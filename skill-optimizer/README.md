# skill-optimizer

A Claude Code skill that audits and refactors other skills so they spend fewer tokens without losing quality. It measures what a skill loads and what its real sessions spent, proposes changes ordered by saving (each one backed by a finding or a number), applies them once you agree, and measures again.

## Install

Copy this folder to `~/.claude/skills/skill-optimizer` (for you) or to `<project>/.claude/skills/skill-optimizer` (for a project). Claude Code picks it up without a restart.

The scripts need [uv](https://docs.astral.sh/uv/), which brings the Python and the libraries they declare (PyYAML). The skill checks for it itself; to install it beforehand:

```sh
sh ~/.claude/skills/skill-optimizer/scripts/doctor.sh --install --dry-run   # macOS, Linux, Git Bash: shows the command
sh ~/.claude/skills/skill-optimizer/scripts/doctor.sh --install             # installs uv and prepares the scripts
```

On Windows PowerShell: `powershell -NoProfile -ExecutionPolicy Bypass -File "$HOME\.claude\skills\skill-optimizer\scripts\doctor.ps1" -Install -DryRun`, then `-Install`. It uses Scoop or winget on Windows, Homebrew on macOS, and the official installer otherwise.

## Use

Ask Claude in your own words, for example:

- "optimize the skill my-skill" (measures, shows a plan, applies it after your OK, measures again)
- "why does my-skill use so many tokens?" (audit only: measures and proposes, changes nothing)
- `/skill-optimizer audit my-skill`

For a skill you did not write (a plugin's or a synced one), it offers to work on a copy.

## What is inside

| Path | What |
|---|---|
| `SKILL.md` | the workflow Claude follows |
| `references/` | the patterns, how to write cheap scripts and subagents, how to measure (read on demand) |
| `scripts/audit.py` | static audit of a skill: what it loads and what to fix |
| `scripts/tokens.py` | where real sessions spent their tokens, from the local transcripts in `~/.claude/projects` (nothing leaves your machine) |
| `scripts/doctor.sh`, `doctor.ps1` | checks and installs uv |
| `assets/templates/` | starting points for the target skill: a checker, start and finish scripts, a subagent, a plugin manifest |

The scripts also run by hand: `uv run scripts/audit.py <skill-folder>` and `uv run scripts/tokens.py list --skill <name>` (`--help` on each).
