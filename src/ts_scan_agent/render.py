import typing as t

from .model import ScanConcept, Candidate, DetectedUnit

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


def render_markdown(concept: ScanConcept, detected_units: t.List[DetectedUnit]) -> str:
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

    return '\n'.join(lines)
