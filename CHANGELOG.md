# ts-scan-agent Changelog
All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/) and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - 2026-08-22

### New Features
    * Initial scan-concept pipeline: Inventory → Mapping → Interview → Markdown report
    * Repo inventory reusing `ts-scan`'s package-manager ecosystem detectors, plus Dockerfile, CI-config and monorepo-marker detection
    * Rule-based mapping of detected units to Module / Infrastructure-Module / Linked-Module candidates, with an `LLMClient` escape hatch for ambiguous cases
    * Provider-agnostic `LLMClient` abstraction with a local Ollama (Qwen3) backend by default and an optional Anthropic backend
    * `ts-scan-agent analyze` CLI command producing a human-readable Markdown scan concept
