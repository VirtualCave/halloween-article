---
name: skill-optimizer
description: Audits and refactors a Claude Code skill so it spends as few tokens as possible without losing quality - measures what the skill loads and what its real sessions spent, then moves deterministic work into scripts, decisions into a start script, detail into on-demand references and delegation into plugin subagents with a fixed model, minimal tools and bounded answers, and measures again. Installs what its scripts need. Use when the user wants a skill cheaper, faster or leaner, asks why a skill or a session burns so many tokens or fills the context, or wants the lessons of one skill applied to another - even without saying "tokens".
---

# Skill optimizer

A skill spends tokens at four levels: its description and its agents' descriptions sit in every session, used or not; `SKILL.md` loads when it triggers and stays for the rest of the conversation; references load when the model opens them; and the work itself (tool output, subagent hand-offs, retries) is usually the largest, because every call re-reads the whole context. This skill measures those levels in a target skill, proposes changes ordered by saving, applies them once the user agrees and measures again. The patterns come from `tech-tutorial`, a skill for Java tutorial repositories that was refactored this way: the references quote it as the worked example, and it does not need to be installed.

`<skill>` is this skill's directory, `${CLAUDE_SKILL_DIR}` (quote it: Windows paths have backslashes). The scripts cost no model tokens and print short summaries: read their output, not the files they parse; `--help` lists the options.

| Script | Does |
|---|---|
| `doctor.sh`, `doctor.ps1` | checks `uv`, which runs the Python scripts and installs the Python and libraries they declare, and prints the install command for this system; `--install --dry-run` (`-Install -DryRun`) shows the plan, `--install` runs it and prepares the scripts |
| `audit.py <target>` | static audit: each level in characters and ~tokens, then findings `file:line [rule] message`; `--save <json>` before changing, `--compare <json>` after |
| `tokens.py list --skill <name>` | sessions in `~/.claude/projects` that invoked the skill, last active first, with weighted tokens |
| `tokens.py show <session>` | where a session spent: per model with context per call, main versus each subagent and its answer, tools, the tool results that cost most (size × the later calls that carried them), the skill's files read or run, compactions |

Run the Python scripts as `uv run "<skill>/scripts/<name>.py" ...`. If `uv` is not found, run the doctor (`sh "<skill>/scripts/doctor.sh"`, or in PowerShell `powershell -NoProfile -ExecutionPolicy Bypass -File "<skill>/scripts/doctor.ps1"`), show the user the plan and run `--install` only after a yes.

## Modes

- **optimize** (default): measure, plan, apply after the user's OK, measure again.
- **audit**: measure and plan only, then offer to apply. For "why does X use so many tokens", for a review, and for skills the user does not own (synced or plugin skills: offer to work on a copy).

## Rules

- Quality first. The work that decides the result (writing, design, naming, diagnosis, reviewing what subagents did, the final report) stays on the main model with full context; optimize the mechanical work around it. A saving that lowers the target's eval pass rate is a regression.
- Evidence before change: every change in the plan cites an audit finding or a number from a session. Guesses about where tokens go are usually wrong; tool output and the number of calls tend to outweigh all the prose.
- Understand before cutting. A sentence that looks redundant often encodes a past failure: move it where it applies (a reference, a script check, an agent's instructions) and keep its why, instead of deleting it.
- Touch only the target skill. Snapshot it before editing, keep its language and voice, do not commit unless asked.
- New scripts use the runtime the target's domain already needs (tech-tutorial: Java through JBang, since every tutorial needs a JDK), else Python run by uv. A new runtime is a prerequisite for every user, so the target also gets a doctor that installs it.
- After adding or changing `agents/` or `.claude-plugin/`, the user runs `/reload-plugins` before the agents can be called; `SKILL.md` changes load live.

## Workflow

Report progress briefly.

1. **Snapshot and measure.** Copy the target to `<scratchpad>/<name>-before/`. `audit.py <target> --save <scratchpad>/<name>-before.json`; `tokens.py list --skill <name>`, then `tokens.py show` on one to three sessions (the costliest and a typical one). Without sessions, say so and plan from the audit and the text.
2. **Read the target** with the Read tool, not `cat` (a large shell output is saved to a file you then read a second time): `SKILL.md`, every reference and agent, each script's `--help` (its source only when needed). Note which steps are mechanical, which decide quality, and which instructions encode a lesson.
3. **Plan** (`references/patterns.md`). A table: change, pattern, evidence, saving (level and rough tokens per run), risk to quality; the biggest saving per risk first. Show it and wait for the OK; in audit mode, stop here.
4. **Apply** in plan order: scripts with `references/scripts.md` and `assets/templates/`, subagents with `references/subagents.md`. Run every script you write on a real input and read what it prints, not only its exit code.
5. **Measure again** (`references/measuring.md`): `audit.py <target> --compare <before.json>`, then the target's evals or one representative task, compared with `tokens.py show`. Report before and after per level, separate what was measured from what is estimated, and remind the user of `/reload-plugins` when agents changed.
