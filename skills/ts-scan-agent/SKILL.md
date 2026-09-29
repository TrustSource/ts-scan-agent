---
name: ts-scan-agent
description: Sets up TrustSource scanning for a repository. Proposes which parts become TrustSource Modules, Infrastructure Modules or Linked Modules and which ts-scan command to run for each, asks the user the open questions in chat, and hands over the final scan concept. Needs nothing installed. Use when the user wants to onboard a repo to TrustSource, asks which ts-scan commands to run, or wants to split a repo into Modules / Infrastructure Modules / Linked Modules.
license: Apache-2.0
compatibility: Self-contained. Runs a bundled dependency-free script with Python 3.8+ or Node.js 18+ if either is present; otherwise the agent follows references/manual.md with its own file tools. No network access or package installs.
metadata:
  version: "0.7.0"
  homepage: https://github.com/TrustSource/ts-scan-agent
allowed-tools: Bash(python3 ${CLAUDE_SKILL_DIR}/scripts/scan_concept.py analyze *) Bash(python ${CLAUDE_SKILL_DIR}/scripts/scan_concept.py analyze *) Bash(node ${CLAUDE_SKILL_DIR}/scripts/scan_concept.mjs analyze *)
---

# TrustSource scan concept

Work out a TrustSource scan concept for the user's repository: one TrustSource project, split
into Modules, Infrastructure Modules and Linked Modules, each with the `ts-scan` command to run.
Collect the answers only the user can give, then show the final report.

This skill is self-contained. Do not install anything (no pip, npm, uv or ts-scan-agent) to
run it.

## Rules

- **Copy every `ts-scan` command verbatim** from the script's output (or, in manual mode, from
  the templates in `references/manual.md`). Never write, edit, shorten, merge or "fix" a
  `ts-scan` command yourself. The templates are tested against the real `ts-scan` CLI; a
  hand-edited command is the failure this skill exists to prevent. If a command looks wrong,
  tell the user and suggest reporting it at https://github.com/TrustSource/ts-scan-agent/issues.
- Ask the user the open questions. Do not answer them yourself from guesses about the repo.
- Never file a GitHub issue and never run `ts-scan upload` without the user's explicit
  confirmation in this conversation. Upload sends scan data to TrustSource.
- Work read-only in the user's repository. Write temporary files (the answers file) outside it.

## 1. Pick how to run

The scripts live in this skill's `scripts/` folder. Below, `${CLAUDE_SKILL_DIR}` is this
skill's directory; if your agent did not replace it with a path, use the directory this
SKILL.md was loaded from.

Check, in order, and use the first that works:

1. `python3 --version` reports 3.8 or newer: run
   `python3 ${CLAUDE_SKILL_DIR}/scripts/scan_concept.py`
2. `python --version` reports 3.8 or newer (common on Windows): run
   `python ${CLAUDE_SKILL_DIR}/scripts/scan_concept.py`
3. `node --version` reports 18 or newer: run
   `node ${CLAUDE_SKILL_DIR}/scripts/scan_concept.mjs`
4. None of them: **manual mode**. Read `references/manual.md` and follow it with your own
   file-listing and file-reading tools, then continue at step 3 below.

Both scripts take the same arguments and print the same output. Below, `RUN` stands for the
command you picked, with the script's full path. Run it from the repository root, with `.` as
the path. The script only reads the repository and writes nothing, so if running it needs the
user's approval, ask for it. Use manual mode only when no runtime is available or the user
declines, and then say that the report was produced in manual mode.

## 2. Get the open questions

```bash
RUN analyze . --format json --no-propose-issues
```

stdout is a JSON scan concept; progress goes to stderr. Each entry in `candidates` has
`path`, `name`, `candidate_type` (`module`, `infrastructure_module` or `linked_module`),
`confidence`, `rationale`, `open_question`, `ts_scan_command` and `warnings`.

If no candidate has a non-null `open_question`, skip to step 4 without `--answers`.

## 3. Ask the user

For each candidate with an `open_question`, ask the user that question in chat. Include the
`path` and a one-line summary of the `rationale`. Put several questions in one message when
there are more than one. Map each reply to an answer:

| `candidate_type` | Allowed answers |
| --- | --- |
| `infrastructure_module` (a Dockerfile) | `module` if the image is the team's own deployable service, `infrastructure_module` if it is runtime infrastructure (base image, sidecar, database) |
| `module` (a nested package) | `yes` if it is released or deployed separately, `no` if it belongs to its parent (it is then dropped and listed under "Folded into parent modules", with no command) |
| `linked_module` | `yes` if it is published or released on its own, `no` if not |

If the user is unsure or skips one, leave it out; it stays listed under "Still open".

When the user replies, invoke this skill again before continuing if your agent supports that
(in Claude Code: the `ts-scan-agent` skill). Pre-approved commands only last for the turn
that loaded the skill.

## 4. Produce the final report

Pass the answers inline as a JSON object keyed by `path`, in single quotes. No file is needed:

```bash
RUN analyze . --answers '{"tools/helper": "no", "Dockerfile": "module"}'
```

Leave out `--answers` if there was nothing to ask. If a path contains a single quote, write the
JSON to a temp file outside the repository and pass its path to `--answers` instead. Keep `--level` at its default unless the
user asked for less explanation (`--level intermediate` or `--level expert`). Add
`--project <name>` only if the user named the TrustSource project.

Show the user the Markdown report from stdout without paraphrasing the commands in it. If the
script exits non-zero because of the answers file (unknown path or invalid value), fix the file
from the error message and run it again.

The report's wording comes from the full ts-scan-agent CLI: where it says "re-run
interactively" or "re-run with `--file-issues`", that is handled by you in this conversation
instead (step 5).

## 5. Follow-ups

- **Unsupported ecosystems.** For each proposal under "Unsupported ecosystems detected", if
  `gh` is available, check for an existing issue first with
  `gh issue list --repo trustsource/ts-scan --search "<ecosystem>" --state all`. If one looks
  related, suggest commenting there instead. Otherwise show the drafted proposal and its
  `gh issue create` command, and run that command exactly as printed only after the user
  confirms.
- **Scanning.** Offer to run the `ts-scan scan ...` part of the recommended commands. That
  needs `ts-scan` itself (`pip install ts-scan`); ask before installing it.
- **Uploading.** Run `ts-scan upload ...` only after the user confirms, and only with
  `TS_API_KEY` set by the user. Never ask the user to paste an API key into the chat.
