#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""ADAPT: closes a SKILL task in one call - changes outside the scope, leftovers, the check on changed files.

Compares with the baseline start.py recorded and ends with FINISH OK or FINISH: n problem(s); the task is reported as
done only after FINISH OK. Template from skill-optimizer: replace the parts marked ADAPT.
"""
from __future__ import annotations

import argparse
import fnmatch
import json
import sys
from pathlib import Path

import check
import start

LEFTOVERS = ["*.orig", "*.rej", "*.bak", "Probe*.*"]  # ADAPT: files a task must not leave behind


def allowed(path: str, allow: list[str]) -> bool:
    return any(path == a or (a.endswith("/") and path.startswith(a)) or fnmatch.fnmatch(path, a) for a in allow)


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("root", nargs="?", default=".", help="folder the task worked on (default: .)")
    args = p.parse_args()
    root = Path(args.root).resolve()
    saved = start.baseline_path(root)
    if not saved.is_file():
        print(f"No baseline for {root.as_posix()}: run start.py first.")
        return 2
    base = json.loads(saved.read_text(encoding="utf-8"))
    now = start.snapshot(root)
    changed = sorted(f for f in now if base["files"].get(f) != now[f])
    deleted = sorted(f for f in base["files"] if f not in now)
    problems = 0
    print(f"-- Changes: {len(changed)} changed or added, {len(deleted)} deleted")

    if base["allow"] is not None:
        for f in changed + deleted:
            if not allowed(f, base["allow"]):
                print(f"{f} [scope] changed, but scope {','.join(base['scope'])} allows {', '.join(base['allow']) or 'nothing'}")
                problems += 1
    for f in changed:
        if any(fnmatch.fnmatch(Path(f).name, g) for g in LEFTOVERS):
            print(f"{f} [leftover] remove it before finishing")
            problems += 1

    print("-- Check (changed files)")
    found = [p for p in check.run(root) if p[0] in set(changed)]
    check.report(found)
    problems += len(found)
    # ADAPT: the verification (build, tests, scenarios) through check.run_logged, printing one line and the log path

    print("FINISH OK" if not problems else f"FINISH: {problems} problem(s)")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
