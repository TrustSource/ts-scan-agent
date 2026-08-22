import json
import subprocess
import typing as t
import warnings


class GitHubIssueError(Exception):
    pass


def find_similar_issues(repo: str, query: str) -> t.List[t.Dict[str, t.Any]]:
    """Best-effort duplicate check via `gh issue list --search`. Read-only. Degrades to an
    empty list (never raises) if `gh` isn't installed or not authenticated - dedup is a safety
    net on top of the human review step, not a hard requirement for drafting a proposal."""

    try:
        result = subprocess.run(
            ['gh', 'issue', 'list', '--repo', repo, '--search', query, '--state', 'all',
             '--json', 'number,title,url,state'],
            capture_output=True, text=True, timeout=30,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as err:
        warnings.warn(f'Could not check {repo} for existing issues ({err}); skipping dedup.')
        return []

    if result.returncode != 0:
        warnings.warn(
            f'Could not check {repo} for existing issues ({result.stderr.strip()}); '
            'skipping dedup.'
        )
        return []

    try:
        return json.loads(result.stdout)
    except ValueError:
        warnings.warn(f'Could not parse `gh issue list` output for {repo}; skipping dedup.')
        return []


def file_issue(repo: str, title: str, body: str, labels: t.List[str]) -> str:
    """Actually files a new issue. Only ever call this after the caller has gotten explicit,
    per-issue interactive confirmation (see cli.py) - this posts publicly, under the local
    `gh` session's identity, to a real third-party-maintained repository."""

    args = ['gh', 'issue', 'create', '--repo', repo, '--title', title, '--body', body]
    for label in labels:
        args += ['--label', label]

    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=30)
    except FileNotFoundError as err:
        raise GitHubIssueError(
            'The `gh` CLI is required to file issues. Install it from https://cli.github.com '
            'and run `gh auth login` first.'
        ) from err

    if result.returncode != 0:
        raise GitHubIssueError(f'`gh issue create` failed: {result.stderr.strip()}')

    return result.stdout.strip()
