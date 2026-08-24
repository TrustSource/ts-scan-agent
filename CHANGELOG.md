# ts-scan-agent Changelog
All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/) and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
