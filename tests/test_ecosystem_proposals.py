import json

from pathlib import Path

from ts_scan_agent.inventory import scan_inventory
from ts_scan_agent.model import DetectedUnit
from ts_scan_agent.ecosystem_proposals import build_proposals


def _write(path: Path, content: str = '') -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def test_composer_manifest_produces_a_proposal_with_static_facts(tmp_path: Path):
    _write(tmp_path / 'composer.json', json.dumps({'require': {'php': '>=8.0'}}))

    units = scan_inventory(tmp_path)
    proposals = build_proposals(units)

    assert len(proposals) == 1
    p = proposals[0]
    assert p.ecosystem == 'PHP (Composer)'
    assert p.manifest_paths == ['.']
    assert 'Packagist' in p.body
    assert p.title == 'Add ts-scan support for PHP (Composer)'


def test_cmake_project_does_not_produce_a_proposal(tmp_path: Path):
    # C/C++ is already covered via DeepScan - CMakeLists.txt must never look "unsupported".
    _write(tmp_path / 'CMakeLists.txt', 'project(demo)\n')

    units = scan_inventory(tmp_path)
    proposals = build_proposals(units)

    assert proposals == []


def test_composer_json_next_to_known_scanner_manifest_is_not_flagged(tmp_path: Path):
    _write(tmp_path / 'package.json', '{}')
    _write(tmp_path / 'composer.json', '{}')

    units = scan_inventory(tmp_path)

    assert not any(u.kind == 'unsupported_ecosystem' for u in units)


def test_multiple_manifests_of_same_ecosystem_are_deduped_into_one_proposal():
    units = [
        DetectedUnit(path='a', kind='unsupported_ecosystem', ecosystem='PHP (Composer)',
                     evidence='composer.json found'),
        DetectedUnit(path='b', kind='unsupported_ecosystem', ecosystem='PHP (Composer)',
                     evidence='composer.json found'),
    ]

    proposals = build_proposals(units)

    assert len(proposals) == 1
    assert sorted(proposals[0].manifest_paths) == ['a', 'b']
