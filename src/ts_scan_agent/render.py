import shlex
import typing as t

from .model import ScanConcept, Candidate, DetectedUnit, EcosystemProposal

Level = t.Literal['beginner', 'intermediate', 'expert']
LEVEL_CHOICES: t.Tuple[Level, ...] = ('beginner', 'intermediate', 'expert')

_SECTION_TITLES = {
    'module': 'Modules',
    'infrastructure_module': 'Infrastructure Modules',
    'linked_module': 'Linked Module candidates',
}

_NAMING_TIP = (
    '> **Naming tip:** `ts-scan scan`/`upload` have no flag to set the module name - '
    'TrustSource auto-derives it from what ts-scan detects (the package name, or for a '
    'container scan, the image reference *including its tag*, e.g. `node:22-alpine`). '
    'Check the module name TrustSource assigns after the first scan and rename it if it '
    'looks version-y **before** the next release: TrustSource keys a module by name, so a '
    'name that changes with every release creates a brand-new module each time, silently '
    'losing everything attached to the old one - whitelist decisions, muted '
    'vulnerabilities, approval history. (A pinnable module ID for `scan`/`upload` is '
    'planned upstream - see ARCHITECTURE.md.)'
)

# Grounded in ts-docs' own onboarding recipe
# (docs/v2.16/recipes/01-first-module-to-sbom.md, "Your first module: from scan to
# signed-off SBOM in 15 minutes") - condensed to what a first-time reader of *this* report
# needs as context, not a full copy. Point to the real recipe for the complete walkthrough.
_GETTING_STARTED = """## Getting started

New to TrustSource? This report only covers *what* to scan and *which command* to run for
each piece (below). Here's the rest of the journey, in order - steps 1-3 and 5-8 happen in
the TrustSource app itself, not on the command line:

1. **Create a TrustSource account and project**, if you don't have one yet
   ([app.trustsource.io](https://app.trustsource.io)).
2. **Create an API key**: **Administration → Scanners & API Keys** → *Create API Key*. It's
   shown once - copy it somewhere safe, e.g. `export TS_API_KEY="..."` in your shell for now.
3. **Install `ts-scan`**, if you haven't: `pip install ts-scan`.
4. **Run the command(s) below**, one per unit listed in this report.
5. **Open the module in the app.** It's created automatically on first upload - you don't
   create it by hand. Give it a minute, then check its **Components** tab.
6. **Look at the traffic-light status.** Yellow or red on a first scan is normal - it means
   there's something to look at (a license, a vulnerability), not that something broke.
7. **Ask your project or compliance manager for an approval** once the status looks good
   enough to ship - that's a deliberate governance step, not automatic.
8. **Create a release** from the approved state. This is what TrustSource keeps watching for
   new vulnerabilities going forward, and what you'd hand a customer as an SBOM.

Full walkthrough: [ts-scan/recipes/01-first-module-to-sbom](https://trustsource.github.io/ts-scan).

## Concepts used in this report

- **Module** - one deployable piece of your software (a service, a library, a container
  image) that gets its own bill of materials and its own approval/release history.
- **Infrastructure Module** - a runtime dependency you don't build yourself (a database, a
  message broker, a base image) - tracked the same way, kept conceptually separate from
  what your team actually ships.
- **Linked Module** - when a Module has its own release cycle (e.g. a shared library with
  its own version), that release can be linked into another project instead of scanned a
  second time there.
"""


def _render_candidate(c: Candidate, level: Level) -> str:
    lines = [f'### `{c.path}` — {c.name}']

    if level == 'expert':
        lines.append('- Recommended command:')
        lines.append(f'  ```bash\n  {c.ts_scan_command}\n  ```')
        return '\n'.join(lines)

    if c.ecosystem:
        lines.append(f'- Ecosystem: {c.ecosystem}')
    lines.append(f'- Confidence: {c.confidence:.0%}')
    lines.append(f'- Rationale: {c.rationale}')
    lines.append('- Recommended command:')
    lines.append(f'  ```bash\n  {c.ts_scan_command}\n  ```')
    for warning in c.warnings:
        lines.append(f'- ⚠️ **Naming:** {warning}')
    if c.open_question:
        lines.append(f'- ⚠️ **Open question:** {c.open_question}')
    return '\n'.join(lines)


def _render_ecosystem_proposal(p: EcosystemProposal, issue_repo: str, level: Level) -> str:
    lines = [f'### {p.ecosystem}']
    lines.append(f'- Found at: {", ".join(f"`{path}`" for path in p.manifest_paths)}')

    if p.existing_issue:
        lines.append(
            f'- ⚠️ A possibly related issue already exists: '
            f'[#{p.existing_issue.number} {p.existing_issue.title}]({p.existing_issue.url}) '
            f'({p.existing_issue.state}) - consider commenting there instead of filing a new one.'
        )
        return '\n'.join(lines)

    if level == 'expert':
        title_arg = shlex.quote(p.title)
        body_arg = shlex.quote(p.body)
        lines.append(f'  ```bash\n  gh issue create --repo {issue_repo} --title {title_arg} '
                      f'--body {body_arg} --label enhancement\n  ```')
        return '\n'.join(lines)

    lines.append('- No existing issue found for this ecosystem.')
    lines.append('')
    lines.append(f'**Draft title:** {p.title}')
    lines.append('')
    lines.append(p.body)
    lines.append('')
    body_arg = shlex.quote(p.body)
    title_arg = shlex.quote(p.title)
    lines.append(
        f'File it yourself with:\n'
        f'  ```bash\n'
        f'  gh issue create --repo {issue_repo} --title {title_arg} --body {body_arg} '
        f'--label enhancement\n'
        f'  ```\n'
        f'  or re-run with `--file-issues` to be walked through review + filing.'
    )
    return '\n'.join(lines)


def render_markdown(concept: ScanConcept, detected_units: t.List[DetectedUnit],
                     issue_repo: str = 'trustsource/ts-scan', level: Level = 'intermediate') -> str:
    lines = [f'# TrustSource Scan Concept: {concept.project_name}', '', f'Generated for `{concept.source_path}`.', '']

    if level == 'beginner':
        lines.append(_GETTING_STARTED)
        lines.append('')

    if level != 'expert':
        lines.append(
            f'Create one TrustSource project (`{concept.project_name}`) and add the following '
            'units to it:'
        )
        lines.append('')
        lines.append(_NAMING_TIP)
        lines.append('')

    by_type: t.Dict[str, t.List[Candidate]] = {'module': [], 'infrastructure_module': [], 'linked_module': []}
    for c in concept.candidates:
        by_type[c.candidate_type].append(c)

    for candidate_type, title in _SECTION_TITLES.items():
        items = by_type[candidate_type]
        if not items:
            continue
        lines.append(f'## {title}')
        lines.append('')
        for c in sorted(items, key=lambda c: c.path):
            lines.append(_render_candidate(c, level))
            lines.append('')

    open_questions = concept.low_confidence_candidates
    if open_questions:
        lines.append('## Still open')
        lines.append('')
        if level == 'expert':
            for c in open_questions:
                lines.append(f'- `{c.path}`')
        else:
            lines.append(
                'The following items could not be classified with confidence and were not '
                'resolved (re-run interactively to answer them):'
            )
            lines.append('')
            for c in open_questions:
                lines.append(f'- `{c.path}` — {c.open_question}')
        lines.append('')

    ci_units = [u for u in detected_units if u.kind == 'ci_config']
    if ci_units:
        lines.append('## Detected CI/CD configuration')
        lines.append('')
        if level != 'expert':
            lines.append(
                'Wire the recommended `ts-scan` commands above into these pipelines so scans '
                'run on every build:'
            )
            lines.append('')
        for u in ci_units:
            lines.append(f'- `{u.path}`')
        lines.append('')

    monorepo_units = [u for u in detected_units if u.kind == 'monorepo_root']
    if monorepo_units and level != 'expert':
        lines.append('## Monorepo markers detected')
        lines.append('')
        lines.append(
            'ts-scan has no built-in monorepo mode - scan each workspace package individually '
            '(as reflected in the Modules above), never the monorepo root.'
        )
        lines.append('')

    if concept.ecosystem_proposals:
        lines.append('## Unsupported ecosystems detected')
        lines.append('')
        if level != 'expert':
            lines.append(
                'ts-scan has no scanner for these yet. A proposal for each is drafted below - '
                'review it (nothing is ever filed on GitHub automatically):'
            )
            lines.append('')
        for p in concept.ecosystem_proposals:
            lines.append(_render_ecosystem_proposal(p, issue_repo, level))
            lines.append('')

    return '\n'.join(lines)
