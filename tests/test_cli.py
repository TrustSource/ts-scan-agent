from pathlib import Path

from click.testing import CliRunner

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
