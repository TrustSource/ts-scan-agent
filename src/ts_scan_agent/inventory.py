import os
import typing as t

from pathlib import Path

from .model import DetectedUnit

IGNORED_DIRS = {
    '.git', '.hg', '.svn',
    'node_modules', 'vendor', 'venv', '.venv', '__pycache__',
    'dist', 'build', 'target', 'bin', 'obj',
    '.mypy_cache', '.pytest_cache', '.ruff_cache', '.tox',
}

MAX_DEPTH = 6

CI_CONFIG_FILES = {
    '.gitlab-ci.yml', 'Jenkinsfile', 'azure-pipelines.yml',
}

DOCKERFILE_NAMES = {'Dockerfile'}

MONOREPO_MARKER_FILES = {
    'pnpm-workspace.yaml', 'lerna.json', 'nx.json', 'rush.json',
}


def _pm_scanner_classes() -> t.List[type]:
    """The ecosystem detectors we reuse from ts-scan, rather than re-implementing manifest
    detection ourselves. Each Scanner subclass exposes a cheap, filesystem-only accepts()."""
    from ts_scan.pm.pypi import PypiScanner
    from ts_scan.pm.maven import MavenScanner
    from ts_scan.pm.gradle import GradleScanner
    from ts_scan.pm.node import NodeScanner
    from ts_scan.pm.nuget import NugetScanner
    from ts_scan.pm.cargo import CargoScanner
    from ts_scan.pm.golang import GolangScanner
    from ts_scan.pm.dart import DartScanner

    return [
        PypiScanner, MavenScanner, GradleScanner, NodeScanner,
        NugetScanner, CargoScanner, GolangScanner, DartScanner,
    ]


def _instantiate_scanner(cls: type):
    """Most Scanner subclasses take no required args beyond the common Scanner.__init__
    kwargs, since accepts() is a pure filesystem check that doesn't need them. GradleScanner
    is the one exception (a required `configuration` arg only used later by scan(), never by
    accepts()) - special-cased here rather than in every caller."""
    if cls.name() == 'Gradle':
        return cls(configuration=None)
    return cls()


def _has_npm_workspaces(package_json: Path) -> bool:
    import json

    try:
        data = json.loads(package_json.read_text())
    except (OSError, ValueError):
        return False

    return bool(data.get('workspaces'))


def scan_inventory(root: Path, max_depth: int = MAX_DEPTH) -> t.List[DetectedUnit]:
    """Deterministic, LLM-free repo walk: finds ecosystem manifests (via ts-scan's own
    detectors), Dockerfiles, CI configs and monorepo markers."""

    root = root.resolve()
    scanners = [_instantiate_scanner(cls) for cls in _pm_scanner_classes()]
    units: t.List[DetectedUnit] = []

    for dirpath, dirnames, filenames in os.walk(root):
        current = Path(dirpath)
        depth = len(current.relative_to(root).parts)

        dirnames[:] = [d for d in dirnames if d not in IGNORED_DIRS]

        if depth > max_depth:
            dirnames[:] = []
            continue

        for scanner in scanners:
            if scanner.accepts(current):
                units.append(DetectedUnit(
                    path=str(current.relative_to(root)) or '.',
                    kind='ecosystem',
                    ecosystem=scanner.name(),
                    evidence=f'{scanner.name()} manifest found',
                ))

        for filename in filenames:
            if filename in DOCKERFILE_NAMES or filename.startswith('Dockerfile.'):
                units.append(DetectedUnit(
                    path=str((current / filename).relative_to(root)),
                    kind='dockerfile',
                    evidence=f'{filename} found',
                ))
            elif filename in MONOREPO_MARKER_FILES:
                units.append(DetectedUnit(
                    path=str(current.relative_to(root)) or '.',
                    kind='monorepo_root',
                    evidence=f'{filename} found',
                ))
            elif filename == 'package.json' and _has_npm_workspaces(current / filename):
                units.append(DetectedUnit(
                    path=str(current.relative_to(root)) or '.',
                    kind='monorepo_root',
                    evidence='package.json "workspaces" field found',
                ))
            elif filename in CI_CONFIG_FILES:
                units.append(DetectedUnit(
                    path=str((current / filename).relative_to(root)),
                    kind='ci_config',
                    evidence=f'{filename} found',
                ))

        if current.name == '.github' and 'workflows' in dirnames:
            workflows_dir = current / 'workflows'
            for wf in workflows_dir.glob('*.yml'):
                units.append(DetectedUnit(
                    path=str(wf.relative_to(root)),
                    kind='ci_config',
                    evidence='GitHub Actions workflow found',
                ))
            for wf in workflows_dir.glob('*.yaml'):
                units.append(DetectedUnit(
                    path=str(wf.relative_to(root)),
                    kind='ci_config',
                    evidence='GitHub Actions workflow found',
                ))

    return units
