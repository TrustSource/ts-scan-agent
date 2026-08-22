import click

from .model import ScanConcept


def run_interview(concept: ScanConcept, non_interactive: bool = False) -> None:
    """v1 interview: a fixed sequential CLI prompt over the candidates Mapping could not
    confidently classify. Updates each candidate in place. Deliberately not a freeform LLM
    chat yet (see ARCHITECTURE.md ADR-002) - just enough to resolve the concrete yes/no or
    module-vs-infra decisions Mapping already knows it's unsure about."""

    pending = concept.low_confidence_candidates
    if not pending:
        return

    if non_interactive:
        return

    click.echo(f'\n{len(pending)} item(s) need your input to finish the scan concept:\n')

    for candidate in pending:
        # `pending` only contains candidates with open_question set (see
        # ScanConcept.low_confidence_candidates), so this always holds.
        assert candidate.open_question is not None
        question = candidate.open_question

        click.echo(f'--- {candidate.path} ({candidate.name}) ---')
        click.echo(candidate.rationale)

        if candidate.candidate_type == 'infrastructure_module':
            choice = click.prompt(
                question,
                type=click.Choice(['module', 'infrastructure_module']),
                default='infrastructure_module',
            )
            candidate.candidate_type = choice  # type: ignore[assignment]
            candidate.confidence = 1.0
            candidate.open_question = None

        elif candidate.candidate_type == 'linked_module':
            confirmed = click.confirm(question, default=True)
            if not confirmed:
                candidate.candidate_type = 'module'
            candidate.confidence = 1.0
            candidate.open_question = None

        else:
            confirmed = click.confirm(question, default=True)
            candidate.confidence = 1.0
            if not confirmed:
                candidate.rationale += (
                    ' [User indicated this should likely be folded into its parent module '
                    'rather than scanned separately - review before adopting this concept.]'
                )
            candidate.open_question = None

        click.echo('')
