import json
import typing as t

from pathlib import Path, PurePosixPath

from .model import DetectedUnit, Candidate
from .llm import LLMClient, NullLLMClient

DOCKERFILE_JUDGE_SCHEMA = {
    'type': 'object',
    'properties': {
        'candidate_type': {'type': 'string', 'enum': ['module', 'infrastructure_module']},
        'confidence': {'type': 'number'},
        'rationale': {'type': 'string'},
    },
    'required': ['candidate_type', 'confidence', 'rationale'],
    'additionalProperties': False,
}


def _module_name(path: str, project_name: str) -> str:
    if path in ('.', ''):
        return project_name
    return PurePosixPath(path).name


def _scan_command(path: str, name: str, project_name: str) -> str:
    target = '.' if path in ('.', '') else path
    return (
        f'ts-scan scan {target} -o {name}.json && '
        f'ts-scan upload --project "{project_name}" --module "{name}" {name}.json'
    )


def _looks_independently_released(root: Path, ecosystem: str, rel_path: str) -> bool:
    """Best-effort heuristic for Linked-Module candidates: does this nested package look like
    it has its own release cadence, separate from the monorepo root? Currently only
    implemented for Node/npm (package.json's "private"/"version" fields are cheap, reliable
    signals); other ecosystems fall back to plain Module classification for now — a known
    limitation, see ARCHITECTURE.md."""

    if ecosystem != 'Node':
        return False

    manifest = root / rel_path / 'package.json'
    try:
        data = json.loads(manifest.read_text())
    except (OSError, ValueError):
        return False

    return bool(data.get('version')) and not data.get('private', False)


def build_candidates(project_name: str, root: Path, units: t.List[DetectedUnit],
                      llm: t.Optional[LLMClient] = None) -> t.List[Candidate]:
    llm = llm or NullLLMClient()

    monorepo_roots = {u.path for u in units if u.kind == 'monorepo_root'}
    ecosystem_units = [u for u in units if u.kind == 'ecosystem']
    dockerfile_units = [u for u in units if u.kind == 'dockerfile']

    candidates: t.List[Candidate] = []

    for unit in ecosystem_units:
        name = _module_name(unit.path, project_name)
        is_nested = unit.path not in ('.', '')
        under_monorepo = any(
            r == '.' or unit.path == r or unit.path.startswith(r + '/') for r in monorepo_roots
        )
        command = _scan_command(unit.path, name, project_name)

        if not is_nested:
            candidates.append(Candidate(
                name=name, path=unit.path, candidate_type='module',
                ecosystem=unit.ecosystem, ts_scan_command=command,
                confidence=0.95, rationale=f'{unit.evidence}; root of the repository',
                open_question=None,
            ))
            continue

        if under_monorepo and unit.ecosystem and \
                _looks_independently_released(root, unit.ecosystem, unit.path):
            candidates.append(Candidate(
                name=name, path=unit.path, candidate_type='linked_module',
                ecosystem=unit.ecosystem, ts_scan_command=command,
                confidence=0.75,
                rationale=(
                    f'{unit.evidence} in a monorepo workspace; its manifest declares its own '
                    'version and is not marked private, suggesting it is published/released '
                    'independently - consider scanning it as its own TrustSource project and '
                    'linking the release into this project as a Linked Module'
                ),
                open_question=(
                    f'Does "{unit.path}" get published/released on its own (npm registry, '
                    'internal registry, separate versioning)? If yes, set it up as its own '
                    'TrustSource project and link its release here instead of scanning it as '
                    'a plain Module.'
                ),
            ))
            continue

        if under_monorepo:
            candidates.append(Candidate(
                name=name, path=unit.path, candidate_type='module',
                ecosystem=unit.ecosystem, ts_scan_command=command,
                confidence=0.9,
                rationale=(
                    f'{unit.evidence} inside a detected monorepo workspace, so it is a '
                    'separately scanned package per ts-scan\'s documented monorepo pattern '
                    '(scan each workspace package individually, never the monorepo root)'
                ),
                open_question=None,
            ))
            continue

        candidates.append(Candidate(
            name=name, path=unit.path, candidate_type='module',
            ecosystem=unit.ecosystem, ts_scan_command=command,
            confidence=0.5,
            rationale=(
                f'{unit.evidence} in a nested directory with no monorepo marker found - could '
                'be its own module, or just a vendored/example subfolder of the parent module'
            ),
            open_question=(
                f'Is "{unit.path}" released/deployed separately from the rest of the repo? '
                'If yes, it should be its own Module; if no, fold it into the parent module\'s '
                'scan instead.'
            ),
        ))

    for unit in dockerfile_units:
        dir_path = str(PurePosixPath(unit.path).parent)
        name = f'{_module_name(dir_path, project_name)}-container'
        command = f'ts-scan docker <image> --project "{project_name}" --module "{name}"'

        judged = llm.judge(
            prompt=(
                f'A Dockerfile was found at "{unit.path}" in a software repository. '
                'In TrustSource\'s data model, a "Module" is a deployable unit the team '
                'builds and ships as its own release; an "Infrastructure Module" is a '
                'runtime dependency the team does not build itself (a base image, database, '
                'message broker, etc). Classify this Dockerfile and explain your reasoning '
                'in one sentence.'
            ),
            schema=DOCKERFILE_JUDGE_SCHEMA,
        )

        if judged:
            candidates.append(Candidate(
                name=name, path=unit.path, candidate_type=judged['candidate_type'],
                ts_scan_command=command, confidence=float(judged['confidence']),
                rationale=judged['rationale'], open_question=None,
            ))
        else:
            candidates.append(Candidate(
                name=name, path=unit.path, candidate_type='infrastructure_module',
                ts_scan_command=command, confidence=0.4,
                rationale=(
                    f'{unit.evidence}; defaulting to Infrastructure Module per TrustSource\'s '
                    'container-scanning guidance, but this is only a default, not a judgment'
                ),
                open_question=(
                    f'Is the image built from "{unit.path}" your own deployable service, or '
                    'runtime infrastructure (base image, sidecar, etc.)? This changes whether '
                    'it should be a Module or an Infrastructure Module.'
                ),
            ))

    return candidates
