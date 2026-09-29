import json

from pathlib import Path

from click.testing import CliRunner

from ts_scan_agent import cli
from ts_scan_agent.cli import _parse_edited_proposal, start


def test_parses_clean_title_line():
    title, body = _parse_edited_proposal('Title: Add support for X\n\nSome body text.')
    assert title == 'Add support for X'
    assert body == 'Some body text.'


def test_tolerates_leading_whitespace_before_title_marker():
    title, body = _parse_edited_proposal(' Title: Add support for X\n\nBody.')
    assert title == 'Add support for X'
    assert body == 'Body.'


def test_tolerates_blank_lines_before_title_marker():
    title, body = _parse_edited_proposal('\n\nTitle: Add support for X\n\nBody.')
    assert title == 'Add support for X'
    assert body == 'Body.'


def test_falls_back_to_none_title_when_marker_missing_rather_than_leaking_into_body():
    title, body = _parse_edited_proposal('Just a rewritten body, no title line.')
    assert title is None
    assert body == 'Just a rewritten body, no title line.'


def test_falls_back_when_first_nonblank_line_is_not_a_title_line():
    edited = 'Some other first line\nTitle: This should NOT be picked up\n\nBody.'
    title, body = _parse_edited_proposal(edited)
    assert title is None
    assert body == edited


def _run(runner, args, no_config_path):
    return runner.invoke(start, ['--config', str(no_config_path), *args])


def test_default_level_is_beginner_with_no_settings_file(tmp_path: Path):
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path) as cwd:
        (Path(cwd) / 'package.json').write_text('{}')
        result = _run(runner, ['analyze', '.', '--llm', 'none', '--non-interactive'],
                       Path(cwd) / 'no-such-config.toml')

    assert result.exit_code == 0, result.output
    assert '## Getting started' in result.output


def test_user_config_overrides_the_default_level(tmp_path: Path):
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path) as cwd:
        (Path(cwd) / 'package.json').write_text('{}')
        config_path = Path(cwd) / 'config.toml'
        config_path.write_text('level = "expert"\n')
        result = _run(runner, ['analyze', '.', '--llm', 'none', '--non-interactive'], config_path)

    assert result.exit_code == 0, result.output
    assert '## Getting started' not in result.output


def test_project_config_in_cwd_overrides_user_config(tmp_path: Path):
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path) as cwd:
        (Path(cwd) / 'package.json').write_text('{}')
        (Path(cwd) / '.ts-scan-agent.toml').write_text('level = "expert"\n')
        user_config_path = Path(cwd) / 'user-config.toml'
        user_config_path.write_text('level = "beginner"\n')
        result = _run(runner, ['analyze', '.', '--llm', 'none', '--non-interactive'], user_config_path)

    assert result.exit_code == 0, result.output
    assert '## Getting started' not in result.output


def test_explicit_cli_flag_overrides_settings_files(tmp_path: Path):
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path) as cwd:
        (Path(cwd) / 'package.json').write_text('{}')
        (Path(cwd) / '.ts-scan-agent.toml').write_text('level = "expert"\n')
        config_path = Path(cwd) / 'user-config.toml'
        result = _run(
            runner,
            ['analyze', '.', '--llm', 'none', '--non-interactive', '--level', 'beginner'],
            config_path,
        )

    assert result.exit_code == 0, result.output
    assert '## Getting started' in result.output


def _write_fixture_repo(root: Path) -> None:
    # The repro from issue #1: a root package, an ambiguous nested one and a Dockerfile.
    (root / 'package.json').write_text('{"name": "root"}')
    (root / 'tools' / 'helper').mkdir(parents=True)
    (root / 'tools' / 'helper' / 'package.json').write_text('{"name": "helper"}')
    (root / 'Dockerfile').write_text('FROM node:22\n')


def _analyze_fixture(tmp_path: Path, args, answers=None, answers_name='answers.json'):
    runner = CliRunner(mix_stderr=False)
    with runner.isolated_filesystem(temp_dir=tmp_path) as cwd:
        _write_fixture_repo(Path(cwd))
        if answers is not None:
            (Path(cwd) / answers_name).write_text(answers)
            args = [*args, '--answers', answers_name]
        return _run(runner, ['analyze', '.', '--llm', 'none', '--no-propose-issues', *args],
                    Path(cwd) / 'no-such-config.toml')


def _candidates_by_path(result):
    return {c['path']: c for c in json.loads(result.stdout)['candidates']}


def test_no_tty_falls_back_to_non_interactive_with_a_warning(tmp_path: Path):
    # CliRunner's stdin is not a TTY - same as an agent's shell or `< /dev/null`.
    result = _analyze_fixture(tmp_path, [])

    assert result.exit_code == 0, result.stderr
    assert 'stdin is not a terminal' in result.stderr
    assert '## Still open' in result.stdout
    assert '`tools/helper`' in result.stdout
    assert '[Y/n]' not in result.stdout


def test_explicit_non_interactive_does_not_warn_about_tty(tmp_path: Path):
    result = _analyze_fixture(tmp_path, ['--non-interactive'])

    assert result.exit_code == 0, result.stderr
    assert 'stdin is not a terminal' not in result.stderr


def test_still_open_mentions_answers_flag(tmp_path: Path):
    result = _analyze_fixture(tmp_path, ['--non-interactive', '--level', 'intermediate'])

    assert 'pass `--answers` mapping each path' in result.stdout


def test_format_json_dumps_the_scan_concept(tmp_path: Path):
    result = _analyze_fixture(tmp_path, ['--non-interactive', '--format', 'json'])

    assert result.exit_code == 0, result.stderr
    data = json.loads(result.stdout)
    assert set(data) == {'project_name', 'source_path', 'candidates', 'folded_into_parent',
                         'ecosystem_proposals'}
    assert data['folded_into_parent'] == []
    candidates = _candidates_by_path(result)
    assert set(candidates) == {'.', 'tools/helper', 'Dockerfile'}
    for c in candidates.values():
        assert {'path', 'candidate_type', 'confidence', 'rationale', 'open_question',
                'ts_scan_command', 'warnings'} <= set(c)
    assert candidates['.']['open_question'] is None
    assert candidates['tools/helper']['open_question']
    assert candidates['Dockerfile']['ts_scan_command'].startswith('ts-scan scan --use-syft')


def test_answers_file_resolves_open_questions(tmp_path: Path):
    result = _analyze_fixture(
        tmp_path, ['--format', 'json'],
        answers='{"tools/helper": "yes", "Dockerfile": "module"}',
    )

    assert result.exit_code == 0, result.stderr
    assert 'stdin is not a terminal' not in result.stderr
    candidates = _candidates_by_path(result)
    assert candidates['Dockerfile']['candidate_type'] == 'module'
    assert candidates['Dockerfile']['open_question'] is None
    assert candidates['tools/helper']['open_question'] is None
    assert candidates['tools/helper']['confidence'] == 1.0


def test_answers_replace_the_stale_rationale(tmp_path: Path):
    # Mapping's rationale describes the doubt ("defaulting to Infrastructure Module", "could be
    # vendored"); once answered it must say what the user confirmed instead.
    result = _analyze_fixture(
        tmp_path, ['--format', 'json'],
        answers='{"tools/helper": "yes", "Dockerfile": "module"}',
    )

    candidates = _candidates_by_path(result)
    dockerfile = candidates['Dockerfile']['rationale']
    assert 'defaulting' not in dockerfile
    assert 'confirmed the image is their own deployable service' in dockerfile
    helper = candidates['tools/helper']['rationale']
    assert 'vendored' not in helper
    assert 'confirmed it is released/deployed separately' in helper


def test_answers_no_on_nested_package_folds_it_into_the_parent(tmp_path: Path):
    result = _analyze_fixture(tmp_path, ['--format', 'json'], answers='{"tools/helper": false}')

    assert result.exit_code == 0, result.stderr
    data = json.loads(result.stdout)
    candidates = _candidates_by_path(result)
    # No scan of its own: gone from candidates, so its ts-scan command is gone too.
    assert 'tools/helper' not in candidates
    assert data['folded_into_parent'] == [
        {'name': 'helper', 'path': 'tools/helper', 'ecosystem': 'Node'},
    ]
    # Unanswered questions stay open instead of being guessed.
    assert candidates['Dockerfile']['open_question']


def test_folded_package_is_listed_without_a_command(tmp_path: Path):
    result = _analyze_fixture(
        tmp_path, ['--level', 'intermediate'], answers='{"tools/helper": "no"}',
    )

    assert result.exit_code == 0, result.stderr
    assert '## Folded into parent modules' in result.stdout
    assert '- `tools/helper` - helper' in result.stdout
    assert 'ts-scan scan tools/helper' not in result.stdout


def test_answers_file_can_be_toml(tmp_path: Path):
    result = _analyze_fixture(
        tmp_path, ['--format', 'json'],
        answers='"tools/helper" = "yes"\nDockerfile = "infrastructure_module"\n',
        answers_name='answers.toml',
    )

    assert result.exit_code == 0, result.stderr
    candidates = _candidates_by_path(result)
    assert candidates['Dockerfile']['candidate_type'] == 'infrastructure_module'
    assert candidates['Dockerfile']['open_question'] is None


def test_answers_with_unknown_path_fails(tmp_path: Path):
    result = _analyze_fixture(tmp_path, [], answers='{"no/such/path": "yes"}')

    assert result.exit_code != 0
    assert "'no/such/path'" in result.stderr
    assert '"tools/helper"' in result.stderr
    assert result.stdout == ''


def test_answers_for_candidate_without_open_question_fails(tmp_path: Path):
    result = _analyze_fixture(tmp_path, [], answers='{".": "yes"}')

    assert result.exit_code != 0
    assert 'no open question' in result.stderr


def test_answers_with_invalid_value_fails(tmp_path: Path):
    result = _analyze_fixture(tmp_path, [], answers='{"Dockerfile": "yes"}')

    assert result.exit_code != 0
    assert 'module, infrastructure_module' in result.stderr


def test_answers_file_must_be_a_map(tmp_path: Path):
    result = _analyze_fixture(tmp_path, [], answers='["tools/helper"]')

    assert result.exit_code != 0
    assert 'must contain a map' in result.stderr


def test_interview_prompts_go_to_stderr_not_the_report(tmp_path: Path, monkeypatch):
    monkeypatch.setattr('ts_scan_agent.cli._stdin_is_tty', lambda: True)
    runner = CliRunner(mix_stderr=False)
    with runner.isolated_filesystem(temp_dir=tmp_path) as cwd:
        _write_fixture_repo(Path(cwd))
        result = runner.invoke(
            start,
            ['--config', str(Path(cwd) / 'none.toml'), 'analyze', '.', '--llm', 'none',
             '--no-propose-issues', '--format', 'json'],
            input='n\nmodule\n',
        )

    assert result.exit_code == 0, result.stderr
    assert 'need your input' in result.stderr
    assert '[Y/n]' in result.stderr
    assert '[Y/n]' not in result.stdout and 'need your input' not in result.stdout
    # CliRunner echoes the simulated keystrokes into stdout (a real terminal echoes them to
    # the TTY instead), so parse the report from where the JSON starts.
    report = json.loads(result.stdout[result.stdout.index('{'):])
    candidates = {c['path']: c for c in report['candidates']}
    assert candidates['Dockerfile']['candidate_type'] == 'module'
    assert 'tools/helper' not in candidates
    assert [f['path'] for f in report['folded_into_parent']] == ['tools/helper']


def test_answers_can_be_inline_json(tmp_path: Path):
    result = _analyze_fixture(
        tmp_path, ['--format', 'json', '--answers', '{"Dockerfile": "module", "tools/helper": "yes"}'],
    )

    assert result.exit_code == 0, result.stderr
    candidates = _candidates_by_path(result)
    assert candidates['Dockerfile']['candidate_type'] == 'module'
    assert candidates['tools/helper']['open_question'] is None


def test_invalid_inline_answers_fail(tmp_path: Path):
    result = _analyze_fixture(tmp_path, ['--answers', '{"Dockerfile": '])

    assert result.exit_code != 0
    assert 'Could not parse inline --answers JSON' in result.stderr


def test_missing_answers_file_fails(tmp_path: Path):
    result = _analyze_fixture(tmp_path, ['--answers', 'no-such-file.json'])

    assert result.exit_code != 0
    assert 'Could not read --answers file no-such-file.json' in result.stderr


def _linked_concept():
    from ts_scan_agent.model import Candidate, ScanConcept
    return ScanConcept(project_name='p', source_path='/p', candidates=[Candidate(
        name='lib', path='packages/lib', candidate_type='linked_module', ecosystem='Node',
        ts_scan_command='ts-scan scan packages/lib -o lib.json', confidence=0.75,
        rationale='... consider scanning it as its own TrustSource project ...',
        open_question='Does "packages/lib" get published/released on its own?',
    )])


def test_linked_module_answered_no_drops_the_linking_advice():
    from ts_scan_agent.interview import apply_answers
    concept = _linked_concept()

    apply_answers(concept, {'packages/lib': 'no'})

    [c] = concept.candidates
    assert c.candidate_type == 'module'
    assert 'its own TrustSource project' not in c.rationale
    assert 'not released on its own, so it is scanned as a Module' in c.rationale


def test_linked_module_answered_yes_keeps_it_linked():
    from ts_scan_agent.interview import apply_answers
    concept = _linked_concept()

    apply_answers(concept, {'packages/lib': 'yes'})

    [c] = concept.candidates
    assert c.candidate_type == 'linked_module'
    assert c.open_question is None
    assert 'confirmed it is published/released on its own' in c.rationale


def test_closed_stdin_counts_as_no_tty(monkeypatch):
    class ClosedStdin:
        def isatty(self):
            raise ValueError('I/O operation on closed file')

    monkeypatch.setattr(cli.sys, 'stdin', ClosedStdin())

    assert cli._stdin_is_tty() is False
