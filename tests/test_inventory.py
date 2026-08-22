import json

from pathlib import Path

from ts_scan_agent.inventory import scan_inventory


def _write(path: Path, content: str = '') -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def test_detects_npm_workspace_and_nested_packages(tmp_path: Path):
    _write(tmp_path / 'package.json', json.dumps({'name': 'root', 'workspaces': ['packages/*']}))
    _write(tmp_path / 'packages/a/package.json', json.dumps({'name': 'a', 'version': '1.0.0'}))
    _write(tmp_path / 'packages/b/package.json', json.dumps({'name': 'b', 'version': '1.0.0'}))

    units = scan_inventory(tmp_path)

    ecosystem_paths = {u.path for u in units if u.kind == 'ecosystem'}
    monorepo_paths = {u.path for u in units if u.kind == 'monorepo_root'}

    assert '.' in ecosystem_paths
    assert 'packages/a' in ecosystem_paths
    assert 'packages/b' in ecosystem_paths
    assert '.' in monorepo_paths


def test_detects_dockerfile_and_github_actions(tmp_path: Path):
    _write(tmp_path / 'Dockerfile', 'FROM node:22-alpine\n')
    _write(tmp_path / '.github/workflows/ci.yml', 'name: CI\n')

    units = scan_inventory(tmp_path)

    dockerfile_paths = {u.path for u in units if u.kind == 'dockerfile'}
    ci_paths = {u.path for u in units if u.kind == 'ci_config'}

    assert 'Dockerfile' in dockerfile_paths
    assert '.github/workflows/ci.yml' in ci_paths


def test_ignores_node_modules(tmp_path: Path):
    _write(tmp_path / 'package.json', '{}')
    _write(tmp_path / 'node_modules/some-dep/package.json', '{}')

    units = scan_inventory(tmp_path)
    ecosystem_paths = {u.path for u in units if u.kind == 'ecosystem'}

    assert not any('node_modules' in p for p in ecosystem_paths)
