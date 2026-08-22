import typing as t

from pathlib import Path

import click

from . import __version__
from .inventory import scan_inventory
from .mapping import build_candidates
from .interview import run_interview
from .render import render_markdown
from .model import ScanConcept
from .llm import LLMClient, NullLLMClient


@click.group()
@click.version_option(version=__version__, prog_name='ts-scan-agent')
def start():
    """Proposes a TrustSource scan concept for a repository: which parts should become
    TrustSource Modules, Infrastructure Modules or Linked Modules, and which ts-scan command
    to run for each."""


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
@click.option('--project', 'project_name', required=False,
              help='TrustSource project name to propose (defaults to the directory name)')
@click.option('--llm', 'llm_backend', type=click.Choice(['none', 'ollama', 'anthropic']),
              default='ollama',
              help='LLM backend for ambiguous judgment calls. "none" runs fully offline/'
                   'rule-based and defers everything ambiguous to the interview.')
@click.option('--llm-model', required=False, help='Override the default model for the chosen backend')
@click.option('--ollama-url', default='http://localhost:11434', show_default=True,
              help='Base URL of the local Ollama server')
@click.option('--anthropic-api-key', envvar='ANTHROPIC_API_KEY', required=False,
              help='Anthropic API key (or set ANTHROPIC_API_KEY)')
@click.option('--non-interactive', is_flag=True, default=False,
              help='Skip the interview step; unresolved items are listed under "Still open"')
@click.option('-o', '--output', 'output_path', type=click.Path(path_type=Path), required=False,
              help='Write the Markdown report here instead of printing it')
def analyze(path: Path, project_name: t.Optional[str], llm_backend: str,
            llm_model: t.Optional[str], ollama_url: str,
            anthropic_api_key: t.Optional[str], non_interactive: bool,
            output_path: t.Optional[Path]):
    root = path.resolve()
    project_name = project_name or root.name

    llm = _build_llm_client(llm_backend, llm_model, ollama_url, anthropic_api_key)

    click.echo(f'Scanning {root} ...', err=True)
    units = scan_inventory(root)

    candidates = build_candidates(project_name, root, units, llm=llm)
    concept = ScanConcept(project_name=project_name, source_path=str(root), candidates=candidates)

    run_interview(concept, non_interactive=non_interactive)

    report = render_markdown(concept, units)

    if output_path:
        output_path.write_text(report)
        click.echo(f'Wrote scan concept to {output_path}', err=True)
    else:
        click.echo(report)
