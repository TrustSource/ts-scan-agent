![License](https://img.shields.io/badge/License-Apache--2.0-green) ![Python](https://img.shields.io/badge/Python-%203.10,%203.11,%203.12-blue)

# ts-scan-agent

An open-source agent that looks at a repository and proposes a **TrustSource scan concept**:
which parts of the repo should become TrustSource **Modules**, **Infrastructure Modules** or
**Linked Modules**, and which [`ts-scan`](https://github.com/trustsource/ts-scan) command to
run for each — so you don't have to work that out by hand, and don't have to trust an LLM to
get the actual commands right (see [How it works](#how-it-works)).

v1 produces a readable Markdown report you review yourself. It does not (yet) generate runnable
CI scripts, and it does not touch your TrustSource account — see
[ARCHITECTURE.md](ARCHITECTURE.md) for the full design and the reasoning behind it (including
what's deliberately out of scope for now).

## What actually happens when you run it

Four steps, in order — only the second one ever calls an LLM, and only for the specific cases
it already knows it's unsure about:

1. **Inventory** (deterministic, no LLM) — walks your repo, reusing `ts-scan`'s own ecosystem
   detectors (PyPI, Maven, Gradle, npm, NuGet, Cargo, Go, Dart) so ecosystem detection can never
   drift from what `ts-scan` itself would actually scan. Also finds Dockerfiles, CI config
   files, and monorepo markers (`pnpm-workspace.yaml`, an npm `workspaces` field, etc). Honors
   your repo's root `.gitignore`, so vendored/generated/ignored content is never mistaken for
   real source.
2. **Mapping** (rule-based; LLM only for genuinely ambiguous cases) — proposes a Module,
   Infrastructure Module, or Linked Module for each thing Inventory found. A package at the
   repo root, or inside a detected monorepo workspace, is a confident Module. A Dockerfile is
   classified Module vs. Infrastructure Module by an LLM call *if one is configured* — with a
   default guess and an explicit open question if not. **The recommended `ts-scan` command
   itself is never LLM-generated** — it's built from a small set of fixed templates that are
   automatically checked against the real, installed `ts-scan` CLI's actual flags in this
   project's own test suite, so a wrong or hallucinated command can't ship silently (see
   ARCHITECTURE.md → ADR-007).
3. **Interview** — a short, fixed sequence of yes/no or multiple-choice questions for whatever
   Mapping was genuinely unsure about. Skippable with `--non-interactive` (unresolved items are
   then just listed in the report instead).
4. **Report** — renders everything as Markdown: the proposed Module/Infrastructure
   Module/Linked Module tree with recommended commands, a naming-pitfall warning (TrustSource
   keys a module by name — a name that changes every release, like one derived from a Docker
   image tag, silently orphans the old module's whitelist decisions, muted vulnerabilities and
   approval history), any detected CI configs, and — if your repo uses a build system `ts-scan`
   can't scan yet (PHP/Composer, Ruby, Swift, Elixir, Haskell, Perl, Zig, Elm today) — a drafted
   GitHub issue proposing support for it, which is *never* filed without you explicitly
   reviewing and confirming it (see [Unsupported ecosystems](#unsupported-ecosystems) below).

## Which LLMs you can use

Nothing about the tool requires an LLM at all — `--llm none` runs it fully offline/rule-based,
with every ambiguous case simply deferred to the interactive interview. When an LLM *is*
configured, it's only ever asked narrow, structured judgment questions (e.g. "is this Dockerfile
a Module or an Infrastructure Module, and why?") — never anything as consequential as "what
command should I run," and never your repository's actual source code beyond short factual
excerpts embedded in the prompt.

| `--llm` value | Backend | Default model | Setup | Notes |
|---|---|---|---|---|
| `ollama` (default) | Local [Ollama](https://ollama.com) server | `qwen3:7b` | `ollama pull qwen3:7b`, have Ollama running | Nothing about your repo ever leaves the machine. If Ollama isn't reachable, judgment calls just fall back to the interview — the run doesn't fail. |
| `anthropic` | [Anthropic API](https://www.anthropic.com) | `claude-opus-5` | `pip install "ts-scan-agent[anthropic]"`, pass `--anthropic-api-key` or set `ANTHROPIC_API_KEY` | Optional cloud extra, never a required dependency. |
| `none` | — | — | none | Fully offline/rule-based; everything ambiguous goes to the interview. |

Override the model for either backend with `--llm-model` (e.g. `--llm-model qwen3:32b` for
harder cases if you have the hardware, or `--llm-model claude-opus-4-8`), and the Ollama server
address with `--ollama-url` if it's not on `localhost:11434`.

Adding another backend (OpenAI, Azure OpenAI, Bedrock, …) is a small, self-contained addition —
every backend just implements the single-method `LLMClient` interface in `src/ts_scan_agent/llm/`
(see `ollama.py` for the shortest example). Contributions welcome.

## Installation

**Not yet published to PyPI** — `pip install ts-scan-agent` will not work today. Until it is,
install directly from GitHub:

```bash
pip install git+https://github.com/TrustSource/ts-scan-agent.git

# with the optional Anthropic backend
pip install "ts-scan-agent[anthropic] @ git+https://github.com/TrustSource/ts-scan-agent.git"
```

Or from a local clone (useful if you want to read/modify the source):

```bash
git clone https://github.com/TrustSource/ts-scan-agent.git
cd ts-scan-agent
pip install -e .          # add ".[anthropic]" for the optional Anthropic backend
```

Requires Python ≥ 3.10. `ts-scan` itself comes along as a dependency automatically.

## Quickstart

```bash
# Default: local Ollama, interactive interview, prints the report
ts-scan-agent analyze /path/to/your/repo

# Fully offline, no LLM at all, write straight to a file
ts-scan-agent analyze . --llm none --non-interactive -o scan-concept.md

# Use Anthropic instead of the local default
ts-scan-agent analyze . --llm anthropic --anthropic-api-key sk-...

# Give the TrustSource project a specific name (defaults to the directory name)
ts-scan-agent analyze . --project my-product
```

## Unsupported ecosystems

If your repo uses a build system `ts-scan` can't scan yet, the report includes a drafted GitHub
issue proposing support for it on [`trustsource/ts-scan`](https://github.com/trustsource/ts-scan)
— drafting is local/free and on by default (`--propose-issues`, use `--no-propose-issues` to
turn it off). **Nothing is ever filed automatically.** To actually file one:

```bash
ts-scan-agent analyze . --file-issues
```

This checks for a likely-duplicate existing issue first (best-effort, via the `gh` CLI — install
and `gh auth login` if you don't have it), opens the draft in your `$EDITOR` so you can review
and change it, and asks for explicit confirmation before doing anything on GitHub. Use
`--issue-repo` to target a different repository (default `trustsource/ts-scan`). This step is
skipped (with a warning, not silently) under `--non-interactive` — filing always requires a
human in the loop.

## Full CLI reference

```
ts-scan-agent analyze PATH [OPTIONS]
```

| Option | Default | Description |
|---|---|---|
| `PATH` | — | Repository to analyze (required) |
| `--project TEXT` | directory name | TrustSource project name to propose |
| `--llm [none\|ollama\|anthropic]` | `ollama` | LLM backend for ambiguous judgment calls |
| `--llm-model TEXT` | backend-specific | Override the default model |
| `--ollama-url TEXT` | `http://localhost:11434` | Base URL of the local Ollama server |
| `--anthropic-api-key TEXT` | `$ANTHROPIC_API_KEY` | Anthropic API key |
| `--non-interactive` | off | Skip the interview; unresolved items are listed under "Still open" |
| `--propose-issues / --no-propose-issues` | on | Draft a GitHub issue proposal per unsupported ecosystem found |
| `--issue-repo TEXT` | `trustsource/ts-scan` | Repository ecosystem-support proposals target |
| `--file-issues` | off | Review/edit/confirm each drafted proposal, then file it on GitHub |
| `-o, --output PATH` | stdout | Write the Markdown report here instead of printing it |

`ts-scan-agent --version` prints the installed version.

## How it works (architecture)

See [ARCHITECTURE.md](ARCHITECTURE.md) for the full pipeline design, component responsibilities,
and the Architecture Decision Records explaining *why* it's built this way — including why
commands are never LLM-generated (ADR-007), why the LLM is only ever consulted at narrow,
well-defined edges (ADR-001), and what's explicitly out of scope for now.

## License

Apache-2.0, see [LICENSE](LICENSE).
