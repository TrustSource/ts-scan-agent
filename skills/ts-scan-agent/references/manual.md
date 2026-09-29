# Manual mode

Use this only when neither Python 3.8+ nor Node.js 18+ is available. You do by hand what
`scripts/scan_concept.py` does, using your own tools to list directories and read files. Stay
read-only in the repository.

Build the list of **units** (step A), turn them into **candidates** (step B), ask the open
questions (SKILL.md step 3), then write the report (step C).

## A. Walk the repository

Start at the repository root (depth 0) and visit every directory down to depth 6. Skip these
directories entirely, at any depth: `.git`, `.hg`, `.svn`, `node_modules`, `vendor`, `venv`,
`.venv`, `__pycache__`, `dist`, `build`, `target`, `bin`, `obj`, `.mypy_cache`,
`.pytest_cache`, `.ruff_cache`, `.tox`, `Pods`. Also skip anything the root `.gitignore`
ignores (only the root one, not nested ones). Visit directories in sorted order.

In each directory, record these units. Paths are relative to the root with `/`, and the root
itself is `.`.

1. **Ecosystem**: one unit per match, checked in this order, with evidence
   `<Ecosystem> manifest found`:

   | Ecosystem | Directory contains |
   | --- | --- |
   | `PyPI` | `setup.py` or `pyproject.toml` |
   | `Maven` | `pom.xml` |
   | `Gradle` | `build.gradle` or `build.gradle.kts` |
   | `Node` | `package.json` |
   | `NuGet` | `*.nuspec`, `*.*proj`, `packages.config` or `*.sln` |
   | `Cargo` | `Cargo.toml` |
   | `Golang` | `go.mod` |
   | `Dart` | `pubspec.yaml` |

2. **Unsupported ecosystem**, only if step 1 found nothing in this directory: `composer.json`
   (PHP (Composer)), `Gemfile` (Ruby (Bundler)), `Package.swift` (Swift (Swift Package
   Manager)), `Podfile` (iOS (CocoaPods)), `mix.exs` (Elixir (Hex)), `stack.yaml` (Haskell
   (Stack)), `cpanfile` (Perl (CPAN)), `build.zig` (Zig), `elm.json` (Elm), any `*.cabal`
   (Haskell (Cabal)).
3. **Dockerfile**: a file named `Dockerfile` or starting with `Dockerfile.`. Its unit path is
   the file path, e.g. `services/api/Dockerfile`.
4. **Monorepo root**: `pnpm-workspace.yaml`, `lerna.json`, `nx.json`, `rush.json`,
   `melos.yaml`, or a `package.json` with a non-empty `workspaces` field.
5. **CI config**: `.gitlab-ci.yml`, `Jenkinsfile`, `azure-pipelines.yml`, and every `*.yml` /
   `*.yaml` file in `.github/workflows/`.

## B. Classify

`PROJECT` is the TrustSource project name: what the user named, else the repository
directory's name. A unit's `NAME` is the last segment of its path, or `PROJECT` for `.`.

For each **ecosystem** unit at path `P`:

| Situation | Type | Confidence | Open question |
| --- | --- | --- | --- |
| `P` is `.` | Module | 95% | none |
| Inside a monorepo root (the root is `.`, equal to `P`, or a parent of `P`), Node, and its `package.json` has a `version` and is not `"private": true` | Linked Module | 75% | Does "P" get published/released on its own (npm registry, internal registry, separate versioning)? If yes, set it up as its own TrustSource project and link its release here instead of scanning it as a plain Module. |
| Inside a monorepo root, otherwise | Module | 90% | none |
| Anything else (nested, no monorepo marker) | Module | 50% | Is "P" released/deployed separately from the rest of the repo? If yes, it should be its own Module; if no, fold it into the parent module's scan instead. |

Its command, with `TARGET` = `P` (`.` for the root):

```
ts-scan scan TARGET -o NAME.json && ts-scan upload --project-name "PROJECT" --api-key "$TS_API_KEY" NAME.json
```

For each **Dockerfile** unit at path `F` in directory `D`: an Infrastructure Module, 40%
confidence, named `<name of D>-container` (`PROJECT-container` when `D` is the root), with the
open question: Is the image built from "F" your own deployable service, or runtime
infrastructure (base image, sidecar, etc.)? This changes whether it should be a Module or an
Infrastructure Module. Its command:

```
ts-scan scan --use-syft docker:<image> -o NAME.json && ts-scan upload --project-name "PROJECT" --api-key "$TS_API_KEY" NAME.json
```

Fill in only `TARGET`, `NAME` and `PROJECT`. Leave `docker:<image>` and `"$TS_API_KEY"`
exactly as written; the user fills them in. Do not add, drop or reorder any other part.

**Naming warning:** if a candidate's name contains a version or image tag (`api-1.4.2`,
`node:22-alpine`, `api-v2`), warn that TrustSource keys a module by name, so a name that
changes per release creates a new module each time and loses its history.

Answers from SKILL.md step 3 resolve the open questions, and each answered item's reason
becomes what the user confirmed (not the original doubt):

- Dockerfile answered `module`: a Module. Answered `infrastructure_module`: stays an
  Infrastructure Module.
- Linked Module answered `yes`: stays a Linked Module (its own TrustSource project, release
  linked here). Answered `no`: a plain Module of this project.
- Nested Module answered `yes`: stays its own Module. Answered `no`: it belongs to its parent,
  so **remove it and its command** and list it under "Folded into parent modules" instead.

Answered items no longer count as open.

## C. Write the report

Tell the user this was produced in manual mode, then give:

1. One TrustSource project, `PROJECT`, and the reminder that `ts-scan` has no flag to set the
   module name: TrustSource derives it from what it scans (for containers, the image reference
   including its tag), so check the name after the first scan and keep it stable.
2. Sections **Modules**, **Infrastructure Modules**, **Linked Module candidates** (skip empty
   ones), each item sorted by path: path, name, ecosystem, confidence, a one-line reason, and
   its command in a `bash` block.
3. **Folded into parent modules**, if any: each folded path, name and ecosystem, with no command.
4. **Still open**: each unanswered question with its path.
5. **Detected CI/CD configuration**: the CI files, with a note to wire the commands into them.
6. **Monorepo markers detected**, if any: scan each workspace package on its own, never the
   monorepo root.
7. **Unsupported ecosystems detected**, if any: for each, the paths, and a draft issue titled
   `Add ts-scan support for <ecosystem>` for `trustsource/ts-scan`, filed only as described in
   SKILL.md step 5.

For a first-time TrustSource user, add these steps: create a TrustSource account and project,
create an API key under Administration > Scanners & API Keys and `export TS_API_KEY=...`,
`pip install ts-scan`, run the commands, then review the module in the app, get an approval
and create a release.
