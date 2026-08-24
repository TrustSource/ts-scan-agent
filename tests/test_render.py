from ts_scan_agent.model import ScanConcept, Candidate, DetectedUnit
from ts_scan_agent.render import render_markdown


def test_render_groups_by_candidate_type_and_shows_commands():
    concept = ScanConcept(
        project_name='demo',
        source_path='/tmp/demo',
        candidates=[
            Candidate(name='demo', path='.', candidate_type='module', ecosystem='Node',
                      ts_scan_command='ts-scan scan .', confidence=0.95,
                      rationale='root package'),
            Candidate(name='demo-container', path='Dockerfile',
                      candidate_type='infrastructure_module',
                      ts_scan_command='ts-scan docker <image>', confidence=0.4,
                      rationale='defaulted', open_question='Module or infra?'),
        ],
    )

    report = render_markdown(concept, detected_units=[])

    assert '# TrustSource Scan Concept: demo' in report
    assert '## Modules' in report
    assert '## Infrastructure Modules' in report
    assert 'ts-scan scan .' in report
    assert '## Still open' in report
    assert 'Module or infra?' in report


def test_render_lists_detected_ci_and_monorepo_markers():
    concept = ScanConcept(project_name='demo', source_path='/tmp/demo', candidates=[])
    units = [
        DetectedUnit(path='.github/workflows/ci.yml', kind='ci_config', evidence='found'),
        DetectedUnit(path='.', kind='monorepo_root', evidence='pnpm-workspace.yaml found'),
    ]

    report = render_markdown(concept, detected_units=units)

    assert '## Detected CI/CD configuration' in report
    assert '.github/workflows/ci.yml' in report
    assert '## Monorepo markers detected' in report


def test_render_always_shows_the_naming_tip():
    concept = ScanConcept(project_name='demo', source_path='/tmp/demo', candidates=[])

    report = render_markdown(concept, detected_units=[])

    assert 'Naming tip' in report
    assert 'muted vulnerabilities' in report


def test_render_shows_per_candidate_naming_warning():
    concept = ScanConcept(
        project_name='demo',
        source_path='/tmp/demo',
        candidates=[
            Candidate(name='api-1.4.2', path='.', candidate_type='module',
                      ts_scan_command='ts-scan scan .', confidence=0.95,
                      rationale='root package', warnings=['"api-1.4.2" looks versioned.']),
        ],
    )

    report = render_markdown(concept, detected_units=[])

    assert '⚠️ **Naming:**' in report
    assert '"api-1.4.2" looks versioned.' in report
