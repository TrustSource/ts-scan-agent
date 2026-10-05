import re
import sys
import typing as t

from pathlib import Path

import click

from . import __version__
from .inventory import scan_inventory
from .mapping import build_candidates
from .interview import run_interview, load_answers, apply_answers
from .render import render_markdown, render_json, Level, LEVEL_CHOICES, FORMAT_CHOICES
from .model import ScanConcept, ExistingIssueRef
from .llm import LLMClient, NullLLMClient
from .ecosystem_proposals import build_proposals
from .github_issues import find_similar_issues, file_issue, GitHubIssueError
from .settings import load_settings, USER_CONFIG_PATH


@click.group(context_settings={'auto_envvar_prefix': 'TS_SCAN_AGENT'})
@click.version_option(version=__version__, prog_name='ts-scan-agent')
@click.option('--config', 'config_path', default=USER_CONFIG_PATH, show_default=True,
              type=click.Path(path_type=Path, dir_okay=False),
              help='User-level settings file (TOML), keyed by the option names shown below '
                   '(e.g. `level = "expert"`). A .ts-scan-agent.toml in the current directory, '
                   'if present, overrides it - commit one to a repo to pin shared team/CI '
                   'defaults. Every value here can still be overridden by a '
                   'TS_SCAN_AGENT_<NAME> environment variable or the matching CLI flag.')
@click.pass_context
def start(ctx: click.Context, config_path: Path):
    """Proposes a TrustSource scan concept for a repository: which parts should become
    TrustSource Modules, Infrastructure Modules or Linked Modules, and which ts-scan command
    to run for each."""
    settings = load_settings(config_path, project_dir=Path.cwd())
    ctx.default_map = settings
    group = t.cast(click.Group, ctx.command)
    for sub in group.commands.values():
        sub.context_settings['default_map'] = settings


def _build_llm_client(backend: str, model: t.Optional[str], ollama_url: str,
                       anthropic_api_key: t.Optional[str]) -> LLMClient:
    if backend == 'none':
        return NullLLMClient()

    if backend == 'ollama':
        from .llm.ollama import OllamaLLMClient, DEFAULT_MODEL
        return OllamaLLMClient(model=model or DEFAULT_MODEL, base_url=ollama_url)

    if backend == 'anthropic':
        if not anthropic_api_key:
            raise click.UsageError(
                '--anthropic-api-key (or ANTHROPIC_API_KEY) is required for --llm anthropic'
            )
        from .llm.anthropic import AnthropicLLMClient, DEFAULT_MODEL
        return AnthropicLLMClient(api_key=anthropic_api_key, model=model or DEFAULT_MODEL)

    raise click.UsageError(f'Unknown LLM backend: {backend}')


@start.command('analyze', help='Analyze a repository and propose a TrustSource scan concept')
@click.argument('path', type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.option('--level', type=click.Choice(LEVEL_CHOICES), default='beginner', show_default=True,
              help='How much explanation the report includes. beginner: step-by-step '
                   'TrustSource onboarding plus a concepts glossary, in addition to everything '
                   'intermediate has (default - if you already know TrustSource, set this once '
                   'in a settings file or pass --level intermediate/expert). intermediate: '
                   'structure, commands, rationale and hints. expert: structure and commands '
                   'only, no prose.')
@click.option('--project', required=False,
              help='TrustSource project name to propose (defaults to the directory name)')
@click.option('--llm', type=click.Choice(['none', 'ollama', 'anthropic']), default='ollama',
              help='LLM backend for ambiguous judgment calls. "none" runs fully offline/'
                   'rule-based and defers everything ambiguous to the interview.')
@click.option('--llm-model', required=False, help='Override the default model for the chosen backend')
@click.option('--ollama-url', default='http://localhost:11434', show_default=True,
              help='Base URL of the local Ollama server')
@click.option('--anthropic-api-key', envvar='ANTHROPIC_API_KEY', required=False,
              help='Anthropic API key (or set ANTHROPIC_API_KEY)')
@click.option('--non-interactive', is_flag=True, default=False,
              help='Skip the interview step; unresolved items are listed under "Still open". '
                   'Implied when stdin is not a terminal.')
@click.option('--answers', required=False, metavar='FILE|JSON',
              help='Map from candidate path to answer, applied instead of the interview: a '
                   'JSON (or .toml) file, or an inline JSON object such as '
                   '\'{"Dockerfile": "module"}\'. Answers are "module"/"infrastructure_module" '
                   'for a Dockerfile, "yes"/"no" for everything else. Unanswered items stay '
                   'under "Still open"; an unknown path or invalid value is an error.')
@click.option('--format', type=click.Choice(FORMAT_CHOICES), default='markdown', show_default=True,
              help='Report format. json dumps the scan concept (candidates, commands, open '
                   'questions, ecosystem proposals) for scripts and coding agents; --level only '
                   'affects markdown.')
@click.option('--propose-issues/--no-propose-issues', default=True,
              help='Draft a ts-scan GitHub issue proposal for each unsupported ecosystem found '
                   '(local/text only - never filed without --file-issues)')
@click.option('--issue-repo', default='trustsource/ts-scan', show_default=True,
              help='Repository ecosystem-support proposals target')
@click.option('--file-issues', is_flag=True, default=False,
              help='For each drafted proposal with no likely-duplicate issue found, let you '
                   'review/edit it in $EDITOR and then confirm before filing it on GitHub. '
                   'Ignored (with a warning) under --non-interactive - filing always requires '
                   'an interactive confirmation.')
@click.option('-o', '--output', required=False, type=click.Path(path_type=Path),
              help='Write the report here instead of printing it')
def analyze(path: Path, level: Level, project: t.Optional[str], llm: str,
            llm_model: t.Optional[str], ollama_url: str,
            anthropic_api_key: t.Optional[str], non_interactive: bool,
            answers: t.Optional[str], format: str,
            propose_issues: bool, issue_repo: str, file_issues: bool,
            output: t.Optional[Path]):
    root = path.resolve()
    project_name = project or root.name

    # Read --answers up front so a malformed file fails before any scanning work.
    answer_map = load_answers(answers) if answers else None

    if answer_map is not None:
        non_interactive = True
    elif not non_interactive and not _stdin_is_tty():
        click.echo(
            'Warning: stdin is not a terminal - running non-interactively. Unresolved items '
            'are listed under "Still open"; pass --non-interactive to silence this, or '
            '--answers FILE to resolve them.',
            err=True,
        )
        non_interactive = True

    llm_client = _build_llm_client(llm, llm_model, ollama_url, anthropic_api_key)

    click.echo(f'Scanning {root} ...', err=True)
    units = scan_inventory(root)

    candidates = build_candidates(project_name, root, units, llm=llm_client)
    concept = ScanConcept(project_name=project_name, source_path=str(root), candidates=candidates)

    if answer_map is not None:
        apply_answers(concept, answer_map)
    run_interview(concept, non_interactive=non_interactive)

    if propose_issues:
        concept.ecosystem_proposals = build_proposals(units, llm=llm_client)
        for proposal in concept.ecosystem_proposals:
            results = find_similar_issues(issue_repo, proposal.ecosystem)
            proposal.existing_issue_checked = results is not None
            if results:
                proposal.existing_issue = ExistingIssueRef(**results[0])

    if file_issues:
        if non_interactive:
            click.echo(
                'Warning: --file-issues has no effect under --non-interactive - filing always '
                'requires interactive review and confirmation.',
                err=True,
            )
        else:
            _review_and_file_issues(concept, issue_repo)

    if format == 'json':
        report = render_json(concept)
    else:
        report = render_markdown(concept, units, issue_repo=issue_repo, level=level)

    if output:
        output.write_text(report)
        click.echo(f'Wrote scan concept to {output}', err=True)
    else:
        click.echo(report)


def _stdin_is_tty() -> bool:
    # A stdin object closed in-process (by an embedding wrapper) raises ValueError on isatty().
    try:
        return sys.stdin is not None and sys.stdin.isatty()
    except (ValueError, AttributeError):
        return False


_TITLE_LINE_RE = re.compile(r'^\s*Title:\s*(.*)$')


def _parse_edited_proposal(edited: str) -> t.Tuple[t.Optional[str], str]:
    """Pulls a "Title: ..." line (however it drifted after a round-trip through the user's
    editor - leading whitespace, blank lines above it, trailing whitespace) out of the edited
    text, if still present, and returns (title_or_None, remaining_body). Falls back to
    (None, edited) - keeping the original title - rather than silently dumping "Title: ..."
    into the body when the marker doesn't match exactly."""

    lines = edited.splitlines()
    for i, line in enumerate(lines):
        if not line.strip():
            continue
        match = _TITLE_LINE_RE.match(line)
        if match:
            body = '\n'.join(lines[i + 1:]).strip()
            return match.group(1).strip() or None, body
        break  # first non-blank line isn't a Title: line - don't scan further

    return None, edited.strip()


def _review_and_file_issues(concept: ScanConcept, issue_repo: str) -> None:
    for proposal in concept.ecosystem_proposals:
        if proposal.existing_issue:
            continue

        click.echo(f'\n--- Draft proposal for {proposal.ecosystem} ---', err=True)
        click.echo('Opening in your editor for review - save and close to continue.', err=True)

        edited = click.edit(text=f'Title: {proposal.title}\n\n{proposal.body}')
        if edited is None:
            click.echo('Skipped (editor closed without saving).', err=True)
            continue

        title, body = _parse_edited_proposal(edited)
        proposal.title = title or proposal.title
        proposal.body = body

        click.echo(f'\nTitle: {proposal.title}\n\n{proposal.body}\n', err=True)
        if not click.confirm(f'File this on {issue_repo}?', default=False, err=True):
            click.echo('Skipped.', err=True)
            continue

        try:
            url = file_issue(issue_repo, proposal.title, proposal.body, labels=['enhancement'])
            click.echo(f'Filed: {url}', err=True)
        except GitHubIssueError as err:
            click.echo(f'Failed to file issue: {err}', err=True)
