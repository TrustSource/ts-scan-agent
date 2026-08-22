# ts-scan-agent

An open-source agent that looks at a repository and proposes a **TrustSource scan concept**:
which parts of the repo should become TrustSource **Modules**, **Infrastructure Modules** or
**Linked Modules**, and which `ts-scan` command to run for each — so you don't have to figure
that out by hand.

v1 produces a readable Markdown report. It does not (yet) generate runnable CI scripts — that's
a planned next step, see [ARCHITECTURE.md](ARCHITECTURE.md).

## Quickstart

```bash
pip install ts-scan-agent
ts-scan-agent analyze /path/to/your/repo
```

By default this uses a local [Ollama](https://ollama.com) server (model `qwen3:7b`, pull it
first with `ollama pull qwen3:7b`) for the handful of judgment calls that can't be made by rule
alone — nothing about your repository is sent anywhere. If Ollama isn't running, those judgment
calls are simply deferred to the interactive interview instead; nothing breaks.

```bash
# Fully offline / rule-based, no LLM at all - ambiguous items go straight to the interview
ts-scan-agent analyze . --llm none

# Use Anthropic instead (requires: pip install "ts-scan-agent[anthropic]")
ts-scan-agent analyze . --llm anthropic --anthropic-api-key sk-...

# Skip the interactive interview, write the report to a file
ts-scan-agent analyze . --non-interactive -o scan-concept.md
```

## How it works

1. **Inventory** — walks the repo (reusing [`ts-scan`](https://github.com/trustsource/ts-scan)'s
   own ecosystem detectors) to find package manifests, Dockerfiles, CI configs and monorepo
   markers. Purely deterministic, no LLM involved.
2. **Mapping** — proposes a Module / Infrastructure Module / Linked Module for each detected
   unit using rules; falls back to an LLM judgment call only for genuinely ambiguous cases.
3. **Interview** — asks you directly about anything still unresolved.
4. **Report** — renders the final concept as Markdown, including the recommended `ts-scan`
   command per unit.

See [ARCHITECTURE.md](ARCHITECTURE.md) for the full design and the reasoning behind it (ADRs).

## License

Apache-2.0, see [LICENSE](LICENSE).
