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

(alongside Mapping: any DetectedUnit for an ecosystem ts-scan can't scan yet flows into
ecosystem_proposals.py, producing an EcosystemProposal per ecosystem - drafted locally always;
filed on GitHub only via the separate, explicit --file-issues review-and-confirm flow.)
```

## Components

- **`inventory.py`** — deterministic repo walker. Reuses `ts_scan.pm.*Scanner.accepts()` for
  ecosystem detection instead of re-implementing manifest parsing; adds its own detection for
  Dockerfiles, CI config files and monorepo markers (`pnpm-workspace.yaml`, `lerna.json`, an
  npm `workspaces` field, etc). Produces `DetectedUnit` objects. Never touches an LLM. Honors
  the repo's root `.gitignore` (via `pathspec`) - ignored directories are never descended into
  and ignored files never become `DetectedUnit`s, so vendored/generated/ignored content can't
  produce a false Module or a false "unsupported ecosystem" proposal. Scope is deliberately
  limited - see Known Limitations below.
- **`mapping.py`** — rule engine turning `DetectedUnit`s into `Candidate`s. A detected
  ecosystem at the repo root, or nested under a monorepo marker, is a high-confidence Module.
  A nested ecosystem manifest with no monorepo marker is ambiguous (own module, or just a
  vendored subfolder?). A Node package inside a monorepo that declares its own version and
  isn't `private` is a Linked Module candidate. A Dockerfile is classified Module vs.
  Infrastructure Module via an `LLMClient` call when one is configured, defaulting to
  Infrastructure Module (per TrustSource's own container-scanning guidance) with an open
  question when it isn't. Every candidate name is also checked against `_naming_warnings()`
  for version-like patterns (`api-1.4.2`, `node:22-alpine`, `api-v2`) and gets a non-blocking
  `Candidate.warnings` entry if it matches - a module name that changes with every release
  creates a brand-new TrustSource module per release, silently losing everything attached to
  the old one (whitelist decisions, muted vulnerabilities, approval history). This only catches
  names *we* generate; `render.py` also prints a fixed reminder up front, since neither
  `ts-scan scan` nor `upload` has a flag to set the module name at all — TrustSource
  auto-derives it from the scanned artifact (see ADR-007 below), so the actual risk is
  whatever ts-scan itself infers, most commonly a container image tag on a Syft-based scan.
- **`ts_scan_reference.py`** — introspects the real `ts-scan` Click command tree (never
  hand-transcribed) as ground truth for every `ts_scan_command` string this project generates
  or shows an LLM; see ADR-007.
- **`interview.py`** — walks the `Candidate`s with an unresolved `open_question` and asks a
  fixed CLI question per item.
- **`render.py`** — turns the finished `ScanConcept` (plus the raw `DetectedUnit` list, for the
  CI/monorepo-marker sections) into the Markdown report.
- **`llm/`** — the `LLMClient` abstraction plus concrete backends (`ollama.py` default,
  `anthropic.py` optional extra).
- **`model.py`** — the shared data types (`DetectedUnit`, `Candidate`, `ScanConcept`) that
  every stage above passes to the next. Internal only in v1 (not exposed as a file format yet).
- **`ecosystem_proposals.py`** — for `DetectedUnit`s of kind `unsupported_ecosystem` (a manifest
  format from a small known list — `UNSUPPORTED_ECOSYSTEM_MARKERS`/`_EXTENSIONS` in
  `inventory.py` — that no `ts_scan.pm.*Scanner` accepted for that directory), drafts an
  `EcosystemProposal`: a static fact baseline (registry/manifest/lockfile, always present) plus
  optional `LLMClient`-drafted enrichment (suggested approach, closest existing scanner).
- **`github_issues.py`** — thin `gh` CLI wrapper: read-only duplicate search
  (`find_similar_issues`) and issue filing (`file_issue`), used only by the CLI's
  `--file-issues` flow, never automatically.

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

### ADR-006 — Ecosystem-support proposals: draft always, file only on explicit opt-in

**Date:** 2026-08-22

**Context:** When Inventory finds a build system `ts-scan` has no scanner for, the agent can
draft a GitHub issue proposing support for it on `trustsource/ts-scan` — turning a real gap a
customer hit into an actionable upstream request. But this tool runs against arbitrary,
potentially many customers' repos; it must never post to a third-party-maintained public repo
on someone's behalf without them actively choosing to. User also required (2026-08-22) that the
customer be able to review and edit the concept before it's sent, not just accept/reject a
fixed text — drafting alone isn't enough, the flow has to make editing natural.

Also explicitly considered and deferred here: generating the actual scanner *implementation*
(not just the concept) and opening it as a PR the customer could use pre-merge. Rejected for
now — needs a much larger coding-tier model and an iterative test-driven loop that the current
single-shot `LLMClient.judge()` isn't built for, needs matching server-side work (component
data for the new ecosystem), and raises real legal/compliance-accuracy questions around
unreviewed generated code feeding SBOM data. Revisit as its own, later feature.

**Decision:** `ecosystem_proposals.py` always drafts a proposal per unsupported ecosystem found
(local text generation only, cheap) — this ships in the Markdown report by default
(`--propose-issues`, on by default) with the exact `gh issue create` command to run by hand.
Actually filing requires `--file-issues` *and*, per proposal: a best-effort duplicate check
(`github_issues.find_similar_issues`, skipped with a warning if a match is found), the drafted
text opened in the user's `$EDITOR` for review/editing (`click.edit`), and an explicit
`click.confirm` on the (possibly edited) result. `--file-issues` is a no-op (warns, doesn't
silently degrade to non-interactive-confirm-skipped) under `--non-interactive` — this
confirmation step cannot be bypassed by combining flags.

**Consequences:** Filing is meaningfully more friction than a single flag, by design. Dedup
relies on the `gh` CLI being installed/authenticated for the best safety net, but degrades to
"draft only, no dedup check" rather than blocking drafting when it isn't — consistent with
ADR-001/ADR-002's "always at least a usable local baseline" posture.

### ADR-007 — `ts_scan_command` text must come from introspected ground truth, never invented

**Date:** 2026-08-22

**Context:** This tool's entire value proposition is telling customers which command to run.
A wrong command is worse than no command — it burns trust immediately ("sonst kriegen die
Kunden die Krise", per the user). This was not a hypothetical risk: while implementing this
ADR, introspecting the real `ts-scan` Click command tree (`ts_scan_reference.py`) revealed that
the command templates shipped up to this point were themselves wrong — `ts-scan upload` has no
`--module` flag (module name is auto-derived, see the Known Limitations entry above),
`--project` should have been `--project-name`, and `ts-scan docker` doesn't exist as a
subcommand at all (it's `ts-scan scan --use-syft docker:<image>`). These had been hand-typed
from a mix of memory and a ts-docs recipe page, neither of which is authoritative for the
actual installed CLI.

**Decision:** `ts_scan_reference.py` introspects the real Click command tree from the installed
`ts-scan` package (`cli.commands`, each command's `.params`) as the only source of truth for
flags/arguments. `mapping.py`'s `_scan_command()`/`_docker_scan_command()` are the *only* two
places that build `ts_scan_command` strings, and both are plain deterministic string templates
— no LLM is ever in this path (consistent with ADR-001: LLMClient is only consulted for
Module-vs-Infrastructure-Module *classification*, never for command text). `tests/
test_ts_scan_reference.py` extracts every flag token from both templates' output
(`extract_flags()`) and asserts each one is a real flag on the real command, sourced from the
same introspection — so a future `ts-scan` release that renames/removes a flag fails this
project's test suite immediately instead of silently shipping a wrong command to customers.

**Consequences:** Command text is exactly as current as the pinned `ts-scan` dependency version
— bump `ts-scan` in `pyproject.toml` and the reference (and the validation test) automatically
reflect the new CLI surface; a flag removed upstream breaks the test loudly rather than shipping
stale advice. `ecosystem_proposals.py`'s LLM-drafted "suggested approach" text is prose about a
*hypothetical future* scanner for an ecosystem ts-scan doesn't support yet — it never claims to
give a runnable command for an existing one, so it's out of scope for this guarantee, but stays
worth re-checking if that changes.

---

## Known limitations & pending upstream work

- **Module name pinning (blocked on upstream tickets, not yet shipped as of 2026-08-22):** the
  naming-tip/`Candidate.warnings` mechanism (v0.3.0) is a stopgap. Verified against the real CLI
  (introspected via `ts_scan_reference.py`, ADR-007): **neither `ts-scan scan` nor `upload` has
  a `--module` flag at all** — TrustSource auto-derives the module name entirely from the
  scanned artifact (package name, or the image reference incl. tag for a Syft/container scan).
  `ts-scan import` is the one exception - it already takes a pinned, decoupled identifier
  (`--module` *and* `--module-id`, both required). The user has filed tickets to bring
  equivalent pinning to `scan`/`upload` — the commands this tool actually recommends.
  **Once that ships:** update `_scan_command()`/`_docker_scan_command()` in `mapping.py`
  to emit a pinned `--module-id` alongside `--module`, and adjust the naming-tip text in
  `render.py` to recommend pinning as the actual fix rather than just "pick a stable name."

- **`.gitignore` support is intentionally narrow (v0.4.0):** only the **root** `.gitignore` is
  read — nested per-directory `.gitignore` files are not merged in, and ecosystem-/VCS-equivalent
  ignore mechanisms (`.dockerignore`, `.npmignore`, SVN's `svn:ignore` property, …) aren't
  honored at all (different semantics, or - for `svn:ignore` - not even a plain file we could
  read the same way). It also only gates *our own* detection (Dockerfiles, CI configs, monorepo
  markers, unsupported-ecosystem markers) plus directory descent — it does **not** reach into
  `ts_scan.pm.*Scanner.accepts()`, so a manifest file that's individually gitignored (rare)
  inside a *non*-ignored directory can still trigger a Module candidate, since `accepts()`
  re-checks the filesystem directly rather than going through our filtered `filenames` list.
  Extend `inventory.py`'s `_load_gitignore_spec()` to a proper per-directory cascade if
  nested-gitignore repos turn out to matter in practice.

- **VCS other than Git works, but only gets the baseline treatment.** Nothing in the pipeline
  actually depends on Git — `scan_inventory()` walks whatever local directory it's given, and
  `IGNORED_DIRS` already prunes `.svn` and `.hg` (verified 2026-08-22: this correctly skips both
  modern single-root and pre-1.7 per-directory `.svn` layouts, since the prune re-applies at
  every level `os.walk` descends into). What SVN/Mercurial working copies don't get is anything
  equivalent to `.gitignore` filtering (see above) or the CI-config detection list, which is
  Git-hosting-specific (`.github/workflows`, `.gitlab-ci.yml`) - a Jenkinsfile is still caught
  either way. This tool also never clones/checks out anything itself, for any VCS - it only ever
  analyzes an already-local directory you point it at.
