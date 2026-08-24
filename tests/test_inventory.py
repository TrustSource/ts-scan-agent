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


def test_honors_root_gitignore_for_directories(tmp_path: Path):
    _write(tmp_path / '.gitignore', 'generated/\n')
    _write(tmp_path / 'package.json', '{}')
    _write(tmp_path / 'generated/composer.json', '{}')  # would otherwise be an unsupported-ecosystem hit

    units = scan_inventory(tmp_path)

    assert not any(u.path.startswith('generated') for u in units)


def test_honors_root_gitignore_for_individual_files(tmp_path: Path):
    _write(tmp_path / '.gitignore', 'Dockerfile.bak\n')
    _write(tmp_path / 'Dockerfile', 'FROM alpine\n')
    _write(tmp_path / 'Dockerfile.bak', 'FROM alpine\n')

    units = scan_inventory(tmp_path)
    dockerfile_paths = {u.path for u in units if u.kind == 'dockerfile'}

    assert dockerfile_paths == {'Dockerfile'}


def test_works_without_a_gitignore_present(tmp_path: Path):
    _write(tmp_path / 'package.json', '{}')

    units = scan_inventory(tmp_path)

    assert any(u.kind == 'ecosystem' for u in units)
