# ts-scan-agent Changelog
All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/) and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.6.0] - 2026-08-22

### New Features
    * Settings file support: `~/.ts-scan-agent/config.toml` (personal defaults) and `.ts-scan-agent.toml` in the current working directory (shared team/CI defaults, overrides the personal file) - keys match the `--help` option names, any `analyze` flag can be set this way, no per-option code needed (uses Click's own `default_map`, mirroring `ts-scan`'s own config pattern)
    * `--config PATH` on the top-level command to point at a different user-level settings file
    * `TS_SCAN_AGENT_<NAME>` environment variables now override settings-file values (via `auto_envvar_prefix`)

### Changed
    * **`--level` now defaults to `beginner`** (was `intermediate`) - this tool exists to help people with little TrustSource background, and that's exactly who runs it with no flags on a first try. Set `level = "expert"`/`"intermediate"` in a settings file to change your own default once instead of passing `--level` every run
    * Renamed CLI parameters to match their flag names exactly, since they're now also settings-file/env-var keys: `--llm` is `llm` (was `llm_backend`), `--project` is `project` (was `project_name`), `-o/--output` is `output` (was `output_path`)

## [0.5.0] - 2026-08-22

### New Features
    * `--level [beginner|intermediate|expert]` controls how much explanation the report includes. `beginner` prepends a step-by-step TrustSource onboarding walkthrough and a Module/Infrastructure Module/Linked Module glossary; `intermediate` (default) is today's report unchanged; `expert` strips all rationale/confidence/hint prose down to just the project tree and commands. Never affects which candidates are produced or which command is recommended - only `render.py` branches on it (see ARCHITECTURE.md ADR-008)

## [0.4.1] - 2026-08-22

### Fixed
    * README instructions said `pip install ts-scan-agent` - the package is **not yet published to PyPI**, so that command fails. Replaced with `pip install git+https://github.com/TrustSource/ts-scan-agent.git` (and the `[anthropic]`-extra equivalent), both verified against a real fresh install

### Documentation
    * Rewrote README.md: explains the four pipeline steps and what each does/doesn't call an LLM for, a table of supported LLM backends with their actual default models, the unsupported-ecosystem GitHub issue flow, and a full CLI flag reference

## [0.4.0] - 2026-08-22

### New Features
    * `ts_scan_reference.py`: introspects the real `ts-scan` Click command tree as ground truth; `tests/test_ts_scan_reference.py` validates every generated `ts_scan_command` against it, so a future `ts-scan` flag rename/removal fails the test suite instead of shipping a wrong command
    * Inventory now honors the repo's root `.gitignore` (via `pathspec`) - ignored directories are never descended into and ignored files never become detected units

### Fixes
    * **Generated `ts-scan upload` commands referenced a `--module` flag that does not exist**, and used `--project` instead of the real `--project-name` - TrustSource actually auto-derives the module name from the scanned artifact; commands and the naming-tip text corrected accordingly
    * **`ts-scan docker <image>` was not a real subcommand** - container/image scanning is `ts-scan scan --use-syft docker:<image>`; the Infrastructure Module command template was rewritten to match
    * Added the previously-missing required `--api-key` to every generated `upload` command

## [0.3.0] - 2026-08-22

### New Features
    * Always-shown naming-tip note in the report: never bake a version/image tag into a Module or Infrastructure Module name - it creates a brand-new module per release and loses whitelist decisions, muted vulnerabilities and approval history attached to the old one
    * `Candidate.warnings`: every candidate name we generate is checked against version-like patterns (`api-1.4.2`, `node:22-alpine`, `api-v2`) and flagged non-blockingly if it matches

## [0.2.1] - 2026-08-22

### Fixes
    * Anthropic backend: default model was a stale `claude-opus-4-7` - now `claude-opus-5`
    * Anthropic backend: switched from a forced-tool-call workaround to native `output_config.format` (json_schema) structured output, per the current API
    * Anthropic backend: `judge()` now degrades to `{}` on any API error (auth, rate limit, connection) instead of crashing the whole `analyze` run, matching the Ollama/Null backends' contract
    * Added `additionalProperties: false` to the judge() schemas (Dockerfile classification, ecosystem enrichment), required for strict `json_schema` structured output

## [0.2.0] - 2026-08-22

### New Features
    * Detect ecosystems ts-scan has no scanner for yet (PHP/Composer, Ruby/Bundler, Swift, Elixir, Haskell, Perl, Zig, Elm) and draft a GitHub issue proposal per ecosystem, with static facts plus optional LLM-drafted enrichment
    * `--file-issues` to review (editable in $EDITOR), confirm and file a drafted proposal on `trustsource/ts-scan`, with a best-effort duplicate check first; never fires under `--non-interactive`
    * `--propose-issues/--no-propose-issues` and `--issue-repo` options

## [0.1.0] - 2026-08-22

### New Features
    * Initial scan-concept pipeline: Inventory → Mapping → Interview → Markdown report
    * Repo inventory reusing `ts-scan`'s package-manager ecosystem detectors, plus Dockerfile, CI-config and monorepo-marker detection
    * Rule-based mapping of detected units to Module / Infrastructure-Module / Linked-Module candidates, with an `LLMClient` escape hatch for ambiguous cases
    * Provider-agnostic `LLMClient` abstraction with a local Ollama (Qwen3) backend by default and an optional Anthropic backend
    * `ts-scan-agent analyze` CLI command producing a human-readable Markdown scan concept
