# Token-cheap scripts

## Runtime and dependencies

- Use the runtime the target's domain already needs: a Java skill, JBang (`//JAVA 21+`, `//DEPS group:artifact:version`); a Node project skill, node. Otherwise Python run by uv. Shell only for the doctor, which must run before any runtime exists, and for one-liners.
- Python with uv: the script declares its Python and libraries in a PEP 723 header, and `uv run script.py` installs both into uv's cache on the first run (later runs start in a fraction of a second), so nothing is installed system-wide and `pip` never meets an externally managed Python.

  ```python
  #!/usr/bin/env -S uv run --script
  # /// script
  # requires-python = ">=3.10"
  # dependencies = ["pyyaml>=6.0"]
  # ///
  ```

- Libraries: the standard library first; a library when it replaces fragile code (a real YAML or TOML parser, HTTP with retries, a Markdown parser), widely used and maintained, with a minimum major version.
- The doctor: copy `<skill>/scripts/doctor.sh` and `doctor.ps1` and change the tools. Its contract: one line per tool, `ok <tool> <version> (<path>)` or `MISSING <tool>: <why the skill needs it>` with an `install:` line for this system and package manager (Scoop or winget on Windows, Homebrew on macOS, the official installer or the distribution's manager on Linux) and a manual-install link; tools installed but not yet on `PATH` found by their usual folders and called by full path; `--install --dry-run` prints the plan, `--install` runs it, only after the user's yes, with the installer's output in a log file (package managers print pages: Scoop alone printed 170 KB updating its buckets) and only its last lines shown on failure; with `--install`, a warm-up run of one script so the first real run does not download anything; a last line `DOCTOR OK` or `DOCTOR: n missing`. When the skill has subagents, it also prints the `ENV` line their prompts carry.

## The output contract

```
README.md:42 [doc-ref] names jbang alias 'load', not in jbang-catalog.json
src/Main.java:7 [non-english] comment: "Crea el cliente"
... 3 more [non-english] in src/Main.java (--max)
CHECK: 5 problem(s) - full log: /tmp/check-20261029.log
```

- One line per problem, `file:line [rule] message`, paths relative and with `/`: the model goes straight to the place.
- Capped per file and rule (`--max`, default 5) with a `... n more` line: the sixth identical line teaches nothing the first five did not.
- A last status line the model can trust, `CHECK OK` or `CHECK: n problem(s)`; exit 0 clean, 1 problems, 2 usage error.
- Long output (builds, tests, tool logs) goes to a file: print its path and the lines that matter (the failing test and its first message line). The model opens the log only when the summary is not enough.
- Filters to the task: `--changed` (files changed since the baseline or the last commit), `--only` and `--skip` rules. Split option lists on commas and spaces: PowerShell passes `a,b` as `a b`.
- Self-documenting: `--help` lists the options and rules; a script that reads a data file prints its format with `--format`. A model that reads a thousand-line source to learn one flag has lost the saving.
- UTF-8 output whatever the console default (`sys.stdout.reconfigure(encoding="utf-8")`), no colours, no progress bars, no banners.
- Deterministic and idempotent: the same input prints the same lines; `--apply` changes only what it reported.

## Start and finish

- **start** (template `assets/templates/start.py`): takes the scopes and the folder; runs the doctor for the tools those scopes need, records the baseline, runs the first check, and prints sections (`-- Doctor`, `-- Check`) and then `NEXT` lines: the references to read, the delegations with their inputs already grouped (above the thresholds), the closing step. The scope table lives in the script, not in `SKILL.md`.
- **baseline**: what the task starts from (file hashes or `git status`, plus what a task may leave behind: listening ports, running containers) and the scope, stored outside the work tree (`.git/<skill>-baseline.json`, or the temp folder).
- **finish** (template `finish.py`): compares with the baseline: changes outside the scope's allowed paths, leftovers, the check on changed files only, the verification (build, tests, scenarios: one line and a log path each); one `FINISH OK` line.
- Compose in one process: start and finish import the check (`import check`) instead of spawning it, so there is one runtime start-up and one output. The templates import each other: keep them in the same folder.

## Data files

JSON with a `_comment` describing the format, or a `--format` option of the script that reads it; every fact with the date it was checked, so old entries get re-verified instead of trusted.

## Platform notes

- Windows: `python3` may be the Microsoft Store stub, which `uv run` avoids. Git Bash eats unquoted backslashes: quote Windows paths or write them with `/`. Reading files: `encoding="utf-8", errors="replace"`.
- Paths in the output relative to the root, with `/`.

## Testing a script

Run it on a real input and read the output: a generator that "succeeds" but writes an empty table is a failure. Run `--help`. A clean input must print the OK line, and a broken one the problem with its location.
