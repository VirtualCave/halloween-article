# Measuring

## audit.py

Static, no model. It measures each level in characters and ~tokens (characters / 4: good for comparing the same text before and after, not a price) and lists findings; `--help` lists the rules. Warnings are defects (a description the listing cuts, an agent without model or tools, agents that never load, a pointer to a missing file); notes are candidates to weigh against what the target does. `--save` before the first change and `--compare` after: it prints each measure before and after, and which rules have fewer or more findings.

## tokens.py

Reads the transcripts Claude Code keeps in `~/.claude/projects/<project>/<session>.jsonl` (subagents in `<session>/subagents/`), with the usage the API returned for every call.

- `list --skill <name> [--days 60] [--project <text>]`: the sessions that invoked the skill (Skill tool or `/name`), last active first: session id, project, weighted tokens, those of the subagents (and how many), main calls, compactions, title.
- `show <id|prefix|path> [--top 8]`: usage per model (calls, context per call, input, cache writes, cache reads, output, weighted); each subagent with its type, model, calls, weighted tokens and the size of its answer in the main context; the main thread's tools by calls and result size; its tool results ranked by carried tokens (size × the later calls before the next compaction); the invoked skills' files read, run or edited; compactions. A subagent's own `.jsonl` can be shown the same way.

Weighted tokens = input + 1.25 × cache write (5 min) + 2 × cache write (1 h) + 0.1 × cache read + 5 × output: the price ratios Claude models share, so sessions on the same model compare in one number. Models differ in price: compare rows of the same model, and count work moved from the main model to `haiku` as a saving even when its weighted number does not drop.

What the numbers point to:

| In `show` | Pattern |
|---|---|
| main cache reads dominate (calls × ctx/call) | fewer calls: A1, B1, B2; smaller context: A2, A3 |
| a few results with huge carried tokens | A2, A3, or delegate that step (D2) |
| many calls of the same tool shape | A1 |
| a reference read in every session but needed in few | C1 |
| subagents with few calls whose weighted tokens are mostly start-up | D2 (threshold) |
| subagent answers over about 1k tokens | D3 |
| subagents on the main model | D1 |
| compactions | the work level is too big: carried tokens first |
| large output tokens on the main model | decisions a script could print (B1), text a template could hold (C5) |
| calls spent on missing tools or install attempts | E1 |

## Before and after

- Same task, same model, same effort. Best: the target's evals (`evals/<case>/` in the skill-creator format, which `claude plugin eval` and the skill-creator skill run), whose pass rate must not drop. Otherwise one representative task run on the snapshot and on the new version, twice each if possible: runs of one task vary, so a difference of a few percent proves nothing.
- When nothing can be run, report the static change from `audit.py --compare` and the estimate per pattern, marked as estimates.
- Report:

  | Level | Before | After | Measured with |
  |---|---|---|---|
  | Listing (every session) | | | `audit.py` |
  | Trigger (`SKILL.md`) | | | `audit.py` |
  | On demand per typical task | | | the references the start script prints |
  | Session: weighted main / subagents, calls, ctx/call | | | `tokens.py show` before / after |
  | Evals pass rate | | | evals |

  Then the changes made, and what was not measured.
