import json
import typing as t

from pathlib import Path

from ts_scan_agent.model import DetectedUnit
from ts_scan_agent.mapping import build_candidates
from ts_scan_agent.llm import LLMClient


class FakeLLMClient(LLMClient):
    def __init__(self, response: t.Dict[str, t.Any]):
        self.response = response
        self.calls = 0

    def judge(self, prompt: str, schema: t.Dict[str, t.Any]) -> t.Dict[str, t.Any]:
        self.calls += 1
        return self.response


def _write(path: Path, content: str = '') -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def test_root_ecosystem_is_high_confidence_module(tmp_path: Path):
    units = [DetectedUnit(path='.', kind='ecosystem', ecosystem='Node', evidence='package.json found')]

    candidates = build_candidates('demo', tmp_path, units)

    assert len(candidates) == 1
    c = candidates[0]
    assert c.candidate_type == 'module'
    assert c.confidence >= 0.9
    assert c.open_question is None
    assert c.name == 'demo'


def test_nested_package_without_monorepo_marker_is_ambiguous(tmp_path: Path):
    units = [DetectedUnit(path='examples/demo', kind='ecosystem', ecosystem='Node',
                           evidence='package.json found')]

    candidates = build_candidates('proj', tmp_path, units)

    assert len(candidates) == 1
    c = candidates[0]
    assert c.candidate_type == 'module'
    assert c.confidence < 0.6
    assert c.open_question is not None


def test_nested_independently_versioned_package_becomes_linked_module_candidate(tmp_path: Path):
    _write(tmp_path / 'packages/a/package.json', json.dumps({'name': 'a', 'version': '2.1.0'}))

    units = [
        DetectedUnit(path='.', kind='monorepo_root', evidence='pnpm-workspace.yaml found'),
        DetectedUnit(path='packages/a', kind='ecosystem', ecosystem='Node',
                     evidence='Node manifest found'),
    ]

    candidates = build_candidates('proj', tmp_path, units)

    assert len(candidates) == 1
    assert candidates[0].candidate_type == 'linked_module'
    assert candidates[0].open_question is not None


def test_dockerfile_uses_llm_judgment_when_available(tmp_path: Path):
    units = [DetectedUnit(path='Dockerfile', kind='dockerfile', evidence='Dockerfile found')]
    llm = FakeLLMClient({'candidate_type': 'module', 'confidence': 0.9, 'rationale': 'own service'})

    candidates = build_candidates('proj', tmp_path, units, llm=llm)

    assert llm.calls == 1
    assert len(candidates) == 1
    assert candidates[0].candidate_type == 'module'
    assert candidates[0].confidence == 0.9
    assert candidates[0].open_question is None


def test_dockerfile_defaults_to_infra_module_with_open_question_when_no_llm(tmp_path: Path):
    units = [DetectedUnit(path='Dockerfile', kind='dockerfile', evidence='Dockerfile found')]

    candidates = build_candidates('proj', tmp_path, units)

    assert len(candidates) == 1
    assert candidates[0].candidate_type == 'infrastructure_module'
    assert candidates[0].open_question is not None
