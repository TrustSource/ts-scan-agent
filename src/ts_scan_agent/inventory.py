import os
import typing as t

from pathlib import Path

import pathspec

from .model import DetectedUnit

IGNORED_DIRS = {
    '.git', '.hg', '.svn',
    'node_modules', 'vendor', 'venv', '.venv', '__pycache__',
    'dist', 'build', 'target', 'bin', 'obj',
    '.mypy_cache', '.pytest_cache', '.ruff_cache', '.tox',
    'Pods',  # CocoaPods' vendor dir - iOS/macOS equivalent of node_modules
}

MAX_DEPTH = 6

CI_CONFIG_FILES = {
    '.gitlab-ci.yml', 'Jenkinsfile', 'azure-pipelines.yml',
}

DOCKERFILE_NAMES = {'Dockerfile'}

MONOREPO_MARKER_FILES = {
    'pnpm-workspace.yaml', 'lerna.json', 'nx.json', 'rush.json',
    'melos.yaml',  # Dart/Flutter monorepo tool - https://melos.invertase.dev
}

# Ecosystems ts-scan has no dependency-tree scanner for. Deliberately excludes anything
# ts-scan already covers - including C/C++, which is handled via DeepScan integration even
# though it has no ts_scan.pm.Scanner subclass, so no C/C++ build files belong in this list.
# This is a starting set, not exhaustive - extend as gaps are found; see ARCHITECTURE.md.
UNSUPPORTED_ECOSYSTEM_MARKERS = {
    'composer.json': 'PHP (Composer)',
    'Gemfile': 'Ruby (Bundler)',
    'Package.swift': 'Swift (Swift Package Manager)',
    'mix.exs': 'Elixir (Hex)',
    'stack.yaml': 'Haskell (Stack)',
    'cpanfile': 'Perl (CPAN)',
    'build.zig': 'Zig',
    'elm.json': 'Elm',
}

UNSUPPORTED_ECOSYSTEM_EXTENSIONS = {
    '.cabal': 'Haskell (Cabal)',
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


def _load_gitignore_spec(root: Path) -> t.Optional[pathspec.PathSpec]:
    """Only the root `.gitignore` is honored - not nested per-directory ones, and not
    ecosystem-equivalents like `.dockerignore`/`.npmignore` (different semantics: build-context
    and publish exclusion, not "not part of the source"). This is the common case for most
    repos; a known limitation, see ARCHITECTURE.md."""
    gitignore = root / '.gitignore'
    if not gitignore.is_file():
        return None

    try:
        lines = gitignore.read_text(errors='ignore').splitlines()
    except OSError:
        return None

    return pathspec.PathSpec.from_lines('gitwildmatch', lines)


def _has_npm_workspaces(package_json: Path) -> bool:
    import json

    try:
        data = json.loads(package_json.read_text())
    except (OSError, ValueError):
        return False

    return bool(data.get('workspaces'))


def scan_inventory(root: Path, max_depth: int = MAX_DEPTH) -> t.List[DetectedUnit]:
    """Deterministic, LLM-free repo walk: finds ecosystem manifests (via ts-scan's own
    detectors), Dockerfiles, CI configs and monorepo markers. Honors the repo's root
    `.gitignore`, if present - directories it excludes are never descended into, and files it
    excludes are never treated as evidence, so generated/vendored/ignored content doesn't
    produce false candidates or false "unsupported ecosystem" proposals."""

    root = root.resolve()
    scanners = [_instantiate_scanner(cls) for cls in _pm_scanner_classes()]
    gitignore_spec = _load_gitignore_spec(root)
    units: t.List[DetectedUnit] = []

    for dirpath, dirnames, filenames in os.walk(root):
        current = Path(dirpath)
        depth = len(current.relative_to(root).parts)

        dirnames[:] = [d for d in dirnames if d not in IGNORED_DIRS]

        if gitignore_spec is not None:
            dirnames[:] = [
                d for d in dirnames
                if not gitignore_spec.match_file(str((current / d).relative_to(root)) + '/')
            ]
            filenames = [
                f for f in filenames
                if not gitignore_spec.match_file(str((current / f).relative_to(root)))
            ]

        if depth > max_depth:
            dirnames[:] = []
            continue

        known_ecosystem_found = False
        for scanner in scanners:
            if scanner.accepts(current):
                known_ecosystem_found = True
                units.append(DetectedUnit(
                    path=str(current.relative_to(root)) or '.',
                    kind='ecosystem',
                    ecosystem=scanner.name(),
                    evidence=f'{scanner.name()} manifest found',
                ))

        if not known_ecosystem_found:
            for filename in filenames:
                display_name = (
                    UNSUPPORTED_ECOSYSTEM_MARKERS.get(filename)
                    or UNSUPPORTED_ECOSYSTEM_EXTENSIONS.get(Path(filename).suffix)
                )
                if display_name:
                    units.append(DetectedUnit(
                        path=str(current.relative_to(root)) or '.',
                        kind='unsupported_ecosystem',
                        ecosystem=display_name,
                        evidence=f'{filename} found, no ts-scan scanner for {display_name}',
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
