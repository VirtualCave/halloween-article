#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["pyyaml>=6.0"]
# ///
"""Static token audit of a Claude Code skill: what each level loads, and what to fix.

Prints the levels (listing, trigger, on demand) in characters and ~tokens (characters / 4), then one line per
finding, file:line [rule] message, at most --max per rule, and a last line AUDIT OK or AUDIT: w warning(s), n note(s).
Exit code 0 without warnings, 1 with warnings, 2 on a usage error. --save writes the measures and findings to a JSON
file; --compare reads such a file and prints what changed since.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

import yaml

RULES = {
    # rule: (severity, what it flags)
    "frontmatter": ("warn", "SKILL.md without parseable frontmatter, name or description"),
    "description-cap": ("warn", "description + when_to_use over 1,536 characters: the skills listing cuts the rest"),
    "description-long": ("note", "description over 1,024 characters: the limit for skills uploaded to claude.ai or the API"),
    "body-lines": ("warn", "SKILL.md body over --body-lines lines"),
    "body-chars": ("note", "SKILL.md body over --body-chars characters: every later call of the conversation carries it"),
    "missing-file": ("warn", "a path to a skill file (references/, agents/, assets/, scripts/) that does not exist;"
                             " ignore it when the path belongs to the user's project"),
    "orphan-reference": ("note", "a reference (a Markdown file outside SKILL.md, agents/, scripts/ and assets/) that no"
                                 " other skill file names: never loaded, or loaded blind"),
    "reference-toc": ("note", "a reference over 300 lines without a table of contents near its top"),
    "duplicate": ("note", "the same long line in SKILL.md and a reference, or in two references: paid twice when both"
                          " load (agents are left out: each runs in its own context)"),
    "plugin-missing": ("warn", "agents/ without .claude-plugin/plugin.json: the agents never load as subagent types"),
    "agent-model": ("warn", "an agent without model: it may run on the main, most expensive model"),
    "agent-tools": ("warn", "an agent without tools: it inherits every tool, and every tool schema is context"),
    "agent-fields": ("note", "an agent without effort, maxTurns or omitClaudeMd"),
    "agent-description": ("note", "an agent description over 200 characters, or not starting '<skill> only -':"
                                  " it sits in every session's context"),
    "agent-answer": ("note", "an agent whose instructions set no status line (DONE/BLOCKED) or no length bound"),
    "agent-nested": ("note", "an agent that may start subagents (Agent or Task in its tools)"),
    "agent-skills": ("note", "an agent that preloads skills: their full content in every run"),
    "no-agents": ("note", "SKILL.md tells to dispatch subagents but the skill defines none: prompts re-sent, models"
                          " not fixed"),
    "script-candidate": ("note", "many shell blocks and no scripts/: repeated command sequences cost model tokens"),
    "script-help": ("note", "a script without --help: the model reads its source to learn how to call it"),
    "noisy-command": ("note", "a command in the instructions that prints far more than the model needs"),
    "no-evals": ("note", "no evals/: a change cannot be measured on the same task before and after"),
}

TEXT_SUFFIXES = {".md", ".txt", ".json", ".yaml", ".yml", ".py", ".java", ".kt", ".sh", ".ps1", ".js", ".mjs", ".ts",
                 ".d2", ".xml", ".toml", ".html", ".css", ".csv", ".properties", ".sql", ".rb", ".go"}
IGNORED_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", "target", "build", "dist", ".idea", ".vscode"}
SHELL_LANGS = {"bash", "sh", "shell", "console", "zsh", "powershell", "pwsh", "ps1", "cmd", "bat"}
SCRIPT_HELP = {  # suffix: what shows the script documents its options
    ".py": re.compile(r"argparse|click|typer|--help"),
    ".java": re.compile(r"mixinStandardHelpOptions|--help"),
    ".kt": re.compile(r"--help"),
    ".sh": re.compile(r"--help|usage", re.I),
    ".ps1": re.compile(r"\.SYNOPSIS|param\s*\(|--help", re.I),
    ".js": re.compile(r"--help"), ".mjs": re.compile(r"--help"), ".ts": re.compile(r"--help"),
}
PATH_REF = re.compile(r"(?:(?<=[\s`'\"(\[])|(?<=<skill>/)|(?<=\}/)|^)"
                      r"((?:references|agents|assets|scripts)/[\w./-]*\w\.\w+)")
HUMAN_DOCS = {"README", "CHANGELOG", "LICENSE", "CONTRIBUTING"}  # at the skill root: for people, never loaded
# an instruction to delegate, not a mention of subagents
DELEGATION = re.compile(r"\b(?:dispatch|spawn|launch|start|delegate to|call)\b[^.]{0,40}\bsub-?agents?\b"
                        r"|subagent_type|\bgeneral-purpose\b|\bAgent tool\b|\bTask tool\b", re.I)
STATUS = re.compile(r"\bDONE\b.*\bBLOCKED\b|\bBLOCKED\b.*\bDONE\b", re.S)
BOUND = re.compile(r"\bat most \d+|\b\d+ lines\b|\bno more than \d+|\bmaximum of \d+", re.I)
NOISY = [
    (re.compile(r"(?<![\w-])(?:\./)?mvnw?(?:\.cmd)?\s+(?![\d.]+\b)(?!.*(?:\s-q\b|--quiet))"),
     "Maven without -q prints every plugin step"),
    (re.compile(r"(?<![\w-])(?:\./)?gradlew?(?:\.bat)?\s+(?![\d.]+\b)(?!.*(?:\s-q\b|--quiet))"), "Gradle without -q"),
    (re.compile(r"\bnpm\s+(?:install|i|ci)\b(?!.*(?:--silent|\s-s\b|--quiet|--loglevel))"), "npm install without --silent"),
    (re.compile(r"\bpip3?\s+install\b(?!.*(?:\s-q\b|--quiet))"), "pip install without -q"),
    (re.compile(r"\bdocker\s+build\b(?!.*(?:\s-q\b|--quiet))"), "docker build without -q"),
    (re.compile(r"\bdocker[ -]compose\s+(?:-f\s+\S+\s+)*up\b(?!.*(?:\s-d\b|--detach))"),
     "compose up in the foreground streams every log"),
    (re.compile(r"\bpytest\b.*\s-v+\b"), "pytest -v prints every test"),
    (re.compile(r"\b(?:grep|rg)\s+(?:-\w*[rR]\w*\s+)?.*(?:~/\.m2|node_modules|\$HOME\b|\s~/?(?:\s|$))"),
     "a recursive search over a home, cache or node_modules folder"),
    (re.compile(r"\bfind\s+/(?:\s|$)"), "find over the whole disk"),
]


def tok(chars: int) -> int:
    return round(chars / 4)


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def split_frontmatter(text: str):
    """(frontmatter text or None, body, number of lines the frontmatter takes)."""
    m = re.match(r"\A---[ \t]*\r?\n(.*?)\r?\n---[ \t]*(?:\r?\n|\Z)", text, re.S)
    if not m:
        return None, text, 0
    return m.group(1), text[m.end():], m.group(0).count("\n")


def parse_frontmatter(text: str):
    """(dict or None, body, offset, error)."""
    fm, body, offset = split_frontmatter(text)
    if fm is None:
        return None, body, 0, "no frontmatter"
    try:
        data = yaml.safe_load(fm)
    except yaml.YAMLError as e:
        return None, body, offset, f"unparseable YAML: {str(e).splitlines()[0]}"
    return (data if isinstance(data, dict) else {}), body, offset, None


def files_under(root: Path, folder: str) -> list[Path]:
    base = root / folder
    if not base.is_dir():
        return []
    return sorted(p for p in base.rglob("*")
                  if p.is_file() and not IGNORED_DIRS & set(p.relative_to(root).parts))


RUN_VERB = re.compile(r"\b(?:run|runs|running|execute|call|use|with|then|try)\W{0,3}$", re.I)


def commands(text: str):
    """(line number, command) for every fenced line and every inline span the prose tells to run ('run `x`');
    spans that only name something (`mvn test` runs the unit tests) are left out."""
    fence = None
    for n, line in enumerate(text.splitlines(), 1):
        stripped = line.strip()
        if stripped.startswith("```") or stripped.startswith("~~~"):
            fence = None if fence else stripped[3:].strip().lower() or "text"
            continue
        if fence:
            yield n, line
        else:
            for m in re.finditer(r"`([^`]+)`", line):
                if RUN_VERB.search(line[max(0, m.start() - 25):m.start()]):
                    yield n, m.group(1)


def fences(text: str) -> list[str]:
    return [m.group(1).lower() for m in re.finditer(r"^\s*```\s*([\w+-]*)", text, re.M)][::2]


def prose_lines(text: str):
    """(line number, line) outside fenced blocks."""
    fence = False
    for n, line in enumerate(text.splitlines(), 1):
        if line.strip().startswith(("```", "~~~")):
            fence = not fence
            continue
        if not fence:
            yield n, line


class Audit:
    def __init__(self, root: Path, body_lines: int, body_chars: int):
        self.root = root
        self.body_lines = body_lines
        self.body_chars = body_chars
        self.findings: list[dict] = []
        self.measures: dict[str, int] = {}
        self.details: dict[str, str] = {}

    def add(self, path: Path | str, line: int, rule: str, message: str):
        rel = path if isinstance(path, str) else path.relative_to(self.root).as_posix()
        self.findings.append({"file": rel, "line": line, "rule": rule, "severity": RULES[rule][0], "message": message})

    def run(self):
        root = self.root
        skill_md = root / "SKILL.md"
        if not skill_md.is_file():
            raise SystemExit(f"No SKILL.md in {root}: give the folder of a skill.")
        text = read(skill_md)
        meta, body, offset, error = parse_frontmatter(text)
        name = (meta or {}).get("name") or root.name
        self.name = str(name)
        description = str((meta or {}).get("description") or "")
        when = str((meta or {}).get("when_to_use") or "")
        if error or not (meta or {}).get("description") or not (meta or {}).get("name"):
            missing = error or "missing " + " and ".join(k for k in ("name", "description") if not (meta or {}).get(k))
            self.add(skill_md, 1, "frontmatter", missing)
        listing = len(description) + len(when)
        if listing > 1536:
            self.add(skill_md, 1, "description-cap", f"{listing} characters; put the key use case first and cut")
        elif len(description) > 1024:
            self.add(skill_md, 1, "description-long", f"{len(description)} characters")
        body_lines = body.count("\n") + 1
        if body_lines > self.body_lines:
            self.add(skill_md, offset + 1, "body-lines", f"{body_lines} lines; keep a router, move detail to references/")
        if len(body) > self.body_chars:
            self.add(skill_md, offset + 1, "body-chars", f"{len(body):,} characters (~{tok(len(body)):,} tokens)")

        references = [p for p in files_under(root, "references") if p.suffix in TEXT_SUFFIXES]
        agents = [p for p in files_under(root, "agents") if p.suffix == ".md"]
        scripts = [p for p in files_under(root, "scripts")]
        assets = [p for p in files_under(root, "assets") if p.suffix in TEXT_SUFFIXES]
        known = {"references", "agents", "scripts", "assets", "evals", ".claude-plugin"}
        others = [p for p in sorted(root.rglob("*")) if p.is_file() and p != skill_md and p.suffix in TEXT_SUFFIXES
                  and not (known | IGNORED_DIRS) & set(p.relative_to(root).parts)
                  and not (p.parent == root and p.stem.upper() in HUMAN_DOCS)]
        references += [p for p in others if p.suffix == ".md"]  # read on demand like references, wherever they sit
        docs = [skill_md] + [p for p in references if p.suffix == ".md"] + agents
        texts = {p: read(p) for p in {skill_md, *references, *agents, *assets,
                                      *(s for s in scripts if s.suffix in TEXT_SUFFIXES)}}

        agent_desc, agent_body = self.agents(agents, texts)
        ref_sizes = {p: len(texts[p]) for p in references}
        self.measures = {
            "listing.description": tok(listing),
            "listing.agents": tok(agent_desc),
            "trigger.skill_md": tok(len(body)),
            "on_demand.references": tok(sum(ref_sizes.values())),
            "on_demand.agent_bodies": tok(agent_body),
            "on_demand.assets": tok(sum(len(texts[p]) for p in assets)),
            "files.references": len(references),
            "files.agents": len(agents),
            "files.scripts": len(scripts),
        }
        largest = max(ref_sizes, key=ref_sizes.get) if ref_sizes else None
        self.details = {
            "skill_md": f"{len(body):,} ch, {body_lines} lines",
            "description": f"{listing:,} ch",
            "largest": f", largest {largest.name} ~{tok(ref_sizes[largest]):,}" if largest else "",
        }

        self.paths(docs, texts)
        self.orphans(references, texts)
        self.tocs(references, texts)
        self.duplicates([d for d in docs if d not in agents], texts)
        self.delegation(agents, docs, texts)
        self.scripts(scripts, docs, texts)
        self.noisy(docs, texts)
        if not (root / "evals").is_dir():
            self.add(skill_md, 1, "no-evals", "add one case per typical task (skill-creator format) to measure changes")

    def agents(self, agents: list[Path], texts: dict) -> tuple[int, int]:
        desc_total = body_total = 0
        if agents and not (self.root / ".claude-plugin" / "plugin.json").is_file():
            self.add(agents[0], 1, "plugin-missing", "add .claude-plugin/plugin.json (template in skill-optimizer assets)")
        for agent in agents:
            meta, body, offset, error = parse_frontmatter(texts[agent])
            meta = meta or {}
            description = str(meta.get("description") or "")
            desc_total += len(description)
            body_total += len(body)
            if error:
                self.add(agent, 1, "agent-model", f"frontmatter: {error}")
                continue
            if not meta.get("model") or meta.get("model") == "inherit":
                self.add(agent, 1, "agent-model", "set model: haiku for mechanical work, sonnet for judgement")
            tools = meta.get("tools")
            if not tools:
                self.add(agent, 1, "agent-tools", "list only the tools it needs")
            missing = [k for k in ("effort", "maxTurns", "omitClaudeMd") if k not in meta]
            if missing:
                self.add(agent, 1, "agent-fields", "missing " + ", ".join(missing))
            prefix = f"{self.name} only"
            if len(description) > 200 or not description.lower().startswith(prefix.lower()):
                self.add(agent, 1, "agent-description",
                         f"{len(description)} characters" + ("" if description.lower().startswith(prefix.lower())
                                                             else f"; start it with '{prefix} -'"))
            if not STATUS.search(body) or not BOUND.search(body):
                lacks = [w for w, ok in (("status line", STATUS.search(body)), ("length bound", BOUND.search(body)))
                         if not ok]
                self.add(agent, offset + 1, "agent-answer", "no " + " and no ".join(lacks))
            tool_list = tools if isinstance(tools, list) else re.split(r"[,\s]+", str(tools or ""))
            if any(t.split("(")[0] in ("Agent", "Task") for t in tool_list):
                self.add(agent, 1, "agent-nested", "remove Agent/Task, and say 'Do not start subagents.'")
            if meta.get("skills"):
                self.add(agent, 1, "agent-skills", f"preloads {meta.get('skills')}")
        return desc_total, body_total

    def paths(self, docs: list[Path], texts: dict):
        for doc in docs:
            for n, line in enumerate(texts[doc].splitlines(), 1):
                for ref in PATH_REF.findall(line):
                    if not (self.root / ref).exists():
                        self.add(doc, n, "missing-file", ref)

    def orphans(self, references: list[Path], texts: dict):
        for ref in references:
            named = any(ref.name in text for p, text in texts.items() if p != ref)
            if not named:
                self.add(ref, 1, "orphan-reference", "no skill file names it")

    def tocs(self, references: list[Path], texts: dict):
        for ref in references:
            lines = texts[ref].splitlines()
            if len(lines) > 300:
                head = "\n".join(lines[:60]).lower()
                if "contents" not in head and len(re.findall(r"\]\(#", head)) < 3:
                    self.add(ref, 1, "reference-toc", f"{len(lines)} lines")

    def duplicates(self, docs: list[Path], texts: dict):
        seen: dict[str, tuple[Path, int]] = {}
        for doc in docs:
            for n, line in prose_lines(texts[doc]):
                key = " ".join(line.split()).lower()
                if len(key) < 100 or set(key) <= set("|-: "):
                    continue
                if key in seen and seen[key][0] != doc:
                    first, first_line = seen[key]
                    self.add(doc, n, "duplicate", f"same line as {first.relative_to(self.root).as_posix()}:{first_line}")
                seen.setdefault(key, (doc, n))

    def delegation(self, agents: list[Path], docs: list[Path], texts: dict):
        if agents:
            return
        skill_md = docs[0]  # the instructions that run: references only explain
        mentions = [n for n, line in prose_lines(texts[skill_md]) if DELEGATION.search(line)]
        if len(mentions) >= 2:
            self.add(skill_md, mentions[0], "no-agents", f"{len(mentions)} lines dispatch subagents and no agents/ folder")

    def scripts(self, scripts: list[Path], docs: list[Path], texts: dict):
        if not scripts:
            blocks = sum(1 for doc in docs for lang in fences(texts[doc]) if lang in SHELL_LANGS)
            if blocks >= 8:
                self.add(docs[0], 1, "script-candidate", f"{blocks} shell blocks; script the sequences that repeat")
            return
        for script in scripts:
            text = texts.get(script) or read(script)
            suffix = script.suffix or (".sh" if re.match(r"#!.*\b(?:ba|z)?sh\b", text) else "")
            pattern = SCRIPT_HELP.get(suffix)
            if pattern is None or "lib" in script.relative_to(self.root).parts[1:-1]:
                continue
            if not pattern.search(text):
                self.add(script, 1, "script-help", "document its options with --help")

    def noisy(self, docs: list[Path], texts: dict):
        for doc in docs:
            for n, code in commands(texts[doc]):
                for pattern, why in NOISY:
                    if pattern.search(code):
                        self.add(doc, n, "noisy-command", f"{why}: {code.strip()[:70]}")
                        break


def print_levels(a: Audit):
    m, d = a.measures, a.details
    print(f"skill-optimizer audit: {a.name} ({a.root.as_posix()})")
    print("-- Levels (~tok = characters / 4)")
    print(f"listing     description ~{m['listing.description']:,} tok ({d['description']});"
          f" {m['files.agents']} agent descriptions ~{m['listing.agents']:,} tok")
    print(f"trigger     SKILL.md body ~{m['trigger.skill_md']:,} tok ({d['skill_md']})")
    print(f"on demand   {m['files.references']} references ~{m['on_demand.references']:,} tok{d['largest']};"
          f" {m['files.agents']} agent bodies ~{m['on_demand.agent_bodies']:,} tok (one per run);"
          f" assets ~{m['on_demand.assets']:,} tok")
    print(f"not loaded  {m['files.scripts']} script files (they cost only what they print)")


def print_findings(findings: list[dict], max_per_rule: int):
    print("-- Findings")
    order = sorted(findings, key=lambda f: (f["severity"] != "warn", f["rule"], f["file"], f["line"]))
    shown = Counter()
    hidden = Counter()
    for f in order:
        if shown[f["rule"]] < max_per_rule:
            print(f"{f['file']}:{f['line']} [{f['rule']}] {f['message']}")
            shown[f["rule"]] += 1
        else:
            hidden[f["rule"]] += 1
    for rule, k in hidden.items():
        print(f"... {k} more [{rule}] (--max)")
    if not findings:
        print("none")


def compare(before: dict, a: Audit):
    print(f"-- Compared with the saved audit ({before.get('skill', '?')})")
    for key, now in a.measures.items():
        old = before.get("measures", {}).get(key)
        if old is None or old == now:
            continue
        unit = "" if key.startswith("files.") else " tok"
        change = f" ({(now - old) / old:+.0%})" if old else ""
        print(f"{key:<24} {old:,} -> {now:,}{unit}{change}")
    old_rules = Counter(f["rule"] for f in before.get("findings", []))
    new_rules = Counter(f["rule"] for f in a.findings)
    fixed = [f"{r} ({old_rules[r] - new_rules[r]})" for r in sorted(old_rules) if old_rules[r] > new_rules[r]]
    new = [f"{r} ({new_rules[r] - old_rules[r]})" for r in sorted(new_rules) if new_rules[r] > old_rules[r]]
    count = lambda fs, s: sum(1 for f in fs if f["severity"] == s)  # noqa: E731
    print(f"findings: {count(before.get('findings', []), 'warn')} -> {count(a.findings, 'warn')} warning(s),"
          f" {count(before.get('findings', []), 'note')} -> {count(a.findings, 'note')} note(s);"
          f" fewer: {', '.join(fixed) or 'none'}; more: {', '.join(new) or 'none'}")


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    rules = "\n".join(f"  {r:<18} {sev}: {what}" for r, (sev, what) in RULES.items())
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0], epilog="Rules:\n" + rules,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("skill", nargs="?", default=".", help="the skill folder (the one with SKILL.md); default: .")
    p.add_argument("--save", metavar="JSON", help="write the measures and findings to this file (before changing)")
    p.add_argument("--compare", metavar="JSON", help="compare with a file written by --save (after changing)")
    p.add_argument("--only", default="", help="comma-separated rules to report")
    p.add_argument("--skip", default="", help="comma-separated rules to leave out")
    p.add_argument("--max", type=int, default=5, help="findings shown per rule (default 5)")
    p.add_argument("--body-lines", type=int, default=500, help="SKILL.md body lines before body-lines (default 500)")
    p.add_argument("--body-chars", type=int, default=10000, help="SKILL.md body characters before body-chars (default 10000)")
    args = p.parse_args()
    only = {r for r in args.only.split(",") if r}
    skip = {r for r in args.skip.split(",") if r}
    unknown = (only | skip) - RULES.keys()
    if unknown:
        print(f"Unknown rule(s): {', '.join(sorted(unknown))} (see --help)")
        return 2

    a = Audit(Path(args.skill).resolve(), args.body_lines, args.body_chars)
    a.run()
    a.findings = [f for f in a.findings if (not only or f["rule"] in only) and f["rule"] not in skip]
    print_levels(a)
    print_findings(a.findings, args.max)
    if args.compare:
        compare(json.loads(Path(args.compare).read_text(encoding="utf-8")), a)
    if args.save:
        Path(args.save).write_text(json.dumps({"skill": a.name, "measures": a.measures, "findings": a.findings},
                                              indent=1), encoding="utf-8")
        print(f"saved: {Path(args.save).resolve().as_posix()}")
    warnings = sum(1 for f in a.findings if f["severity"] == "warn")
    notes = len(a.findings) - warnings
    print("AUDIT OK" if not a.findings else f"AUDIT: {warnings} warning(s), {notes} note(s)")
    return 1 if warnings else 0


if __name__ == "__main__":
    sys.exit(main())
