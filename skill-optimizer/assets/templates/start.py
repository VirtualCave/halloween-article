#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""ADAPT: starts a SKILL task in one call - baseline, first check and the NEXT lines for the scope.

The scope table (references to read, paths the task may change, delegations) lives here, not in SKILL.md: the model
reads the NEXT lines instead of every table. Records the baseline finish.py compares with.
Template from skill-optimizer: replace the parts marked ADAPT; keep check.py and finish.py in the same folder.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tempfile
from pathlib import Path

import check  # same folder: runs in this process, one start-up and one output

SKILL = "SKILL"  # ADAPT
SCOPES = {  # ADAPT: scope -> references to read, in reading order, and the paths it may change (None: any)
    "full": {"references": ["workflow.md", "verification.md"], "allow": None},
    "docs": {"references": ["writing.md"], "allow": ["README.md", "docs/"]},
    "check": {"references": ["verification.md"], "allow": []},
}
DELEGATE_ABOVE = 5  # ADAPT: with this many files or fewer, do it yourself: a subagent's start-up costs more
GROUP_SIZE = 8  # ADAPT: files per subagent


def snapshot(root: Path) -> dict[str, str]:
    """Every file's hash: finish.py tells what changed without needing git."""
    return {p.relative_to(root).as_posix(): hashlib.sha1(p.read_bytes()).hexdigest()
            for p in sorted(root.rglob("*")) if p.is_file() and not check.IGNORED & set(p.relative_to(root).parts)}


def baseline_path(root: Path) -> Path:
    """Outside the work tree: in .git when there is one, else in the temp folder."""
    if (root / ".git").is_dir():
        return root / ".git" / f"{SKILL}-baseline.json"
    return Path(tempfile.gettempdir()) / f"{SKILL}-baseline-{hashlib.sha1(str(root).encode()).hexdigest()[:12]}.json"


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("root", nargs="?", default=".", help="folder the task works on (default: .)")
    p.add_argument("--scope", required=True, help="one or more of " + ", ".join(SCOPES) + ", comma-separated")
    args = p.parse_args()
    root = Path(args.root).resolve()
    scopes = [s for s in args.scope.replace(" ", ",").split(",") if s]
    unknown = [s for s in scopes if s not in SCOPES]
    if unknown or not scopes:
        print(f"Unknown scope {', '.join(unknown)}: use one or more of {', '.join(SCOPES)}.")
        return 2

    references = list(dict.fromkeys(r for s in scopes for r in SCOPES[s]["references"]))
    allows = [SCOPES[s]["allow"] for s in scopes]
    allow = None if None in allows else sorted({a for al in allows for a in al})
    files = snapshot(root)
    baseline_path(root).write_text(json.dumps({"scope": scopes, "allow": allow, "files": files}), encoding="utf-8")
    print(f"-- Baseline: {len(files)} files, scope {','.join(scopes)}")
    # ADAPT: run the doctor for the tools these scopes need, and print its ENV line for the subagent prompts

    print("-- Check")
    found = check.run(root)
    check.report(found)

    print("-- Next")
    print("NEXT read " + ", ".join(f"references/{r}" for r in references))
    flagged = sorted({f for f, *_ in found})
    if len(flagged) > DELEGATE_ABOVE:
        for i in range(0, len(flagged), GROUP_SIZE):
            group = flagged[i:i + GROUP_SIZE]
            print(f"NEXT {SKILL}:AGENT (haiku, low effort), in parallel: {', '.join(group)}")  # ADAPT: the agent
    elif flagged:
        print(f"NEXT fix these {len(flagged)} file(s) yourself: {', '.join(flagged)}")
    print("NEXT at the end: finish.py, and report the task as done only after FINISH OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
