# Subagents

## Plugin agents in a skill folder

A skill folder with `.claude-plugin/plugin.json` loads as the plugin `<name>@skills-dir`, and each `agents/<agent>.md` becomes the subagent type `<name>:<agent>` (a subfolder adds to the name: `x.md` in `agents/review/` is `<name>:review:x`). After adding or changing them the user runs `/reload-plugins`. Templates: `assets/templates/plugin.json` and `agent.md`.

When the type is not available (plugin not loaded yet, or skills-directory plugins blocked by an administrator), call `general-purpose` with the agent's `model` and `effort` and the prompt "Read `<skill>/agents/<agent>.md` and follow it. Inputs: ...". Write this fallback into the target's instructions.

## Frontmatter

| Field | Value | Why |
|---|---|---|
| `name` | the agent's name, without `:` | |
| `description` | one line, `<skill> only - <what it does>` | every agent description sits in every session's context (Claude Code warns above 15,000 tokens of them); the prefix keeps the main model from using it for other work |
| `model` | `haiku` or `sonnet` by the routing below (or `opus`, `fable`, a full model id) | unset, it may run on the main, most expensive model |
| `effort` | `low` for mechanical work, `medium` for judgement | thinking tokens |
| `tools` | only the ones it needs | omitted, it inherits every tool: more schemas in its context, and room to do what it should not |
| `maxTurns` | 25-40 | bounds a lost subagent; at the limit its output is marked partial |
| `omitClaudeMd` | `true` | skips the user's and the project's CLAUDE.md, rarely relevant to a scoped task (Claude Code 2.1.271 or later) |
| `skills` | leave out | preloads each skill's full content into every run |

Plugin agents ignore `hooks`, `mcpServers` and `permissionMode`.

## Instructions (the agent's body)

In this order: what it does and what the prompt gives it (inputs, the `ENV` line, a scratchpad folder); the steps; what not to repeat (what the scripts already check); when it is done, as a command whose output proves it; the answer; the status. Template: `assets/templates/agent.md`.

The answer contract:
- A first-line status: `DONE`, `DONE_WITH_CONCERNS` (followed by the doubts), `BLOCKED` (what stopped it) or `NEEDS_CONTEXT` (what is missing).
- At most N lines (10 to 25), findings as `file:line: problem`, each with its concrete case.
- Long output to a file in the scratchpad folder, returning its path.
- `Do not start subagents.`

## Routing and thresholds

| Work | Who |
|---|---|
| decides the quality: writing, design, naming, diagnosis, reviewing what subagents changed, the final read-through and report | the main model, not delegated |
| judgement that a script, a build or a cited source then checks: drafting test data, fact-checking against official pages, comparing docs with code | `sonnet`, effort `medium` or `low` |
| mechanical work a script verifies: translating text that a lint then checks, executing given steps exactly | `haiku`, effort `low` |
| deterministic work | a script, never a subagent |

A subagent's start-up and hand-off cost tens of thousands of (mostly cached) tokens, so below a handful of files or steps the main model does the work itself. Put each threshold in the start script, which prints the delegation only above it (tech-tutorial: translator above 5 files, in groups of about 8; inventory above 15 source files; executor above 2 scenarios). The other reason to delegate is the main context: work that would fill it with output the main model never needs again belongs in a subagent even near the threshold.

Independent groups go in one message with several Agent calls; work that shares a resource (ports, a database, one file) goes to a single subagent.

## Calling

The prompt carries the inputs, the `ENV` line and the scratchpad folder, nothing the agent file already says:

```
subagent_type: "<skill>:<agent>"
prompt: "Repository: C:/work/repo. Files: src/a/, src/b/ (8 files). ENV: java 25 (C:/jdk-25) mvn 3.9.11. Scratchpad: C:/tmp/scratch/translator-1"
```

## After the answer

- Rerun the deterministic check (lint, build, scenarios) before acting on or reporting a result: a cheaper model's mistakes sound as sure as its findings.
- `BLOCKED` or `NEEDS_CONTEXT`: add the missing context, split the task, move it one model up (`model` in the call overrides the agent's), or do it yourself; never resend it unchanged.
- After an agent that edits: `git status --short`, to check it touched only its files.
- Open its scratchpad file only when the answer is not enough.
