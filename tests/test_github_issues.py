import json
import subprocess

import pytest

from ts_scan_agent import github_issues


class FakeCompletedProcess:
    def __init__(self, returncode=0, stdout='', stderr=''):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def test_find_similar_issues_parses_gh_output(monkeypatch):
    captured = {}
    payload = [{'number': 22, 'title': 'pls. add flutter env', 'url': 'https://x/22', 'state': 'OPEN'}]

    def fake_run(args, **kwargs):
        captured['args'] = args
        return FakeCompletedProcess(returncode=0, stdout=json.dumps(payload))

    monkeypatch.setattr(subprocess, 'run', fake_run)

    result = github_issues.find_similar_issues('trustsource/ts-scan', 'Flutter')

    assert result == payload
    assert captured['args'][:3] == ['gh', 'issue', 'list']
    assert '--repo' in captured['args'] and 'trustsource/ts-scan' in captured['args']
    assert '--search' in captured['args'] and 'Flutter' in captured['args']


def test_find_similar_issues_degrades_to_empty_list_when_gh_missing(monkeypatch):
    def fake_run(args, **kwargs):
        raise FileNotFoundError('gh not found')

    monkeypatch.setattr(subprocess, 'run', fake_run)

    with pytest.warns(UserWarning):
        result = github_issues.find_similar_issues('trustsource/ts-scan', 'PHP')

    assert result == []


def test_find_similar_issues_degrades_to_empty_list_on_nonzero_exit(monkeypatch):
    def fake_run(args, **kwargs):
        return FakeCompletedProcess(returncode=1, stderr='not authenticated')

    monkeypatch.setattr(subprocess, 'run', fake_run)

    with pytest.warns(UserWarning):
        result = github_issues.find_similar_issues('trustsource/ts-scan', 'PHP')

    assert result == []


def test_file_issue_returns_url_on_success(monkeypatch):
    captured = {}

    def fake_run(args, **kwargs):
        captured['args'] = args
        return FakeCompletedProcess(returncode=0, stdout='https://github.com/trustsource/ts-scan/issues/99\n')

    monkeypatch.setattr(subprocess, 'run', fake_run)

    url = github_issues.file_issue('trustsource/ts-scan', 'Add PHP support', 'body text', ['enhancement'])

    assert url == 'https://github.com/trustsource/ts-scan/issues/99'
    assert captured['args'][:3] == ['gh', 'issue', 'create']
    assert '--label' in captured['args'] and 'enhancement' in captured['args']


def test_file_issue_raises_on_nonzero_exit(monkeypatch):
    def fake_run(args, **kwargs):
        return FakeCompletedProcess(returncode=1, stderr='validation failed')

    monkeypatch.setattr(subprocess, 'run', fake_run)

    with pytest.raises(github_issues.GitHubIssueError):
        github_issues.file_issue('trustsource/ts-scan', 'title', 'body', [])


def test_file_issue_raises_clear_error_when_gh_missing(monkeypatch):
    def fake_run(args, **kwargs):
        raise FileNotFoundError('gh not found')

    monkeypatch.setattr(subprocess, 'run', fake_run)

    with pytest.raises(github_issues.GitHubIssueError):
        github_issues.file_issue('trustsource/ts-scan', 'title', 'body', [])
