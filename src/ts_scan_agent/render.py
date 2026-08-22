import shlex
import typing as t

from .model import ScanConcept, Candidate, DetectedUnit, EcosystemProposal

_SECTION_TITLES = {
    'module': 'Modules',
    'infrastructure_module': 'Infrastructure Modules',
    'linked_module': 'Linked Module candidates',
}


def _render_candidate(c: Candidate) -> str:
    lines = [f'### `{c.path}` — {c.name}']
    if c.ecosystem:
        lines.append(f'- Ecosystem: {c.ecosystem}')
    lines.append(f'- Confidence: {c.confidence:.0%}')
    lines.append(f'- Rationale: {c.rationale}')
    lines.append('- Recommended command:')
    lines.append(f'  ```bash\n  {c.ts_scan_command}\n  ```')
    if c.open_question:
        lines.append(f'- ⚠️ **Open question:** {c.open_question}')
    return '\n'.join(lines)


def _render_ecosystem_proposal(p: EcosystemProposal, issue_repo: str) -> str:
    lines = [f'### {p.ecosystem}']
    lines.append(f'- Found at: {", ".join(f"`{path}`" for path in p.manifest_paths)}')

    if p.existing_issue:
        lines.append(
            f'- ⚠️ A possibly related issue already exists: '
            f'[#{p.existing_issue.number} {p.existing_issue.title}]({p.existing_issue.url}) '
            f'({p.existing_issue.state}) - consider commenting there instead of filing a new one.'
        )
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
                     issue_repo: str = 'trustsource/ts-scan') -> str:
    lines = [
        f'# TrustSource Scan Concept: {concept.project_name}',
        '',
        f'Generated for `{concept.source_path}`.',
        '',
        f'Create one TrustSource project (`{concept.project_name}`) and add the following '
        'units to it:',
        '',
    ]

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
            lines.append(_render_candidate(c))
            lines.append('')

    open_questions = concept.low_confidence_candidates
    if open_questions:
        lines.append('## Still open')
        lines.append('')
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
        lines.append(
            'Wire the recommended `ts-scan` commands above into these pipelines so scans run '
            'on every build:'
        )
        lines.append('')
        for u in ci_units:
            lines.append(f'- `{u.path}`')
        lines.append('')

    monorepo_units = [u for u in detected_units if u.kind == 'monorepo_root']
    if monorepo_units:
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
        lines.append(
            'ts-scan has no scanner for these yet. A proposal for each is drafted below - '
            'review it (nothing is ever filed on GitHub automatically):'
        )
        lines.append('')
        for p in concept.ecosystem_proposals:
            lines.append(_render_ecosystem_proposal(p, issue_repo))
            lines.append('')

    return '\n'.join(lines)
