#!/usr/bin/env python3
"""Dependency-free port of the ts-scan-agent pipeline (Inventory -> Mapping -> Render) for the
ts-scan-agent Agent Skill. Standard library only, Python 3.8+, so the skill works on any machine
with a Python interpreter and nothing installed.

The installable `ts_scan_agent` package is the source of truth. This file mirrors it for the
`--llm none` path: every ambiguous case becomes an open question that the coding agent asks the
user in chat and passes back with --answers. tests/test_skill_scripts.py runs this script and
the package on the same fixtures and fails on any difference, so the two can't drift silently.
scan_concept.mjs is the same port for machines that only have Node.js.

Usage:
    python3 scan_concept.py analyze PATH [--format json|markdown] [--answers FILE] [--level ...]
"""

import argparse
import json
import os
import re
import shlex
import sys

VERSION = '0.7.0'

# --- Inventory (mirrors src/ts_scan_agent/inventory.py) -------------------------------------

IGNORED_DIRS = {
    '.git', '.hg', '.svn',
    'node_modules', 'vendor', 'venv', '.venv', '__pycache__',
    'dist', 'build', 'target', 'bin', 'obj',
    '.mypy_cache', '.pytest_cache', '.ruff_cache', '.tox',
    'Pods',
}

MAX_DEPTH = 6

CI_CONFIG_FILES = {'.gitlab-ci.yml', 'Jenkinsfile', 'azure-pipelines.yml'}

DOCKERFILE_NAMES = {'Dockerfile'}

MONOREPO_MARKER_FILES = {'pnpm-workspace.yaml', 'lerna.json', 'nx.json', 'rush.json', 'melos.yaml'}

UNSUPPORTED_ECOSYSTEM_MARKERS = {
    'composer.json': 'PHP (Composer)',
    'Gemfile': 'Ruby (Bundler)',
    'Package.swift': 'Swift (Swift Package Manager)',
    'Podfile': 'iOS (CocoaPods)',
    'mix.exs': 'Elixir (Hex)',
    'stack.yaml': 'Haskell (Stack)',
    'cpanfile': 'Perl (CPAN)',
    'build.zig': 'Zig',
    'elm.json': 'Elm',
}

UNSUPPORTED_ECOSYSTEM_EXTENSIONS = {'.cabal': 'Haskell (Cabal)'}


def _glob_any(entries, pattern):
    regex = re.compile(_translate_segment_glob(pattern) + '$')
    return any(regex.match(e) for e in entries)


# Each entry mirrors one ts_scan.pm.*Scanner.accepts(dir), in the order inventory.py asks them.
def _detect_ecosystems(dirpath):
    try:
        entries = os.listdir(dirpath)
    except OSError:
        return []
    names = set(entries)
    found = []
    if 'setup.py' in names or 'pyproject.toml' in names:
        found.append('PyPI')
    if 'pom.xml' in names:
        found.append('Maven')
    if 'build.gradle' in names or 'build.gradle.kts' in names:
        found.append('Gradle')
    if 'package.json' in names:
        found.append('Node')
    if (_glob_any(entries, '*.nuspec') or _glob_any(entries, '*.*proj')
            or 'packages.config' in names or _glob_any(entries, '*.sln')):
        found.append('NuGet')
    if 'Cargo.toml' in names:
        found.append('Cargo')
    if 'go.mod' in names:
        found.append('Golang')
    if 'pubspec.yaml' in names:
        found.append('Dart')
    return found


# gitignore matching: a port of pathspec 0.12's GitWildMatchPattern, which inventory.py uses.
def _translate_segment_glob(pattern):
    escape = False
    regex = ''
    i, end = 0, len(pattern)
    while i < end:
        char = pattern[i]
        i += 1
        if escape:
            escape = False
            regex += re.escape(char)
        elif char == '\\':
            escape = True
        elif char == '*':
            regex += '[^/]*'
        elif char == '?':
            regex += '[^/]'
        elif char == '[':
            j = i
            if j < end and pattern[j] in '!^':
                j += 1
            if j < end and pattern[j] == ']':
                j += 1
            while j < end and pattern[j] != ']':
                j += 1
            if j < end:
                j += 1
                expr = '['
                if pattern[i] in '!^':
                    expr += '^'
                    i += 1
                expr += pattern[i:j].replace('\\', '\\\\')
                regex += expr
                i = j
            else:
                regex += '\\['
        else:
            regex += re.escape(char)
    if escape:
        raise ValueError('dangling escape')
    return regex


def _gitignore_pattern_to_regex(pattern):
    pattern = pattern.lstrip() if pattern.endswith('\\ ') else pattern.strip()
    if not pattern or pattern.startswith('#') or pattern == '/':
        return None, None

    include = True
    if pattern.startswith('!'):
        include = False
        pattern = pattern[1:]

    segs = pattern.split('/')
    is_dir_pattern = not segs[-1]
    for i in range(len(segs) - 1, 0, -1):
        if segs[i - 1] == '**' and segs[i] == '**':
            del segs[i]

    if len(segs) == 2 and segs[0] == '**' and not segs[1]:
        return '^.+/.*$', include

    if not segs[0]:
        del segs[0]
    elif len(segs) == 1 or (len(segs) == 2 and not segs[1]):
        if segs[0] != '**':
            segs.insert(0, '**')
    if not segs:
        return None, None
    if not segs[-1] and len(segs) > 1:
        segs[-1] = '**'

    out = ['^']
    need_slash = False
    end = len(segs) - 1
    for i, seg in enumerate(segs):
        if seg == '**':
            if i == 0 and i == end:
                out.append('[^/]+(?:/.*)?')
            elif i == 0:
                out.append('(?:.+/)?')
                need_slash = False
            elif i == end:
                out.append('/.*')
            else:
                out.append('(?:/.+)?')
                need_slash = True
        elif seg == '*':
            if need_slash:
                out.append('/')
            out.append('[^/]+')
            if i == end:
                out.append('(?:/.*)?')
            need_slash = True
        else:
            if need_slash:
                out.append('/')
            try:
                out.append(_translate_segment_glob(seg))
            except ValueError:
                return None, None
            if i == end:
                out.append('(?:/.*)?')
            need_slash = True
    out.append('$')
    return ''.join(out), include


def _load_gitignore(root):
    try:
        with open(os.path.join(root, '.gitignore'), encoding='utf-8', errors='ignore') as fp:
            lines = fp.read().splitlines()
    except OSError:
        return None
    spec = []
    for line in lines:
        regex, include = _gitignore_pattern_to_regex(line)
        if regex is None:
            continue
        try:
            spec.append((re.compile(regex), include))
        except re.error:
            pass  # A range like `[z-a]` never matches in git either - skip it, as the Node port does.
    return spec


def _gitignored(spec, rel_path):
    matched = False
    for regex, include in spec:
        if regex.match(rel_path):
            matched = include
    return matched


def _has_npm_workspaces(package_json):
    try:
        with open(package_json, encoding='utf-8') as fp:
            data = json.load(fp)
    except (OSError, ValueError):
        return False
    return isinstance(data, dict) and bool(data.get('workspaces'))


def _unit(path, kind, evidence, ecosystem=None):
    return {'path': path, 'kind': kind, 'ecosystem': ecosystem, 'evidence': evidence}


def scan_inventory(root, max_depth=MAX_DEPTH):
    spec = _load_gitignore(root)
    units = []

    def rel(*parts):
        joined = '/'.join(p for p in parts if p)
        return joined or '.'

    def walk(rel_dir, depth):
        abs_dir = os.path.join(root, rel_dir) if rel_dir else root
        try:
            entries = sorted(os.listdir(abs_dir))
        except OSError:
            return
        dirnames = [e for e in entries if os.path.isdir(os.path.join(abs_dir, e))
                    and not os.path.islink(os.path.join(abs_dir, e))]
        filenames = [e for e in entries if e not in dirnames
                     and not os.path.isdir(os.path.join(abs_dir, e))]

        dirnames = [d for d in dirnames if d not in IGNORED_DIRS]
        if spec is not None:
            dirnames = [d for d in dirnames if not _gitignored(spec, rel(rel_dir, d) + '/')]
            filenames = [f for f in filenames if not _gitignored(spec, rel(rel_dir, f))]

        if depth > max_depth:
            return

        here = rel(rel_dir)
        ecosystems = _detect_ecosystems(abs_dir)
        for name in ecosystems:
            units.append(_unit(here, 'ecosystem', f'{name} manifest found', name))

        if not ecosystems:
            for filename in filenames:
                display = (UNSUPPORTED_ECOSYSTEM_MARKERS.get(filename)
                           or UNSUPPORTED_ECOSYSTEM_EXTENSIONS.get(os.path.splitext(filename)[1]))
                if display:
                    units.append(_unit(
                        here, 'unsupported_ecosystem',
                        f'{filename} found, no ts-scan scanner for {display}', display,
                    ))

        for filename in filenames:
            if filename in DOCKERFILE_NAMES or filename.startswith('Dockerfile.'):
                units.append(_unit(rel(rel_dir, filename), 'dockerfile', f'{filename} found'))
            elif filename in MONOREPO_MARKER_FILES:
                units.append(_unit(here, 'monorepo_root', f'{filename} found'))
            elif filename == 'package.json' and _has_npm_workspaces(os.path.join(abs_dir, filename)):
                units.append(_unit(here, 'monorepo_root', 'package.json "workspaces" field found'))
            elif filename in CI_CONFIG_FILES:
                units.append(_unit(rel(rel_dir, filename), 'ci_config', f'{filename} found'))

        if os.path.basename(abs_dir) == '.github' and 'workflows' in dirnames:
            workflows = os.path.join(abs_dir, 'workflows')
            try:
                wf_entries = sorted(os.listdir(workflows))
            except OSError:
                wf_entries = []
            for ext in ('.yml', '.yaml'):
                for wf in wf_entries:
                    if wf.endswith(ext) and os.path.isfile(os.path.join(workflows, wf)):
                        units.append(_unit(rel(rel_dir, 'workflows', wf), 'ci_config',
                                           'GitHub Actions workflow found'))

        for d in dirnames:
            walk(rel(rel_dir, d) if rel_dir else d, depth + 1)

    walk('', 0)
    return units


# --- Mapping (mirrors src/ts_scan_agent/mapping.py, no-LLM path) ----------------------------

_DOCKER_TAG_VERSION_RE = re.compile(r':v?\d+(\.\d+)*([-_][a-zA-Z0-9.]+)?$')
_DOTTED_VERSION_RE = re.compile(r'(?:^|[-_ ])v?\d+\.\d+(?:\.\d+)?(?:$|[-_ ])')
_BARE_V_SUFFIX_RE = re.compile(r'[-_]v\d+$')


def _naming_warnings(name):
    if (_DOCKER_TAG_VERSION_RE.search(name) or _DOTTED_VERSION_RE.search(name)
            or _BARE_V_SUFFIX_RE.search(name)):
        return [
            f'"{name}" looks like it embeds a version or image tag. Keep TrustSource module '
            'names stable across releases (e.g. "api-runtime", not "api-1.4.2" or '
            '"node-22-alpine") - a version bump would otherwise create a brand-new module and '
            'silently lose everything attached to the old one, including muted vulnerabilities '
            'and approval history.'
        ]
    return []


def _module_name(path, project_name):
    if path in ('.', ''):
        return project_name
    return path.rstrip('/').split('/')[-1]


def _scan_command(path, name, project_name):
    target = '.' if path in ('.', '') else path
    return (
        f'ts-scan scan {target} -o {name}.json && '
        f'ts-scan upload --project-name "{project_name}" --api-key "$TS_API_KEY" {name}.json'
    )


def _docker_scan_command(name, project_name):
    return (
        f'ts-scan scan --use-syft docker:<image> -o {name}.json && '
        f'ts-scan upload --project-name "{project_name}" --api-key "$TS_API_KEY" {name}.json'
    )


def _looks_independently_released(root, ecosystem, rel_path):
    if ecosystem != 'Node':
        return False
    try:
        with open(os.path.join(root, rel_path, 'package.json'), encoding='utf-8') as fp:
            data = json.load(fp)
    except (OSError, ValueError):
        return False
    if not isinstance(data, dict):
        return False
    return bool(data.get('version')) and not data.get('private', False)


def _candidate(name, path, candidate_type, command, confidence, rationale,
               open_question=None, ecosystem=None):
    return {
        'name': name,
        'path': path,
        'candidate_type': candidate_type,
        'ecosystem': ecosystem,
        'ts_scan_command': command,
        'confidence': confidence,
        'rationale': rationale,
        'open_question': open_question,
        'warnings': [],
    }


def build_candidates(project_name, root, units):
    monorepo_roots = {u['path'] for u in units if u['kind'] == 'monorepo_root'}
    candidates = []

    for unit in (u for u in units if u['kind'] == 'ecosystem'):
        path, ecosystem, evidence = unit['path'], unit['ecosystem'], unit['evidence']
        name = _module_name(path, project_name)
        is_nested = path not in ('.', '')
        under_monorepo = any(r == '.' or path == r or path.startswith(r + '/') for r in monorepo_roots)
        command = _scan_command(path, name, project_name)

        if not is_nested:
            candidates.append(_candidate(
                name, path, 'module', command, 0.95,
                f'{evidence}; root of the repository', ecosystem=ecosystem,
            ))
        elif under_monorepo and ecosystem and _looks_independently_released(root, ecosystem, path):
            candidates.append(_candidate(
                name, path, 'linked_module', command, 0.75,
                f'{evidence} in a monorepo workspace; its manifest declares its own '
                'version and is not marked private, suggesting it is published/released '
                'independently - consider scanning it as its own TrustSource project and '
                'linking the release into this project as a Linked Module',
                open_question=(
                    f'Does "{path}" get published/released on its own (npm registry, '
                    'internal registry, separate versioning)? If yes, set it up as its own '
                    'TrustSource project and link its release here instead of scanning it as '
                    'a plain Module.'
                ),
                ecosystem=ecosystem,
            ))
        elif under_monorepo:
            candidates.append(_candidate(
                name, path, 'module', command, 0.9,
                f'{evidence} inside a detected monorepo workspace, so it is a '
                'separately scanned package per ts-scan\'s documented monorepo pattern '
                '(scan each workspace package individually, never the monorepo root)',
                ecosystem=ecosystem,
            ))
        else:
            candidates.append(_candidate(
                name, path, 'module', command, 0.5,
                f'{evidence} in a nested directory with no monorepo marker found - could '
                'be its own module, or just a vendored/example subfolder of the parent module',
                open_question=(
                    f'Is "{path}" released/deployed separately from the rest of the repo? '
                    'If yes, it should be its own Module; if no, fold it into the parent module\'s '
                    'scan instead.'
                ),
                ecosystem=ecosystem,
            ))

    for unit in (u for u in units if u['kind'] == 'dockerfile'):
        dir_path = unit['path'].rsplit('/', 1)[0] if '/' in unit['path'] else '.'
        name = f'{_module_name(dir_path, project_name)}-container'
        candidates.append(_candidate(
            name, unit['path'], 'infrastructure_module', _docker_scan_command(name, project_name),
            0.4,
            f'{unit["evidence"]}; defaulting to Infrastructure Module per TrustSource\'s '
            'container-scanning guidance, but this is only a default, not a judgment',
            open_question=(
                f'Is the image built from "{unit["path"]}" your own deployable service, or '
                'runtime infrastructure (base image, sidecar, etc.)? This changes whether '
                'it should be a Module or an Infrastructure Module.'
            ),
        ))

    for c in candidates:
        c['warnings'] = _naming_warnings(c['name'])
    return candidates


# --- Ecosystem proposals (mirrors src/ts_scan_agent/ecosystem_proposals.py, no-LLM path) ----

ECOSYSTEM_FACTS = {
    'PHP (Composer)':
        'Registry: Packagist. Manifest: composer.json (dependency constraints). '
        'Lockfile: composer.lock (exact resolved versions and hashes).',
    'Ruby (Bundler)':
        'Registry: RubyGems. Manifest: Gemfile (dependency constraints, Ruby DSL). '
        'Lockfile: Gemfile.lock (exact resolved versions and dependency graph).',
    'Swift (Swift Package Manager)':
        'No central registry - dependencies resolve directly from git repository URLs and '
        'tags. Manifest: Package.swift (Swift source). Lockfile: Package.resolved (JSON, '
        'pinned revisions). Prior art: TrustSource previously shipped a standalone SPM plugin, '
        'github.com/TrustSource/ts-spm (deprecated, unmaintained) - its scanner core is just '
        '`swift package show-dependencies --format json` plus a recursive walk of the result, '
        'directly portable to a ts_scan.pm.swift.SwiftScanner.',
    'iOS (CocoaPods)':
        'Registry: the CocoaPods Specs CDN (no TrustSource plugin has ever covered this - '
        'verified against the full github.com/trustsource and github.com/eacg-gmbh org history, '
        '2026-08-26). Manifest: Podfile (Ruby DSL, dependency constraints). '
        'Lockfile: Podfile.lock (YAML-like, exact resolved pod versions) - the more reliable '
        'thing to parse, similar to how other lockfile-based scanners in this codebase work.',
    'Elixir (Hex)':
        'Registry: Hex.pm. Manifest: mix.exs (Elixir source, deps function). '
        'Lockfile: mix.lock.',
    'Haskell (Stack)':
        'Registry: Hackage, via Stackage snapshots. Manifest: package.yaml or *.cabal, plus '
        'stack.yaml (resolver/snapshot pinning). Lockfile: stack.yaml.lock.',
    'Haskell (Cabal)':
        'Registry: Hackage. Manifest: *.cabal. Lockfile (optional): cabal.project.freeze '
        '(pins exact versions).',
    'Perl (CPAN)':
        'Registry: CPAN / MetaCPAN. Manifest: cpanfile. '
        'Lockfile: cpanfile.snapshot (via Carton).',
    'Zig':
        'No central registry - dependencies resolve from git/tarball URLs with content '
        'hashes. Manifest: build.zig (build script) plus build.zig.zon (dependency manifest, '
        'newer Zig versions).',
    'Elm':
        'Registry: package.elm-lang.org. Manifest: elm.json (dependency version ranges, '
        'fully pinned after `elm install`; the compiler enforces semantic versioning). '
        'No separate lockfile.',
}

DISCLOSURE_NOTE = (
    '\n\n---\n*Drafted automatically by [ts-scan-agent]'
    '(https://github.com/TrustSource/ts-scan-agent) from a real repository that hit this '
    'gap. Please review and edit before submitting - this is a starting point, not a '
    'finished spec.*'
)


def build_proposals(units):
    paths_by_ecosystem = {}
    for unit in units:
        if unit['kind'] != 'unsupported_ecosystem' or not unit['ecosystem']:
            continue
        paths = paths_by_ecosystem.setdefault(unit['ecosystem'], [])
        if unit['path'] not in paths:
            paths.append(unit['path'])

    proposals = []
    for ecosystem, paths in paths_by_ecosystem.items():
        body = '\n'.join([
            f'`ts-scan` has no dependency-tree scanner for **{ecosystem}** yet.',
            '',
            f'Found in this repository at: {", ".join(f"`{p}`" for p in paths)}',
            '',
            '### Ecosystem facts',
            ECOSYSTEM_FACTS.get(
                ecosystem,
                'No static facts recorded for this ecosystem yet - please fill in the package '
                'registry, manifest format and lockfile format.',
            ),
            DISCLOSURE_NOTE,
        ])
        proposals.append({
            'ecosystem': ecosystem,
            'manifest_paths': paths,
            'title': f'Add ts-scan support for {ecosystem}',
            'body': body,
            'existing_issue': None,
            'existing_issue_checked': False,
        })
    return proposals


# --- Answers (mirrors src/ts_scan_agent/interview.py apply_answers) --------------------------

DOCKERFILE_ANSWERS = ('module', 'infrastructure_module')
YES_NO_ANSWERS = ('yes', 'no')


class UsageFailure(Exception):
    pass


def load_answers(value):
    # Inline JSON (starts with "{") or a JSON file. Unlike the package's --answers there is no
    # TOML: the standard library has no TOML parser before Python 3.11.
    if value.lstrip().startswith('{'):
        source = 'inline --answers JSON'
        try:
            data = json.loads(value)
        except ValueError as err:
            raise UsageFailure(f'Could not parse {source}: {err}')
    else:
        source = f'--answers file {value}'
        if value.lower().endswith('.toml'):
            raise UsageFailure(
                f'{source}: TOML answers files need the full ts-scan-agent CLI. This script '
                'reads JSON only - pass the answers as inline JSON or a .json file.'
            )
        try:
            with open(value, encoding='utf-8') as fp:
                data = json.load(fp)
        except (OSError, ValueError) as err:
            raise UsageFailure(f'Could not read {source}: {err}')
    if not isinstance(data, dict):
        raise UsageFailure(
            f'{source} must contain a map from candidate path to answer, '
            'e.g. {"tools/helper": "yes", "Dockerfile": "module"}'
        )
    return data


def _parse_answer(candidate, value):
    if candidate['candidate_type'] == 'infrastructure_module':
        if isinstance(value, str) and value in DOCKERFILE_ANSWERS:
            return value
        allowed = DOCKERFILE_ANSWERS
    else:
        if isinstance(value, bool):
            return value
        if isinstance(value, str) and value.lower() in YES_NO_ANSWERS:
            return value.lower() == 'yes'
        allowed = YES_NO_ANSWERS
    raise UsageFailure(
        f'Invalid answer {value!r} for "{candidate["path"]}" - expected one of: {", ".join(allowed)}'
    )


def _resolve(concept, candidate, answer):
    name = candidate['path'].rstrip('/').split('/')[-1]
    ecosystem = candidate['ecosystem']

    if candidate['candidate_type'] == 'infrastructure_module':
        candidate['candidate_type'] = answer
        if answer == 'module':
            candidate['rationale'] = (
                f'{name} found; the user confirmed the image is their own deployable '
                'service, so it is a Module'
            )
        else:
            candidate['rationale'] = (
                f'{name} found; the user confirmed the image is runtime infrastructure '
                '(base image, sidecar, etc.), so it is an Infrastructure Module'
            )
    elif candidate['candidate_type'] == 'linked_module':
        if answer:
            candidate['rationale'] = (
                f'{ecosystem} manifest found in a monorepo workspace; the user '
                'confirmed it is published/released on its own - set it up as its own '
                'TrustSource project and link its release into this project as a Linked Module'
            )
        else:
            candidate['candidate_type'] = 'module'
            candidate['rationale'] = (
                f'{ecosystem} manifest found in a monorepo workspace; the user '
                'confirmed it is not released on its own, so it is scanned as a Module of '
                'this project'
            )
    elif answer:
        candidate['rationale'] = (
            f'{ecosystem} manifest found in a nested directory; the user confirmed '
            'it is released/deployed separately, so it is its own Module'
        )
    else:
        # Belongs to its parent: no scan of its own, so it leaves `candidates`.
        concept['candidates'].remove(candidate)
        concept['folded_into_parent'].append(
            {'name': candidate['name'], 'path': candidate['path'], 'ecosystem': ecosystem}
        )
        return
    candidate['confidence'] = 1.0
    candidate['open_question'] = None


def apply_answers(concept, answers):
    # Several open candidates can share a path (e.g. pyproject.toml and package.json in one
    # directory); they share its question, so the answer applies to all of them.
    pending = {}
    for c in concept['candidates']:
        if c['open_question'] is not None:
            pending.setdefault(c['path'], []).append(c)
    unknown = sorted(p for p in answers if p not in pending)
    if unknown:
        open_paths = ', '.join(f'"{p}"' for p in sorted(pending)) or 'none'
        raise UsageFailure(
            '--answers names path(s) with no open question: '
            f'{", ".join(repr(p) for p in unknown)}. Open questions exist for: {open_paths}'
        )
    parsed = [(c, _parse_answer(c, value)) for path, value in answers.items() for c in pending[path]]
    for candidate, answer in parsed:
        _resolve(concept, candidate, answer)


# --- Render (mirrors src/ts_scan_agent/render.py) --------------------------------------------

LEVEL_CHOICES = ('beginner', 'intermediate', 'expert')
FORMAT_CHOICES = ('markdown', 'json')

_SECTION_TITLES = [
    ('module', 'Modules'),
    ('infrastructure_module', 'Infrastructure Modules'),
    ('linked_module', 'Linked Module candidates'),
]

_NAMING_TIP = (
    '> **Naming tip:** `ts-scan scan`/`upload` have no flag to set the module name - '
    'TrustSource auto-derives it from what ts-scan detects (the package name, or for a '
    'container scan, the image reference *including its tag*, e.g. `node:22-alpine`). '
    'Check the module name TrustSource assigns after the first scan and rename it if it '
    'looks version-y **before** the next release: TrustSource keys a module by name, so a '
    'name that changes with every release creates a brand-new module each time, silently '
    'losing everything attached to the old one - whitelist decisions, muted '
    'vulnerabilities, approval history. (A pinnable module ID for `scan`/`upload` is '
    'planned upstream - see ARCHITECTURE.md.)'
)

_GETTING_STARTED = """## Getting started

New to TrustSource? This report only covers *what* to scan and *which command* to run for
each piece (below). Here's the rest of the journey, in order - steps 1-3 and 5-8 happen in
the TrustSource app itself, not on the command line:

1. **Create a TrustSource account and project**, if you don't have one yet
   ([app.trustsource.io](https://app.trustsource.io)).
2. **Create an API key**: **Administration → Scanners & API Keys** → *Create API Key*. It's
   shown once - copy it somewhere safe, e.g. `export TS_API_KEY="..."` in your shell for now.
3. **Install `ts-scan`**, if you haven't: `pip install ts-scan`.
4. **Run the command(s) below**, one per unit listed in this report.
5. **Open the module in the app.** It's created automatically on first upload - you don't
   create it by hand. Give it a minute, then check its **Components** tab.
6. **Look at the traffic-light status.** Yellow or red on a first scan is normal - it means
   there's something to look at (a license, a vulnerability), not that something broke.
7. **Ask your project or compliance manager for an approval** once the status looks good
   enough to ship - that's a deliberate governance step, not automatic.
8. **Create a release** from the approved state. This is what TrustSource keeps watching for
   new vulnerabilities going forward, and what you'd hand a customer as an SBOM.

Full walkthrough: [ts-scan/recipes/01-first-module-to-sbom](https://trustsource.github.io/ts-scan).

## Concepts used in this report

- **Module** - one deployable piece of your software (a service, a library, a container
  image) that gets its own bill of materials and its own approval/release history.
- **Infrastructure Module** - a runtime dependency you don't build yourself (a database, a
  message broker, a base image) - tracked the same way, kept conceptually separate from
  what your team actually ships.
- **Linked Module** - when a Module has its own release cycle (e.g. a shared library with
  its own version), that release can be linked into another project instead of scanned a
  second time there.
"""


def _render_candidate(c, level):
    lines = [f'### `{c["path"]}` — {c["name"]}']
    if level == 'expert':
        lines.append('- Recommended command:')
        lines.append(f'  ```bash\n  {c["ts_scan_command"]}\n  ```')
        return '\n'.join(lines)
    if c['ecosystem']:
        lines.append(f'- Ecosystem: {c["ecosystem"]}')
    lines.append(f'- Confidence: {c["confidence"]:.0%}')
    lines.append(f'- Rationale: {c["rationale"]}')
    lines.append('- Recommended command:')
    lines.append(f'  ```bash\n  {c["ts_scan_command"]}\n  ```')
    for warning in c['warnings']:
        lines.append(f'- ⚠️ **Naming:** {warning}')
    if c['open_question']:
        lines.append(f'- ⚠️ **Open question:** {c["open_question"]}')
    return '\n'.join(lines)


def _render_ecosystem_proposal(p, issue_repo, level):
    lines = [f'### {p["ecosystem"]}']
    lines.append(f'- Found at: {", ".join(f"`{path}`" for path in p["manifest_paths"])}')
    title_arg = shlex.quote(p['title'])
    body_arg = shlex.quote(p['body'])
    if not p['existing_issue_checked']:
        lines.append(
            f'- Not checked for an existing issue. Search first: '
            f'`gh issue list --repo {issue_repo} --search {shlex.quote(p["ecosystem"])} --state all`'
        )
    if level == 'expert':
        lines.append(f'  ```bash\n  gh issue create --repo {issue_repo} --title {title_arg} '
                     f'--body {body_arg} --label enhancement\n  ```')
        return '\n'.join(lines)
    if p['existing_issue_checked']:
        lines.append('- No existing issue found for this ecosystem.')
    lines.append('')
    lines.append(f'**Draft title:** {p["title"]}')
    lines.append('')
    lines.append(p['body'])
    lines.append('')
    lines.append(
        f'File it yourself with:\n'
        f'  ```bash\n'
        f'  gh issue create --repo {issue_repo} --title {title_arg} --body {body_arg} '
        f'--label enhancement\n'
        f'  ```\n'
        f'  or re-run the `ts-scan-agent` CLI with `--file-issues` to be walked through '
        f'review + filing.'
    )
    return '\n'.join(lines)


def render_markdown(concept, units, issue_repo, level):
    lines = [f'# TrustSource Scan Concept: {concept["project_name"]}', '',
             f'Generated for `{concept["source_path"]}`.', '']

    if level == 'beginner':
        lines.append(_GETTING_STARTED)
        lines.append('')

    if level != 'expert':
        lines.append(
            f'Create one TrustSource project (`{concept["project_name"]}`) and add the following '
            'units to it:'
        )
        lines.append('')
        lines.append(_NAMING_TIP)
        lines.append('')

    for candidate_type, title in _SECTION_TITLES:
        items = [c for c in concept['candidates'] if c['candidate_type'] == candidate_type]
        if not items:
            continue
        lines.append(f'## {title}')
        lines.append('')
        for c in sorted(items, key=lambda c: c['path']):
            lines.append(_render_candidate(c, level))
            lines.append('')

    if concept['folded_into_parent']:
        lines.append('## Folded into parent modules')
        lines.append('')
        if level != 'expert':
            lines.append(
                'You said these belong to their parent module, so they get no scan of their '
                'own:'
            )
            lines.append('')
        for f in sorted(concept['folded_into_parent'], key=lambda f: (f['path'], f['ecosystem'] or '')):
            lines.append(f'- `{f["path"]}` - {f["name"]}' + (f' ({f["ecosystem"]})' if f['ecosystem'] else ''))
        lines.append('')

    open_questions = [c for c in concept['candidates'] if c['open_question'] is not None]
    if open_questions:
        lines.append('## Still open')
        lines.append('')
        if level == 'expert':
            for c in open_questions:
                lines.append(f'- `{c["path"]}`')
        else:
            lines.append(
                'The following items could not be classified with confidence and were not '
                'resolved (pass `--answers` mapping each path below to its answer to resolve '
                'them; the `ts-scan-agent` CLI can also ask them interactively):'
            )
            lines.append('')
            for c in open_questions:
                lines.append(f'- `{c["path"]}` — {c["open_question"]}')
        lines.append('')

    ci_units = [u for u in units if u['kind'] == 'ci_config']
    if ci_units:
        lines.append('## Detected CI/CD configuration')
        lines.append('')
        if level != 'expert':
            lines.append(
                'Wire the recommended `ts-scan` commands above into these pipelines so scans '
                'run on every build:'
            )
            lines.append('')
        for u in ci_units:
            lines.append(f'- `{u["path"]}`')
        lines.append('')

    if any(u['kind'] == 'monorepo_root' for u in units) and level != 'expert':
        lines.append('## Monorepo markers detected')
        lines.append('')
        lines.append(
            'ts-scan has no built-in monorepo mode - scan each workspace package individually '
            '(as reflected in the Modules above), never the monorepo root.'
        )
        lines.append('')

    if concept['ecosystem_proposals']:
        lines.append('## Unsupported ecosystems detected')
        lines.append('')
        if level != 'expert':
            lines.append(
                'ts-scan has no scanner for these yet. A proposal for each is drafted below - '
                'review it (nothing is ever filed on GitHub automatically):'
            )
            lines.append('')
        for p in concept['ecosystem_proposals']:
            lines.append(_render_ecosystem_proposal(p, issue_repo, level))
            lines.append('')

    return '\n'.join(lines)


def render_json(concept):
    return json.dumps(concept, indent=2, ensure_ascii=False)


# --- CLI -------------------------------------------------------------------------------------

def build_parser():
    parser = argparse.ArgumentParser(
        prog='scan_concept.py',
        description='Proposes a TrustSource scan concept for a repository (dependency-free '
                    'port of ts-scan-agent for its Agent Skill).',
    )
    parser.add_argument('--version', action='version', version=f'ts-scan-agent skill {VERSION}')
    sub = parser.add_subparsers(dest='command')
    analyze = sub.add_parser('analyze', help='Analyze a repository')
    analyze.add_argument('path')
    analyze.add_argument('--level', choices=LEVEL_CHOICES, default='beginner')
    analyze.add_argument('--project')
    analyze.add_argument('--answers', metavar='FILE|JSON',
                         help='Inline JSON object or JSON file mapping candidate path to answer')
    analyze.add_argument('--format', choices=FORMAT_CHOICES, default='markdown')
    analyze.add_argument('--propose-issues', dest='propose_issues', action='store_true', default=True)
    analyze.add_argument('--no-propose-issues', dest='propose_issues', action='store_false')
    analyze.add_argument('--issue-repo', default='trustsource/ts-scan')
    analyze.add_argument('-o', '--output')
    return parser


def main(argv=None):
    # The report contains non-ASCII (em dash, warning sign); don't die on a cp1252 console.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8')

    args = build_parser().parse_args(argv)
    if args.command != 'analyze':
        build_parser().print_help(sys.stderr)
        return 2

    try:
        root = os.path.realpath(args.path)
        if not os.path.isdir(root):
            raise UsageFailure(f'Directory "{args.path}" does not exist.')
        answers = load_answers(args.answers) if args.answers else None
        project_name = args.project or os.path.basename(root)

        print(f'Scanning {root} ...', file=sys.stderr)
        units = scan_inventory(root)
        concept = {
            'project_name': project_name,
            'source_path': root,
            'candidates': build_candidates(project_name, root, units),
            'folded_into_parent': [],
            'ecosystem_proposals': [],
        }
        if answers is not None:
            apply_answers(concept, answers)
        if args.propose_issues:
            concept['ecosystem_proposals'] = build_proposals(units)
    except UsageFailure as err:
        print(f'Error: {err}', file=sys.stderr)
        return 1

    if args.format == 'json':
        report = render_json(concept)
    else:
        report = render_markdown(concept, units, args.issue_repo, args.level)

    if args.output:
        with open(args.output, 'w', encoding='utf-8') as fp:
            fp.write(report)
        print(f'Wrote scan concept to {args.output}', file=sys.stderr)
    else:
        sys.stdout.write(report + '\n')
    return 0


if __name__ == '__main__':
    sys.exit(main())
