"""The skill's bundled scripts (skills/ts-scan-agent/scripts/) are dependency-free ports of this
package's --llm none pipeline. These tests run the package and both ports on the same fixtures
and require identical reports, so a change to detection, rules or wording in one place fails
CI until the others follow."""

import json
import re
import shutil
import subprocess
import sys

from pathlib import Path

import pytest

from ts_scan_agent.inventory import scan_inventory
from ts_scan_agent.mapping import build_candidates, _scan_command, _docker_scan_command
from ts_scan_agent.ecosystem_proposals import build_proposals
from ts_scan_agent.interview import apply_answers, AnswersError
from ts_scan_agent.model import ScanConcept
from ts_scan_agent.render import render_markdown, render_json

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = REPO_ROOT / 'skills' / 'ts-scan-agent' / 'scripts'
PY_SCRIPT = SCRIPTS / 'scan_concept.py'
JS_SCRIPT = SCRIPTS / 'scan_concept.mjs'
MANUAL_MD = REPO_ROOT / 'skills' / 'ts-scan-agent' / 'references' / 'manual.md'

NODE = shutil.which('node')

RUNNERS = [
    pytest.param([sys.executable, str(PY_SCRIPT)], id='python'),
    pytest.param(
        [NODE or 'node', str(JS_SCRIPT)], id='node',
        marks=pytest.mark.skipif(NODE is None, reason='node not installed'),
    ),
]


def _write(root: Path, rel: str, content: str = '') -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def _issue_fixture(root: Path) -> None:
    _write(root, 'package.json', '{"name": "root"}')
    _write(root, 'tools/helper/package.json', '{"name": "helper"}')
    _write(root, 'Dockerfile', 'FROM node:22\n')


def _monorepo_fixture(root: Path) -> None:
    _write(root, 'package.json', '{"name": "mono", "workspaces": ["packages/*"]}')
    _write(root, 'packages/published/package.json', '{"name": "p", "version": "1.2.0"}')
    _write(root, 'packages/internal/package.json', '{"name": "i", "version": "1.0.0", "private": true}')
    _write(root, 'packages/noversion/package.json', '{"name": "n"}')
    _write(root, 'packages/api-1.4.2/package.json', '{"name": "versiony"}')
    _write(root, 'services/api/Dockerfile.prod', 'FROM python:3.12\n')
    _write(root, 'services/api/pyproject.toml', '[project]\nname = "api"\n')
    _write(root, '.github/workflows/ci.yml', 'on: push\n')
    _write(root, '.github/workflows/release.yaml', 'on: push\n')
    _write(root, '.gitlab-ci.yml', 'stages: []\n')
    _write(root, 'Jenkinsfile', '')
    _write(root, 'pnpm-workspace.yaml', 'packages: []\n')


def _mixed_fixture(root: Path) -> None:
    _write(root, '.gitignore', '\n'.join([
        '# comment',
        'generated/',
        '*.log',
        '/out',
        'docs/**/examples',
        'sub/dir',
        '!keep.log',
        'secret?.txt',
        '[Tt]emp/',
        '[z-a]',
        '',
    ]))
    _write(root, 'go.mod', 'module example.com/x\n')
    _write(root, 'generated/package.json', '{}')
    _write(root, 'out/Dockerfile', 'FROM scratch\n')
    _write(root, 'docs/a/examples/pom.xml', '<project/>')
    _write(root, 'docs/a/real/pom.xml', '<project/>')
    _write(root, 'sub/dir/Cargo.toml', '[package]\n')
    _write(root, 'sub/other/Cargo.toml', '[package]\n')
    _write(root, 'Temp/pubspec.yaml', 'name: t\n')
    _write(root, 'app/pubspec.yaml', 'name: app\n')
    _write(root, 'php/composer.json', '{}')
    _write(root, 'ruby/Gemfile', '')
    _write(root, 'ruby2/Gemfile', '')
    _write(root, 'hs/thing.cabal', '')
    _write(root, 'dotnet/App.csproj', '<Project/>')
    _write(root, 'dotnet-sln/All.sln', '')
    _write(root, 'gradle-kts/build.gradle.kts', '')
    _write(root, 'mixed/composer.json', '{}')
    _write(root, 'mixed/setup.py', '')
    _write(root, 'node_modules/dep/package.json', '{}')
    _write(root, 'a/b/c/d/e/f/package.json', '{}')
    _write(root, 'a/b/c/d/e/f/g/package.json', '{}')
    _write(root, 'build.zig', '')


def _empty_fixture(root: Path) -> None:
    _write(root, 'README.md', 'nothing to scan')


FIXTURES = {
    'issue': _issue_fixture,
    'monorepo': _monorepo_fixture,
    'mixed': _mixed_fixture,
    'empty': _empty_fixture,
}


@pytest.fixture(params=sorted(FIXTURES))
def repo(request, tmp_path: Path) -> Path:
    root = tmp_path / f'{request.param}-repo'
    root.mkdir()
    FIXTURES[request.param](root)
    return root


def _package_concept(root: Path, answers=None, propose_issues=True):
    root = root.resolve()
    units = scan_inventory(root)
    concept = ScanConcept(project_name=root.name, source_path=str(root),
                          candidates=build_candidates(root.name, root, units))
    if answers is not None:
        apply_answers(concept, answers)
    if propose_issues:
        # No gh duplicate search here: the scripts leave that to the agent (SKILL.md step 5).
        concept.ecosystem_proposals = build_proposals(units)
    return concept, units


def _run(runner, root: Path, *args):
    return subprocess.run(
        [*runner, 'analyze', '.', *args],
        cwd=root, capture_output=True, text=True, encoding='utf-8',
    )


@pytest.mark.parametrize('runner', RUNNERS)
@pytest.mark.parametrize('level', ['beginner', 'intermediate', 'expert'])
def test_markdown_matches_package_byte_for_byte(runner, repo: Path, level: str):
    concept, units = _package_concept(repo)
    expected = render_markdown(concept, units, level=level) + '\n'

    result = _run(runner, repo, '--level', level)

    assert result.returncode == 0, result.stderr
    assert result.stdout == expected


@pytest.mark.parametrize('runner', RUNNERS)
def test_json_matches_package(runner, repo: Path):
    concept, _ = _package_concept(repo)

    result = _run(runner, repo, '--format', 'json')

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == json.loads(render_json(concept))


@pytest.mark.parametrize('runner', RUNNERS)
def test_no_propose_issues_matches_package(runner, tmp_path: Path):
    root = tmp_path / 'mixed-repo'
    root.mkdir()
    _mixed_fixture(root)
    concept, _ = _package_concept(root, propose_issues=False)

    result = _run(runner, root, '--format', 'json', '--no-propose-issues')

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == json.loads(render_json(concept))


@pytest.mark.parametrize('runner', RUNNERS)
@pytest.mark.parametrize('answers', [
    {'tools/helper': 'yes', 'Dockerfile': 'module'},
    {'tools/helper': False},
    {'Dockerfile': 'infrastructure_module', 'tools/helper': 'NO'},
])
def test_answers_match_package(runner, tmp_path: Path, answers):
    root = tmp_path / 'issue-repo'
    root.mkdir()
    _issue_fixture(root)
    answers_file = tmp_path / 'answers.json'
    answers_file.write_text(json.dumps(answers))
    concept, units = _package_concept(root, answers=answers)

    result = _run(runner, root, '--answers', str(answers_file), '--level', 'intermediate')

    assert result.returncode == 0, result.stderr
    assert result.stdout == render_markdown(concept, units, level='intermediate') + '\n'


@pytest.mark.parametrize('runner', RUNNERS)
@pytest.mark.parametrize('level', ['beginner', 'intermediate', 'expert'])
@pytest.mark.parametrize('answers', [
    {'packages/published': 'no', 'services/api/Dockerfile.prod': 'module'},
    {'packages/published': 'yes', 'services/api/Dockerfile.prod': 'infrastructure_module'},
])
def test_linked_module_answers_match_package(runner, tmp_path: Path, level, answers):
    root = tmp_path / 'monorepo-repo'
    root.mkdir()
    _monorepo_fixture(root)
    concept, units = _package_concept(root, answers=answers)

    md = _run(runner, root, '--answers', json.dumps(answers), '--level', level)
    js = _run(runner, root, '--answers', json.dumps(answers), '--format', 'json')

    assert md.returncode == 0, md.stderr
    assert md.stdout == render_markdown(concept, units, level=level) + '\n'
    assert json.loads(js.stdout) == json.loads(render_json(concept))


@pytest.mark.parametrize('runner', RUNNERS)
@pytest.mark.parametrize('level', ['beginner', 'intermediate', 'expert'])
def test_folded_package_matches_package(runner, tmp_path: Path, level):
    root = tmp_path / 'issue-repo'
    root.mkdir()
    _issue_fixture(root)
    answers = {'tools/helper': 'no', 'Dockerfile': 'module'}
    concept, units = _package_concept(root, answers=answers)
    assert [f.path for f in concept.folded_into_parent] == ['tools/helper']

    result = _run(runner, root, '--answers', json.dumps(answers), '--level', level)

    assert result.returncode == 0, result.stderr
    assert result.stdout == render_markdown(concept, units, level=level) + '\n'
    assert 'ts-scan scan tools/helper' not in result.stdout


@pytest.mark.parametrize('runner', RUNNERS)
@pytest.mark.parametrize('answers, message', [
    ({'no/such/path': 'yes'}, "'no/such/path'"),
    ({'.': 'yes'}, 'no open question'),
    ({'Dockerfile': 'yes'}, 'module, infrastructure_module'),
    ({'tools/helper': 'maybe'}, 'yes, no'),
    (['tools/helper'], 'must contain a map'),
])
def test_invalid_answers_fail_like_the_package(runner, tmp_path: Path, answers, message):
    root = tmp_path / 'issue-repo'
    root.mkdir()
    _issue_fixture(root)
    answers_file = tmp_path / 'answers.json'
    answers_file.write_text(json.dumps(answers))

    if isinstance(answers, dict):
        with pytest.raises(AnswersError, match=re.escape(message)):
            _package_concept(root, answers=answers)

    result = _run(runner, root, '--answers', str(answers_file))

    assert result.returncode == 1
    assert message in result.stderr
    assert result.stdout == ''


@pytest.mark.parametrize('runner', RUNNERS)
def test_unknown_flag_is_rejected(runner, tmp_path: Path):
    result = _run(runner, tmp_path, '--llm', 'none')

    assert result.returncode == 2


@pytest.mark.parametrize('runner', RUNNERS)
def test_output_file(runner, tmp_path: Path):
    root = tmp_path / 'issue-repo'
    root.mkdir()
    _issue_fixture(root)
    concept, units = _package_concept(root)
    out = tmp_path / 'report.md'

    result = _run(runner, root, '-o', str(out))

    assert result.returncode == 0, result.stderr
    assert result.stdout == ''
    assert out.read_text(encoding='utf-8') == render_markdown(concept, units, level='beginner')


def test_manual_mode_templates_match_mapping():
    # Manual mode has the agent fill in templates by hand, so they must be exactly the
    # strings mapping.py produces (which test_ts_scan_reference.py checks against ts-scan).
    blocks = re.findall(r'```\n(ts-scan [^\n]*)\n```', MANUAL_MD.read_text())
    assert blocks == [
        _scan_command('TARGET', 'NAME', 'PROJECT'),
        _docker_scan_command('NAME', 'PROJECT'),
    ]


@pytest.mark.parametrize('runner', RUNNERS)
def test_inline_answers_match_package(runner, tmp_path: Path):
    root = tmp_path / 'issue-repo'
    root.mkdir()
    _issue_fixture(root)
    answers = {'tools/helper': 'no', 'Dockerfile': 'module'}
    concept, units = _package_concept(root, answers=answers)

    result = _run(runner, root, '--answers', json.dumps(answers), '--level', 'expert')

    assert result.returncode == 0, result.stderr
    assert result.stdout == render_markdown(concept, units, level='expert') + '\n'


@pytest.mark.parametrize('runner', RUNNERS)
@pytest.mark.parametrize('value, message', [
    ('{"Dockerfile": ', 'Could not parse inline --answers JSON'),
    ('no-such-file.json', 'Could not read --answers file no-such-file.json'),
])
def test_unreadable_answers_fail(runner, tmp_path: Path, value, message):
    root = tmp_path / 'issue-repo'
    root.mkdir()
    _issue_fixture(root)

    result = _run(runner, root, '--answers', value)

    assert result.returncode == 1
    assert message in result.stderr


@pytest.mark.parametrize('runner', RUNNERS)
def test_toml_answers_file_fails_with_a_clear_message(runner, tmp_path: Path):
    root = tmp_path / 'issue-repo'
    root.mkdir()
    _issue_fixture(root)
    answers_file = tmp_path / 'answers.toml'
    answers_file.write_text('"tools/helper" = "yes"\n')

    result = _run(runner, root, '--answers', str(answers_file))

    assert result.returncode == 1
    assert 'reads JSON only' in result.stderr


@pytest.mark.parametrize('runner', RUNNERS)
@pytest.mark.parametrize('answer', ['yes', 'no'])
def test_answer_applies_to_every_open_candidate_at_the_path(runner, tmp_path: Path, answer):
    # Two manifests in one nested directory: two open candidates with the same path.
    root = tmp_path / 'dup-repo'
    _write(root, 'pyproject.toml', '[project]\nname = "root"\n')
    _write(root, 'sub/package.json', '{"name": "sub"}')
    _write(root, 'sub/pyproject.toml', '[project]\nname = "sub"\n')
    answers = {'sub': answer}
    concept, units = _package_concept(root, answers=answers)
    assert not concept.low_confidence_candidates
    assert len(concept.folded_into_parent) == (2 if answer == 'no' else 0)

    md = _run(runner, root, '--answers', json.dumps(answers), '--level', 'intermediate')
    js = _run(runner, root, '--answers', json.dumps(answers), '--format', 'json')

    assert md.returncode == 0, md.stderr
    assert md.stdout == render_markdown(concept, units, level='intermediate') + '\n'
    assert json.loads(js.stdout) == json.loads(render_json(concept))
