import pytest

from ts_scan_agent.ts_scan_reference import load_reference, extract_flags, subcommand_used
from ts_scan_agent.mapping import _scan_command, _docker_scan_command


@pytest.fixture(scope='module')
def reference():
    return load_reference()


def _assert_all_flags_known(command_text, reference):
    subcommands = list(reference.keys())
    for line in command_text.split('&&'):
        line = line.strip()
        sub = subcommand_used(line, subcommands)
        assert sub is not None, f'no known ts-scan subcommand found in: {line!r}'
        known = reference[sub].known_flags()
        used = extract_flags(line)
        unknown = used - known
        assert not unknown, (
            f'`ts-scan {sub}` does not have flag(s) {unknown} (line: {line!r}); '
            f'known flags: {sorted(known)}'
        )


def test_reference_includes_expected_subcommands(reference):
    assert {'scan', 'upload', 'check', 'convert', 'import', 'analyse', 'init'} <= set(reference)


def test_upload_reference_has_no_module_flag(reference):
    # The exact gap this project must never paper over with an invented flag.
    assert '--module' not in reference['upload'].known_flags()
    assert '--project-name' in reference['upload'].known_flags()


def test_scan_command_uses_only_real_flags(reference):
    command = _scan_command('.', 'my-module', 'my-project')
    _assert_all_flags_known(command, reference)


def test_scan_command_never_invents_a_module_flag_on_upload():
    command = _scan_command('src/pkg', 'my-module', 'my-project')
    upload_line = next(line for line in command.split('&&') if 'upload' in line)
    assert '--module' not in upload_line
    assert '--project-name' in upload_line
    assert '--api-key' in upload_line


def test_docker_scan_command_uses_only_real_flags(reference):
    command = _docker_scan_command('my-module-container', 'my-project')
    _assert_all_flags_known(command, reference)


def test_docker_scan_command_does_not_invoke_a_nonexistent_docker_subcommand():
    command = _docker_scan_command('my-module-container', 'my-project')
    tokens = command.split()
    assert 'docker' not in tokens  # only appears inside "docker:<image>", not as a subcommand
    assert '--use-syft' in command
    assert 'docker:<image>' in command
