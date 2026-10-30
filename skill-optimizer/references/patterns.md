# Optimization patterns

Each pattern has the signal that shows it applies (an `audit.py` rule or something `tokens.py show` reveals), the change, and how `tech-tutorial` does it. Plan only with the signals you found: a pattern without a signal is not a saving.

## Where the tokens go

| Level | What | When it costs | Lever |
|---|---|---|---|
| Listing | the skill's `description` (+ `when_to_use`, cut at 1,536 characters); every plugin agent's `description` | every session, whether the skill is used or not | short, key use case first; agents in one line |
| Trigger | `SKILL.md` body | from the invocation on, re-read by every later call; not reloaded, and after a compaction maybe only its start survives | a router: scripts, scopes, rules, one line per step |
| On demand | references, templates, script sources | when the model opens them | read only what the scope needs; scripts print formats so nobody reads their source |
| Work | tool results, file reads, subagent answers, retries | each result is re-read by every later call until a compaction | fewer calls, short outputs |
| Subagents | system prompt, tool schemas, CLAUDE.md, prompt, own work | per subagent; only its answer reaches the main context | thresholds, cheaper model, minimal tools, `omitClaudeMd` |

Every call re-reads the whole context, so the main thread costs roughly calls × context per call. In a `tech-tutorial` session that reviewed a dozen tutorials (461 main calls, 357k tokens of context per call), cache reads were 82% of the main thread's weighted tokens: the prose of the skill was noise next to that. Two levers follow: fewer calls (a script that does ten steps in one call saves ten re-reads of everything) and a smaller context (every byte of tool output kept is paid on every later call, and brings the compaction closer). `tokens.py show` prints both: `ctx/call`, and each result's carried tokens.

## A. Scripts do the deterministic work

**A1. One script per check or transformation the model would do by hand.**
Signal: the skill lists commands to run and outputs to inspect, or checks to make by reading and grepping; `tokens.py show` has many Bash, Read or Grep calls of the same shape in every session; subagents write throwaway helper scripts; `audit.py` `script-candidate`.
Change: a script in `scripts/` that does it and prints a summary (`scripts.md`, template `check.py`). A run costs one call and what it prints.
tech-tutorial: `Lint` (20 rules comparing the README with the repository), `Versions` (outdated versions, `--apply`), `Rename` (git mv plus every reference), `Verify` (three builds, flaky tests).
Not when the check needs judgement (is this explanation clear?): keep it on the model, and let a script narrow where to look.

**A2. Summaries, not logs.** One line per problem, capped per file and rule, a last status line, the full log in a file whose path is printed, filters to what the task touched, `--help` and `--format` instead of the source (the contract is in `scripts.md`).
tech-tutorial: `Lint --changed --max`; `Verify` prints one line per build and the log path; `Scenarios --format`.

**A3. Quiet commands, targeted reads.** Signal: `audit.py` `noisy-command`; the costliest results in `tokens.py show` are build or install logs, recursive searches or whole files. Change: the quiet flag with output to a file the model greps, or a script that runs the command and summarizes; name the exact thing to read.
tech-tutorial: `mvn -B -ntp -q` redirected to a file; `javap` on one jar instead of grepping `~/.m2`.

## B. Scripts decide and close

**B1. A start script turns the request into next steps.** Signal: tables in `SKILL.md` of "for this request read X, delegate Y, run Z with W" that the model reads whole to pick one row; sessions that open several references to decide what to do. Change: `start.py --scope <scope>` runs the set-up (doctor, baseline, first check) and prints `NEXT` lines: the references to read, the delegations with their inputs already grouped, the closing step. `SKILL.md` keeps one line per scope (template `start.py`).
tech-tutorial: `Start --scope translate,upgrade` prints the translator groups, the major upgrades with their migration guides for the fact-checker, and the references of those scopes only.

**B2. A finish script closes the task in one call.** Signal: an end-of-task checklist of manual checks; tasks reported as done that were not. Change: `finish.py` compares with the baseline start recorded: changes outside the scope, leftovers, the check on changed files only, the verification; one `FINISH OK` line, and the task is reported as done only after it (template `finish.py`).
tech-tutorial: `Finish --verify --scenarios`, which also prints the `code-review` level the diff deserves.

**B3. Proof as data.** Signal: the verification re-executes a list of manual steps every time. Change: write the expected behaviour once as a data file with a runner script; drafting it is delegated once, every later check costs one call.
tech-tutorial: `docs/scenarios.json` and `Scenarios` (`--draft`, `--check`, `--only`).

**B4. Rules that must always hold are checked, not repeated.** Signal: emphatic rules (ALWAYS, NEVER) that sessions still break. Change: a check in the finish script, or a hook in the skill's `hooks` frontmatter: prose costs tokens every time and still gets skipped; a check costs nothing and does not forget.
tech-tutorial: "touch only what the request needs" is enforced by `Finish`, which flags changes outside the scope `Start` recorded.

## C. Load less

**C1. `SKILL.md` is a router.** Signal: `audit.py` `body-lines` or `body-chars`; how-to detail that only some tasks need. Change: keep what the skill is, the scripts table, the scopes, the rules for every task and one line per workflow step pointing to its reference; move the rest to `references/<step>.md`, read when that step runs or when the start script prints it. Put the most important instructions first: after a compaction only the start may survive.
tech-tutorial: a 7 KB `SKILL.md`; six references of 3-10 KB, read per scope.

**C2. Knowledge as data.** Signal: lists of facts in prose (versions, known bugs, mappings, exceptions). Change: a JSON file a script reads and applies, each entry with the date it was checked; the model adds an entry instead of reading the list.
tech-tutorial: its `known-issues.json` (blocked upgrades, deprecations, redundant dependencies, migration guides), read by `Versions`.

**C3. Say it once.** Signal: `audit.py` `duplicate`. A text in `SKILL.md` and in a reference is paid twice when both load: keep it where it applies, point to it from elsewhere.

**C4. Descriptions.** The skill's: what it does and when, key use case first, under 1,536 characters (the listing cuts the rest, and when the listing overflows its budget the least used skills lose their description). Each agent's: one line starting `<skill> only -`, so the main model does not pick it for other work (`audit.py` `agent-description`). A skill only ever run as `/name`: `disable-model-invocation: true` takes it out of the listing.

**C5. Templates and copied files, not inline examples.** Signal: long code blocks in `SKILL.md` or references that the model copies into new files. Change: files in `assets/templates/`, read only when one is created; files installed unchanged are copied by a script and never read.
tech-tutorial: its README and `Script.java` templates; `Init` copies `Diagrams.java` and `palette.d2`.

## D. Subagents: the right work, the right model, short answers

**D1. Plugin agents with a fixed frontmatter.** Signal: `audit.py` `no-agents`, `plugin-missing`, `agent-model`, `agent-tools`; long subagent prompts written in `SKILL.md` or references and re-sent each time; `general-purpose` subagents with no model. Change: `.claude-plugin/plugin.json` in the skill folder and `agents/<agent>.md` with model, effort, minimal tools, `maxTurns` and `omitClaudeMd`; the prompt then carries only inputs (`subagents.md`).

**D2. Delegate above a threshold, to the cheapest model a check can back.** Signal: subagents for a handful of files (in `tokens.py show`, a subagent whose weighted tokens are mostly start-up: few calls, small work); everything on the main model; a main thread whose context per call keeps growing with output it never needs again. Change: the routing table and thresholds in `subagents.md`, computed by the start script.
tech-tutorial: translator above 5 files (groups of about 8), inventory above 15 source files.

**D3. Bounded answers.** Signal: `audit.py` `agent-answer`; answers of thousands of tokens in `tokens.py show`. Change: status first, at most N lines, `file:line: problem`, long output to a scratchpad file, no nested subagents (`subagents.md`).

**D4. Do not repeat what scripts settle.** The agent's instructions name what the scripts already check, and the prompt passes their output as input.
tech-tutorial: `inventory`: "Lint already checks ... do not repeat that work".

**D5. One environment line in every prompt.** Signal: subagents that fail on the environment and report guesses as findings. Change: the doctor or start script prints an `ENV` line (tool versions, paths) that goes in every subagent prompt, also in those of the skills the task invokes.

**D6. Verify, escalate, stop.** A cheaper model's mistakes sound as sure as its findings: rerun the script before acting on its result; never resend a `BLOCKED` task unchanged; after three failed fixes of one thing, report (`subagents.md`).

**D7. Fork noisy, self-contained work.** A skill or step whose work is long and noisy, and whose caller needs only the result, can run as `context: fork` (with `agent:`), so its tool output never enters the conversation. Not for work that needs the conversation or questions to the user. tech-tutorial does not need it: its noisy work goes through scripts.

## E. Avoid rework

**E1. A doctor for prerequisites.** Signal: sessions that spend calls discovering a missing tool or a broken path, or guessing install commands. Change: a doctor that checks each prerequisite and its version, prints the install command for the system and package manager found, finds fresh installs not yet on `PATH`, and installs only after the user's yes (`--install --dry-run` shows the plan). Prefer runners that provision the rest: JBang downloads the JDK and the dependencies, uv the Python and the libraries a script declares, so the runner is the only prerequisite. Start from this skill's `scripts/doctor.sh` and `doctor.ps1` (a shell script, because it must run before any runtime exists).
tech-tutorial: `Doctor --install --dry-run` (Scoop, Homebrew, SDKMAN), run by `Start`.

**E2. Edit tools for source files.** Shell heredocs and generated scripts drop backslashes (Git Bash on Windows) and break encodings; every broken file is a retry. Say so in the rules of a target that writes code.

**E3. All the evidence once, one change at a time.** For a failure: collect every layer in one pass, change one thing, rerun only that; after three failed fixes, report.

**E4. Batch.** Independent reads and commands in one message; independent subagents in one message.

**E5. A progress file for long work over many units**, so a context reset or a compaction does not redo verified units.
tech-tutorial: `Review --progress PROGRESS.md`.

**E6. Pick the level of the skills it calls.** When the target invokes another skill with a level (a code review), a script picks it from the size of the change, and skips it when there is nothing to review.
tech-tutorial: `Finish` prints `skip code-review` or `code-review medium` (`low` returns too little to trust).
