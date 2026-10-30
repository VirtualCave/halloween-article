#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Where Claude Code sessions spent their tokens, from the transcripts in ~/.claude/projects.

list: the sessions, newest first, one line each (--skill: only those that invoked a skill).
show: one session in detail - usage per model, main versus each subagent, tools, the tool results that cost most
(their size x the later calls that carried them), the files of the invoked skills read or run, and compactions.
A subagent's own transcript (<session>/subagents/agent-*.jsonl) can be shown too.

Usage comes from the API's numbers in the transcript; tool result sizes are estimates (characters / 4).
Weighted tokens = input + 1.25 x cache write (5 min) + 2 x cache write (1 h) + 0.1 x cache read + 5 x output,
the price ratios shared by Claude models: compare sessions on the same model.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

W_INPUT, W_WRITE_5M, W_WRITE_1H, W_READ, W_OUTPUT = 1.0, 1.25, 2.0, 0.1, 5.0
IMAGE_TOKENS = 1600  # rough cost of one image in a tool result
COMMAND = re.compile(r"<command-name>/([\w.:-]+)</command-name>")
HANDBACK = re.compile(r'<agent-message from="([^"]+)">')  # a background subagent's report, delivered as a message
NOTIFICATION = re.compile(r"<task-notification>.*?<tool-use-id>([^<]+)</tool-use-id>", re.S)
EDIT_TOOLS = {"Edit", "Write", "NotebookEdit", "MultiEdit"}


def config_dir() -> Path:
    base = os.environ.get("CLAUDE_CONFIG_DIR")
    return Path(base) if base else Path.home() / ".claude"


def fmt(n: float) -> str:
    if n >= 1e6:
        return f"{n / 1e6:.2f}M"
    if n >= 1e3:
        return f"{n / 1e3:.1f}k"
    return f"{n:.0f}"


def short_model(model: str) -> str:
    return model.removeprefix("claude-")


@dataclass
class Usage:
    calls: int = 0
    input: int = 0
    write_5m: int = 0
    write_1h: int = 0
    read: int = 0
    output: int = 0

    def add(self, u: dict):
        self.calls += 1
        self.input += u.get("input_tokens") or 0
        split = u.get("cache_creation") or {}
        w5, w1 = split.get("ephemeral_5m_input_tokens"), split.get("ephemeral_1h_input_tokens")
        if w5 is None and w1 is None:
            w5, w1 = u.get("cache_creation_input_tokens") or 0, 0
        self.write_5m += w5 or 0
        self.write_1h += w1 or 0
        self.read += u.get("cache_read_input_tokens") or 0
        self.output += u.get("output_tokens") or 0

    def merge(self, other: Usage):
        for k in ("calls", "input", "write_5m", "write_1h", "read", "output"):
            setattr(self, k, getattr(self, k) + getattr(other, k))

    @property
    def weighted(self) -> float:
        return (self.input * W_INPUT + self.write_5m * W_WRITE_5M + self.write_1h * W_WRITE_1H
                + self.read * W_READ + self.output * W_OUTPUT)

    @property
    def context(self) -> float:
        """Average context per call: what every call re-reads, the lever behind most cache-read cost."""
        return (self.input + self.write_5m + self.write_1h + self.read) / self.calls if self.calls else 0


@dataclass
class Result:
    tool_use_id: str
    chars: int
    images: int
    at_call: int
    segment: int
    carried: int = 0

    @property
    def tokens(self) -> int:
        return round(self.chars / 4) + self.images * IMAGE_TOKENS


@dataclass
class Thread:
    """One transcript: the main conversation or one subagent."""
    path: Path
    usage: dict = field(default_factory=lambda: defaultdict(Usage))
    sidechains: dict = field(default_factory=lambda: defaultdict(Usage))  # older transcripts kept subagents inline
    tool_uses: dict = field(default_factory=dict)  # id -> (name, input)
    results: list = field(default_factory=list)
    compactions: list = field(default_factory=list)
    commands: set = field(default_factory=set)
    title: str | None = None
    start: str | None = None
    cwd: str | None = None
    calls: int = 0

    def total(self) -> Usage:
        u = Usage()
        for part in (*self.usage.values(), *self.sidechains.values()):
            u.merge(part)
        return u


def records(path: Path):
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    yield json.loads(line)
                except json.JSONDecodeError:
                    continue


def result_size(content) -> tuple[int, int]:
    if isinstance(content, str):
        return len(content), 0
    chars = images = 0
    for c in content if isinstance(content, list) else []:
        if isinstance(c, dict) and c.get("type") == "image":
            images += 1
        elif isinstance(c, dict):
            chars += len(c.get("text") or "") if c.get("type") == "text" else len(json.dumps(c))
    return chars, images


def read_thread(path: Path, subagent: bool) -> Thread:
    th = Thread(path)
    seen: set = set()
    segment = 0
    segment_end: dict[int, int] = {}
    for r in records(path):
        th.start = th.start or r.get("timestamp")
        th.cwd = th.cwd or r.get("cwd")
        kind = r.get("type")
        side = bool(r.get("isSidechain")) and not subagent
        if kind == "ai-title":
            th.title = r.get("aiTitle") or th.title
        elif kind == "system" and r.get("subtype") == "compact_boundary":
            m = r.get("compactMetadata") or {}
            th.compactions.append((m.get("trigger"), m.get("preTokens"), m.get("postTokens")))
            segment_end[segment] = th.calls
            segment += 1
        elif kind == "assistant":
            msg = r.get("message") or {}
            key = msg.get("id") or r.get("uuid")
            if key not in seen:  # one API response is split over several lines that repeat its usage
                seen.add(key)
                model = msg.get("model") or "?"
                if msg.get("usage") and model != "<synthetic>":
                    (th.sidechains if side else th.usage)[model].add(msg["usage"])
                    th.calls += 0 if side else 1
            if not side:
                for c in msg.get("content") or []:
                    if isinstance(c, dict) and c.get("type") == "tool_use":
                        th.tool_uses[c.get("id")] = (c.get("name") or "?", c.get("input") or {})
        elif kind == "attachment" and not side:
            prompt = (r.get("attachment") or {}).get("prompt")
            if not isinstance(prompt, str):
                continue
            agent = HANDBACK.search(prompt)
            notice = NOTIFICATION.search(prompt)
            if agent:
                key = f"handback:{agent.group(1)}"
                th.tool_uses[key] = ("handback", {"description": agent.group(1)})
                th.results.append(Result(key, len(prompt), 0, th.calls, segment))
            elif notice:  # counted with the tool call it reports on
                th.results.append(Result(notice.group(1), len(prompt), 0, th.calls, segment))
        elif kind == "user" and not side:
            content = (r.get("message") or {}).get("content")
            if isinstance(content, str):
                th.commands.update(COMMAND.findall(content))
                continue
            for c in content if isinstance(content, list) else []:
                if not isinstance(c, dict):
                    continue
                if c.get("type") == "text":
                    th.commands.update(COMMAND.findall(c.get("text") or ""))
                elif c.get("type") == "tool_result":
                    chars, images = result_size(c.get("content"))
                    th.results.append(Result(c.get("tool_use_id"), chars, images, th.calls, segment))
    segment_end[segment] = th.calls
    for res in th.results:
        res.carried = res.tokens * max(segment_end[res.segment] - res.at_call, 0)
    return th


@dataclass
class Session:
    main: Thread
    subagents: list  # (meta dict, Thread)

    def total(self) -> Usage:
        u = self.main.total()
        for _, th in self.subagents:
            u.merge(th.total())
        return u


def analyze(path: Path) -> Session:
    is_subagent = path.parent.name == "subagents"
    main = read_thread(path, subagent=is_subagent)
    subs = []
    folder = path.with_suffix("") / "subagents"
    if not is_subagent and folder.is_dir():
        for f in sorted(folder.glob("*.jsonl")):
            meta_file = f.with_suffix(".meta.json")
            try:
                meta = json.loads(meta_file.read_text(encoding="utf-8")) if meta_file.is_file() else {}
            except json.JSONDecodeError:
                meta = {}
            subs.append((meta, read_thread(f, subagent=True)))
    return Session(main, subs)


def describe(name: str, inp) -> str:
    if not isinstance(inp, dict):
        return ""
    if name == "Agent":
        text = f"{inp.get('subagent_type', 'general-purpose')} \"{inp.get('description', '')}\""
    else:
        text = next((str(inp[k]) for k in ("command", "file_path", "path", "pattern", "url", "skill", "query",
                                            "prompt", "description") if inp.get(k)), json.dumps(inp)[:80])
        if inp.get("file_path"):
            text = "/".join(re.split(r"[\\/]+", text)[-3:])
    text = " ".join(text.split())
    return text if len(text) <= 60 else text[:57] + "..."


def strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for v in value.values():
            yield from strings(v)
    elif isinstance(value, list):
        for v in value:
            yield from strings(v)


def skills_used(th: Thread) -> list[str]:
    skills_dir = config_dir() / "skills"
    names = [inp.get("skill") for name, inp in th.tool_uses.values() if name == "Skill" and isinstance(inp, dict)]
    names += [c for c in th.commands if ":" in c or (skills_dir / c).is_dir()]
    return sorted({n for n in names if n})


def skill_files(th: Thread, skill: str) -> dict[str, Counter]:
    """read / ran / edited -> Counter of paths inside the skill's folder that the thread's tool calls touched."""
    short = skill.split(":")[-1]
    pattern = re.compile(rf"skills/(?:[^/\s\"'`]+/)*?{re.escape(short)}/([\w./-]+\.\w+)")
    found: dict[str, Counter] = defaultdict(Counter)
    for name, inp in th.tool_uses.values():
        for s in strings(inp):
            for rel in pattern.findall(s.replace("\\", "/")):
                kind = "edited" if name in EDIT_TOOLS else "ran" if rel.startswith("scripts/") else "read"
                found[kind][rel] += 1
    return found


def resolve(arg: str) -> Path:
    p = Path(arg)
    if p.is_file():
        return p
    projects = config_dir() / "projects"
    matches = sorted(projects.glob(f"*/{arg}*.jsonl")) or sorted(projects.glob(f"*/*/subagents/{arg}*.jsonl"))
    if not matches:
        raise SystemExit(f"No session {arg} under {projects.as_posix()} (give an id, an id prefix or a path).")
    if len(matches) > 1:
        raise SystemExit(f"{len(matches)} sessions start with {arg}: give more of the id.")
    return matches[0]


def when(ts: str | None) -> str:
    if not ts:
        return "?"
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone().strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return ts[:16]


def project(th: Thread, path: Path) -> str:
    return Path(th.cwd).name if th.cwd else path.parent.name


def cmd_list(args) -> int:
    projects = config_dir() / "projects"
    cutoff = time.time() - args.days * 86400
    files = [f for f in projects.glob("*/*.jsonl") if f.stat().st_mtime >= cutoff]
    if args.project:
        files = [f for f in files if args.project.lower() in f.parent.name.lower()]
    if args.skill:
        name = re.escape(args.skill)
        used = re.compile(rf'"skill"\s*:\s*"(?:[\w.-]+:)?{name}"|<command-name>/(?:[\w.-]+:)?{name}</command-name>')
        files = [f for f in files if used.search(f.read_text(encoding="utf-8", errors="replace"))]
    files.sort(key=lambda f: f.stat().st_mtime, reverse=True)
    print(f"{'last active':<16}  {'session':<8}  {'project':<22} {'weighted':>9} {'subagents':>10} {'calls':>6}"
          f" {'compact':>7}  title")
    for f in files[:args.limit]:
        s = analyze(f)
        sub = Usage()
        for _, th in s.subagents:
            sub.merge(th.total())
        for u in s.main.sidechains.values():
            sub.merge(u)
        title = (s.main.title or "")[:50]
        active = datetime.fromtimestamp(f.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
        print(f"{active:<16}  {f.stem[:8]:<8}  {project(s.main, f)[:22]:<22} {fmt(s.total().weighted):>9}"
              f" {fmt(sub.weighted) + ' (' + str(len(s.subagents)) + ')':>10} {s.main.calls:>6}"
              f" {len(s.main.compactions):>7}  {title}")
    more = len(files) - args.limit
    print(f"{len(files)} session(s) in the last {args.days} days" + (f", {more} older not shown (--limit)" if more > 0 else ""))
    return 0


def usage_rows(label: str, by_model: dict):
    for model, u in sorted(by_model.items(), key=lambda kv: -kv[1].weighted):
        print(f"{label:<11} {short_model(model):<16} {u.calls:>6} {fmt(u.context):>8} {fmt(u.input):>8}"
              f" {fmt(u.write_5m + u.write_1h):>8} {fmt(u.read):>8} {fmt(u.output):>8} {fmt(u.weighted):>9}")


def cmd_show(args) -> int:
    path = resolve(args.session)
    s = analyze(path)
    main = s.main
    title = f' "{main.title}"' if main.title else ""
    print(f"session {path.stem} ({project(main, path)}, {when(main.start)}){title}")

    print("-- Usage (weighted = input + 1.25 cache write 5m + 2 cache write 1h + 0.1 cache read + 5 output)")
    print(f"{'thread':<11} {'model':<16} {'calls':>6} {'ctx/call':>8} {'input':>8} {'c-write':>8} {'c-read':>8}"
          f" {'output':>8} {'weighted':>9}")
    usage_rows("main", main.usage)
    usage_rows("sidechains", main.sidechains)
    by_model: dict = defaultdict(Usage)
    for _, th in s.subagents:
        for model, u in th.usage.items():
            by_model[model].merge(u)
    usage_rows("subagents", by_model)
    total = s.total().weighted
    main_w = sum(u.weighted for u in main.usage.values())
    print(f"total weighted {fmt(total)}; main {main_w / total:.0%}" if total else "total weighted 0")

    if s.subagents:
        print(f"-- Subagents ({len(s.subagents)}): type \"description\" model, calls, weighted, answer to main")
        answers: Counter = Counter()
        for r in main.results:
            answers[r.tool_use_id] += r.tokens
        for meta, th in sorted(s.subagents, key=lambda mt: -mt[1].total().weighted):
            u = th.total()
            models = ",".join(short_model(m) for m in th.usage) or "?"
            agent_id = th.path.stem.removeprefix("agent-")
            parts = [answers[k] for k in (meta.get("toolUseId"), f"handback:{agent_id}") if k in answers]
            answer = sum(parts) if parts else None
            print(f"{meta.get('agentType', '?')} \"{(meta.get('description') or '')[:40]}\" {models}, {u.calls} calls,"
                  f" {fmt(u.weighted)}, answer {'~' + fmt(answer) + ' tok' if answer is not None else '?'}")

    print("-- Tools in main: calls, results ~tok")
    calls = Counter(name for name, _ in main.tool_uses.values())
    sizes: Counter = Counter()
    for r in main.results:
        sizes[main.tool_uses.get(r.tool_use_id, ("?", None))[0]] += r.tokens
    print(", ".join(f"{name} {calls[name]} ~{fmt(sizes[name])}" for name in sorted(calls, key=lambda n: -sizes[n]))
          or "none")

    print(f"-- Costliest tool results in main: ~tok x later calls = carried (top {args.top})")
    for r in sorted(main.results, key=lambda r: -r.carried)[:args.top]:
        name, inp = main.tool_uses.get(r.tool_use_id, ("?", None))
        later = r.carried // r.tokens if r.tokens else 0
        print(f"{name:<10} {describe(name, inp):<60} {fmt(r.tokens):>6} x {later:<4} = {fmt(r.carried)}")

    skills = skills_used(main)
    print("-- Skills")
    for skill in skills:
        invoked = sum(1 for n, inp in main.tool_uses.values() if n == "Skill" and inp.get("skill") == skill)
        parts = [f"invoked {invoked or 'by /' + skill}"]
        for kind, files in skill_files(main, skill).items():
            parts.append(kind + " " + ", ".join(f"{f}" + (f" x{k}" if k > 1 else "") for f, k in files.most_common()))
        print(f"{skill}: " + "; ".join(parts))
    if not skills:
        print("none")

    print("-- Compactions")
    for trigger, pre, post in main.compactions:
        print(f"{trigger}: {fmt(pre or 0)} -> {fmt(post or 0)} tokens")
    if not main.compactions:
        print("none")
    return 0


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0],
                                epilog=__doc__.split("\n\n", 1)[1], formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="command", required=True)
    ls = sub.add_parser("list", help="sessions, newest first")
    ls.add_argument("--skill", help="only sessions that invoked this skill (Skill tool or /name)")
    ls.add_argument("--project", help="only projects whose folder name contains this text")
    ls.add_argument("--days", type=int, default=60, help="sessions changed in the last N days (default 60)")
    ls.add_argument("--limit", type=int, default=15, help="sessions shown (default 15)")
    show = sub.add_parser("show", help="one session in detail")
    show.add_argument("session", help="session id, id prefix, or path to a .jsonl (also a subagent's)")
    show.add_argument("--top", type=int, default=8, help="costliest tool results shown (default 8)")
    args = p.parse_args()
    return cmd_list(args) if args.command == "list" else cmd_show(args)


if __name__ == "__main__":
    sys.exit(main())
