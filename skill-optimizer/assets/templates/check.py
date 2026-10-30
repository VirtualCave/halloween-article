#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""ADAPT: what this script checks, in one sentence.

Prints one line per problem (file:line [rule] message), at most --max per file and rule, and a last line
CHECK OK or CHECK: n problem(s). Exit code 0 when clean, 1 with problems, 2 on a usage error.
Template from skill-optimizer: replace the parts marked ADAPT; start.py and finish.py import this file.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from collections import Counter
from pathlib import Path

NAME = "CHECK"  # ADAPT: the word that starts the last line
RULES = {  # ADAPT: rule -> what it flags; --help lists them, --only and --skip select them
    "marker": "a TODO or FIXME left in a text file",
}
IGNORED = {".git", "node_modules", "target", "build", "dist", ".venv", "__pycache__"}
TEXT = {".md", ".txt", ".py", ".java", ".kt", ".js", ".ts", ".json", ".yaml", ".yml", ".xml", ".sh", ".ps1"}


def problems(root: Path, files: list[Path]):
    """ADAPT: yield (path relative to root with '/', line, rule, message) for every problem."""
    for f in files:
        for n, line in enumerate(f.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            if "TODO" in line or "FIXME" in line:
                yield rel(root, f), n, "marker", line.strip()[:100]


def rel(root: Path, f: Path) -> str:
    return f.relative_to(root).as_posix()


def all_files(root: Path) -> list[Path]:
    return sorted(p for p in root.rglob("*")
                  if p.is_file() and p.suffix in TEXT and not IGNORED & set(p.relative_to(root).parts))


def changed_files(root: Path) -> list[Path] | None:
    """Files changed since the last commit, untracked ones included; None outside a git repository."""
    try:
        out = subprocess.run(["git", "-C", str(root), "status", "--porcelain", "--untracked-files=all"],
                             capture_output=True, text=True, encoding="utf-8", check=True).stdout
    except (OSError, subprocess.CalledProcessError):
        return None
    paths = [root / line[3:].split(" -> ")[-1].strip('"') for line in out.splitlines()]
    return [p for p in paths if p.is_file() and p.suffix in TEXT]


def run_logged(command: list[str], log: Path, tail: int = 5) -> tuple[int, list[str]]:
    """Runs a command with its whole output in `log`: the summary prints the exit, these last lines and the log path."""
    with log.open("w", encoding="utf-8") as out:
        code = subprocess.run(command, stdout=out, stderr=subprocess.STDOUT).returncode
    return code, log.read_text(encoding="utf-8", errors="replace").splitlines()[-tail:]


def run(root: Path, changed: bool = False, only=(), skip=()) -> list[tuple]:
    """The problems as a list, for the scripts that import this one."""
    files = changed_files(root) if changed else None
    found = problems(root, all_files(root) if files is None else files)
    return [p for p in found if (not only or p[2] in only) and p[2] not in skip]


def report(found: list[tuple], max_per: int = 5) -> None:
    shown: Counter = Counter()
    hidden: Counter = Counter()
    for f, n, rule, message in found:
        if shown[f, rule] < max_per:
            print(f"{f}:{n} [{rule}] {message}")
            shown[f, rule] += 1
        else:
            hidden[f, rule] += 1
    for (f, rule), k in hidden.items():
        print(f"... {k} more [{rule}] in {f} (--max)")
    print(f"{NAME} OK" if not found else f"{NAME}: {len(found)} problem(s)")


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0],
                                epilog="Rules: " + "; ".join(f"{r} ({what})" for r, what in RULES.items()))
    p.add_argument("root", nargs="?", default=".", help="folder to check (default: .)")
    p.add_argument("--changed", action="store_true", help="only files changed since the last commit")
    p.add_argument("--only", default="", help="comma-separated rules to run")
    p.add_argument("--skip", default="", help="comma-separated rules to skip")
    p.add_argument("--max", type=int, default=5, help="problems shown per file and rule (default 5)")
    args = p.parse_args()
    only = {r for r in args.only.replace(" ", ",").split(",") if r}  # PowerShell passes a,b as "a b"
    skip = {r for r in args.skip.replace(" ", ",").split(",") if r}
    if (only | skip) - RULES.keys():
        print(f"Unknown rule(s): {', '.join(sorted((only | skip) - RULES.keys()))} (see --help)")
        return 2
    found = run(Path(args.root).resolve(), args.changed, only, skip)
    report(found, args.max)
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
