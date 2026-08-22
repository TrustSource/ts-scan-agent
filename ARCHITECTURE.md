# Architecture

## System overview

`ts-scan-agent` is a CLI tool that looks at an arbitrary repository and proposes a TrustSource
scan concept: a set of candidate **Modules**, **Infrastructure Modules** and **Linked Modules**
(TrustSource's own data model — see the online help under `03-internal/02-modules/`), each with
a recommended `ts-scan` invocation. Its purpose is to shorten the path from "I have a repo" to
"I know how to configure TrustSource scanning for it," including for repos with unfamiliar or
mixed build chains.

It is distributed as open source so any TrustSource customer can run it against their own code
without sending that code anywhere they haven't explicitly opted into.

## Pipeline

```
repo path
   │
   ▼
┌─────────────┐   deterministic, no LLM
│  Inventory  │   walks the tree; detects ecosystems (via ts-scan's own pm/ detectors),
└─────┬───────┘   Dockerfiles, CI configs, monorepo markers
      │ DetectedUnit[]
      ▼
┌─────────────┐   rule-based; LLMClient only for genuinely ambiguous cases
│   Mapping   │   (e.g. classifying a Dockerfile as Module vs. Infrastructure Module)
└─────┬───────┘
      │ Candidate[] (module | infrastructure_module | linked_module), each with
      │ confidence + rationale, and an open_question if unresolved
      ▼
┌─────────────┐   CLI prompts over just the low-confidence candidates
│  Interview  │
└─────┬───────┘
      │ ScanConcept (resolved)
      ▼
┌─────────────┐
│   Render    │   → Markdown report
└─────────────┘
```

## Components

- **`inventory.py`** — deterministic repo walker. Reuses `ts_scan.pm.*Scanner.accepts()` for
  ecosystem detection instead of re-implementing manifest parsing; adds its own detection for
  Dockerfiles, CI config files and monorepo markers (`pnpm-workspace.yaml`, `lerna.json`, an
  npm `workspaces` field, etc). Produces `DetectedUnit` objects. Never touches an LLM.
- **`mapping.py`** — rule engine turning `DetectedUnit`s into `Candidate`s. A detected
  ecosystem at the repo root, or nested under a monorepo marker, is a high-confidence Module.
  A nested ecosystem manifest with no monorepo marker is ambiguous (own module, or just a
  vendored subfolder?). A Node package inside a monorepo that declares its own version and
  isn't `private` is a Linked Module candidate. A Dockerfile is classified Module vs.
  Infrastructure Module via an `LLMClient` call when one is configured, defaulting to
  Infrastructure Module (per TrustSource's own container-scanning guidance) with an open
  question when it isn't.
- **`interview.py`** — walks the `Candidate`s with an unresolved `open_question` and asks a
  fixed CLI question per item.
- **`render.py`** — turns the finished `ScanConcept` (plus the raw `DetectedUnit` list, for the
  CI/monorepo-marker sections) into the Markdown report.
- **`llm/`** — the `LLMClient` abstraction plus concrete backends (`ollama.py` default,
  `anthropic.py` optional extra).
- **`model.py`** — the shared data types (`DetectedUnit`, `Candidate`, `ScanConcept`) that
  every stage above passes to the next. Internal only in v1 (not exposed as a file format yet).

## Data flow

A `Candidate`'s `confidence` and `open_question` fields are the contract between Mapping,
Interview and Render: Mapping is the only stage that *creates* uncertainty (it never guesses
silently), Interview is the only stage that *resolves* it, and Render is the only stage that
*reports* whatever is still unresolved (the "Still open" section) rather than hiding it.

## Infrastructure & deployment

Pure Python CLI (`pip install ts-scan-agent`), no server component. The only outbound network
call is the optional LLM judgment call (to a local Ollama instance by default, or to the
Anthropic API if explicitly configured) — Inventory, Mapping's rule path, Interview and Render
never make any network call.

---

## Architecture Decision Records

### ADR-001 — Deterministic core, LLM only at the ambiguous edges

**Date:** 2026-08-22

**Context:** The tool inspects potentially proprietary customer repositories. Enterprise
TrustSource customers need this to be auditable and cannot send arbitrary source code to a
third-party API by default.

**Decision:** Inventory and the confident branches of Mapping are pure, deterministic code —
no LLM call, ever. An `LLMClient` is only invoked for the specific cases the rule engine
already knows it's unsure about (Dockerfile Module vs. Infrastructure Module classification;
in future, other ambiguous mapping judgments). Without any LLM configured (`--llm none`), the
tool still produces a complete concept — unresolved items just go to the Interview step
instead.

**Consequences:** Slightly more mapping code (explicit confidence + rationale on every
candidate) than a "throw the repo at an LLM" design would need, but the tool is fully usable,
auditable and zero-cost with no API key, and every automated judgment is explainable.

### ADR-002 — Provider-agnostic `LLMClient`, local Ollama/Qwen3 default

**Date:** 2026-08-22

**Context:** TrustSource customers have varied constraints on which LLM providers they're
allowed to use (some enterprise customers are restricted to specific vendors or on-prem/local
inference only), and an open-source tool shouldn't hard-code a single paid vendor.

**Decision:** All LLM access goes through the `LLMClient` interface (`llm/__init__.py`) with a
single `judge(prompt, schema) -> dict` method. The default backend is a local Ollama server
(`llm/ollama.py`), recommended model `qwen3:7b` — chosen for reliable structured JSON /
tool-calling output at a size that runs on modest hardware (confirmed via web research,
2026-08-22; re-verify periodically as the local-model landscape moves quickly). An Anthropic
backend (`llm/anthropic.py`) is available as the `[anthropic]` extra, never a required
dependency. `OllamaLLMClient.judge()` degrades to "unresolved" (rather than raising) if the
local server or model isn't available, since it's the zero-setup default and a missing local
model must never crash an `analyze` run.

**Consequences:** Adding another backend (OpenAI, Azure OpenAI, Bedrock) is a new file behind
the same interface — no changes needed in `mapping.py` or `cli.py`. Verify Qwen3's exact
license terms for the size in use before treating it as a permanent default (noted as an
open item as of this ADR).

### ADR-003 — Reuse `ts-scan`'s ecosystem detectors instead of re-implementing them

**Date:** 2026-08-22

**Context:** `ts-scan` already ships reliable, filesystem-only ecosystem detection
(`Scanner.accepts(path) -> bool`) for PyPI, Maven, Gradle, Node, NuGet, Cargo, Go and Dart.

**Decision:** `inventory.py` depends on `ts-scan>=1.8.0` and imports the individual
`*Scanner` classes directly from `ts_scan.pm.*` rather than duplicating manifest-detection
logic. `GradleScanner` needs a `configuration` constructor arg used only by its (unused, here)
`scan()` method — instantiated with `configuration=None` since only `accepts()` is called.

**Consequences:** Ecosystem coverage tracks `ts-scan` automatically as it adds ecosystems
(e.g. C/C++ via DeepScan integration is out of scope for this reuse path today since DeepScan
isn't a `pm.Scanner`-style per-ecosystem detector — revisit if/when that changes). Couples this
project's inventory accuracy to `ts-scan`'s internal `pm` module, which is not a documented
public API — acceptable for now, but worth watching across `ts-scan` version bumps.

### ADR-004 — Markdown-only output in v1

**Date:** 2026-08-22

**Context:** The near-term goal is a readable concept document a human reviews; a structured
data contract (JSON/YAML) for downstream script generation is an explicitly later milestone,
not needed yet.

**Decision:** `render.py` renders directly to Markdown text. The pipeline still passes a typed
`ScanConcept` (pydantic) internally, so exposing that as a JSON/YAML export later is an
additive change, not a rewrite.

**Consequences:** No breaking change expected when script generation is added later; until
then, nothing external depends on the internal `ScanConcept` shape.

### ADR-005 — Interview ships as a fixed CLI prompt, not a freeform LLM dialogue (v1 scope cut)

**Date:** 2026-08-22

**Context:** A freeform conversational interview is the eventual goal, but it adds real scope
(dialogue state, LLM-formulated questions, handling off-topic answers) beyond what's needed to
prove the pipeline end-to-end.

**Decision:** v1's `interview.py` walks exactly the candidates Mapping already flagged with an
`open_question` and asks that literal question via `click.prompt`/`click.confirm`. No LLM
involvement in this step yet.

**Consequences:** Interview only ever asks about things Mapping already anticipated; it can't
yet ask a clarifying follow-up or handle a case Mapping didn't foresee. Upgrading to an
LLM-driven dialogue later replaces this module without touching Mapping or Render.
