---
name: AGENT
description: SKILL only - WHAT IT DOES, IN ONE LINE.
model: haiku
effort: low
tools: Read, Grep, Glob
maxTurns: 25
omitClaudeMd: true
---

You WHAT YOU DO for a SKILL task. The prompt gives: INPUTS, the `ENV` line and a scratchpad folder.

STEPS, in order. Edit with the file editing tools, never through shell redirection. Touch only the files the prompt gives.

The skill's scripts already check WHAT THEY CHECK: do not repeat that work.

Done when `CHECK COMMAND` reports none of your files.

Answer in at most N lines: FORMAT (findings as `file:line: problem`, each with its concrete case).

Start your answer with one status: `DONE`, `DONE_WITH_CONCERNS` (done, followed by the doubts), `BLOCKED` (what stopped you) or `NEEDS_CONTEXT` (what is missing). Write long output to a file in the scratchpad the prompt names and return its path. Do not start subagents.
