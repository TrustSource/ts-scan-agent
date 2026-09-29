import json
import typing as t

from pathlib import Path, PurePosixPath

import click
import toml

from .model import ScanConcept, Candidate, FoldedCandidate

# The answer values `--answers` accepts per candidate type - the same choices the interactive
# interview offers, spelled out so an agent can pass them back without a TTY.
DOCKERFILE_ANSWERS = ('module', 'infrastructure_module')
YES_NO_ANSWERS = ('yes', 'no')


class AnswersError(click.ClickException):
    """A problem with an --answers file: unreadable, wrong shape, unknown path or invalid
    value. Exits non-zero with the message instead of silently ignoring the answer."""


def _resolve(concept: ScanConcept, candidate: Candidate, answer: t.Union[str, bool]) -> None:
    """Applies one answer to a candidate. `answer` is a Dockerfile choice
    ('module'/'infrastructure_module') or a yes/no as a bool, depending on candidate_type.
    The rationale is rewritten to state what the user confirmed - Mapping's original text
    describes the doubt ("defaulting to...", "could be vendored"), which is stale once
    answered. A nested package answered "no" belongs to its parent, so it leaves
    `candidates` (and its scan command with it) for `folded_into_parent`."""

    name = PurePosixPath(candidate.path).name

    if candidate.candidate_type == 'infrastructure_module':
        candidate.candidate_type = answer  # type: ignore[assignment]
        if answer == 'module':
            candidate.rationale = (
                f'{name} found; the user confirmed the image is their own deployable '
                'service, so it is a Module'
            )
        else:
            candidate.rationale = (
                f'{name} found; the user confirmed the image is runtime infrastructure '
                '(base image, sidecar, etc.), so it is an Infrastructure Module'
            )

    elif candidate.candidate_type == 'linked_module':
        if answer:
            candidate.rationale = (
                f'{candidate.ecosystem} manifest found in a monorepo workspace; the user '
                'confirmed it is published/released on its own - set it up as its own '
                'TrustSource project and link its release into this project as a Linked Module'
            )
        else:
            candidate.candidate_type = 'module'
            candidate.rationale = (
                f'{candidate.ecosystem} manifest found in a monorepo workspace; the user '
                'confirmed it is not released on its own, so it is scanned as a Module of '
                'this project'
            )

    elif answer:
        candidate.rationale = (
            f'{candidate.ecosystem} manifest found in a nested directory; the user confirmed '
            'it is released/deployed separately, so it is its own Module'
        )

    else:
        concept.candidates.remove(candidate)
        concept.folded_into_parent.append(FoldedCandidate(
            name=candidate.name, path=candidate.path, ecosystem=candidate.ecosystem,
        ))
        return

    candidate.confidence = 1.0
    candidate.open_question = None


def run_interview(concept: ScanConcept, non_interactive: bool = False) -> None:
    """v1 interview: a fixed sequential CLI prompt over the candidates Mapping could not
    confidently classify. Updates each candidate in place. Deliberately not a freeform LLM
    chat yet (see ARCHITECTURE.md ADR-002) - just enough to resolve the concrete yes/no or
    module-vs-infra decisions Mapping already knows it's unsure about. Everything goes to
    stderr so stdout stays reserved for the report."""

    pending = concept.low_confidence_candidates
    if not pending:
        return

    if non_interactive:
        return

    click.echo(f'\n{len(pending)} item(s) need your input to finish the scan concept:\n', err=True)

    for candidate in pending:
        # `pending` only contains candidates with open_question set (see
        # ScanConcept.low_confidence_candidates), so this always holds.
        assert candidate.open_question is not None
        question = candidate.open_question

        click.echo(f'--- {candidate.path} ({candidate.name}) ---', err=True)
        click.echo(candidate.rationale, err=True)

        if candidate.candidate_type == 'infrastructure_module':
            answer: t.Union[str, bool] = click.prompt(
                question,
                type=click.Choice(list(DOCKERFILE_ANSWERS)),
                default='infrastructure_module',
                err=True,
            )
        else:
            answer = click.confirm(question, default=True, err=True)

        _resolve(concept, candidate, answer)
        click.echo('', err=True)


def load_answers(value: str) -> t.Dict[str, t.Any]:
    """Reads --answers: an inline JSON object (anything starting with `{`), or a file - TOML if
    it ends in .toml, JSON otherwise. Inline JSON lets a coding agent pass answers in one
    command, without writing a temp file first. Must be a flat map from candidate path to
    answer."""

    if value.lstrip().startswith('{'):
        source = 'inline --answers JSON'
        try:
            data = json.loads(value)
        except ValueError as err:
            raise AnswersError(f'Could not parse {source}: {err}')
    else:
        path = Path(value)
        source = f'--answers file {path}'
        try:
            text = path.read_text()
            data = toml.loads(text) if path.suffix.lower() == '.toml' else json.loads(text)
        except (OSError, ValueError, toml.TomlDecodeError) as err:
            raise AnswersError(f'Could not read {source}: {err}')

    if not isinstance(data, dict):
        raise AnswersError(
            f'{source} must contain a map from candidate path to answer, '
            f'e.g. {{"tools/helper": "yes", "Dockerfile": "module"}}'
        )
    return data


def _parse_answer(candidate: Candidate, value: t.Any) -> t.Union[str, bool]:
    if candidate.candidate_type == 'infrastructure_module':
        if value in DOCKERFILE_ANSWERS:
            return value
        allowed = DOCKERFILE_ANSWERS
    else:
        if isinstance(value, bool):
            return value
        if isinstance(value, str) and value.lower() in YES_NO_ANSWERS:
            return value.lower() == 'yes'
        allowed = YES_NO_ANSWERS

    raise AnswersError(
        f'Invalid answer {value!r} for "{candidate.path}" - expected one of: '
        f'{", ".join(allowed)}'
    )


def apply_answers(concept: ScanConcept, answers: t.Dict[str, t.Any]) -> None:
    """Non-interactive counterpart to run_interview(): resolves open questions from a
    path -> answer map (e.g. collected by a coding agent in chat). Validates every entry
    before changing anything, so a bad file never leaves the concept half-applied. Open
    questions without an answer stay open and show up under "Still open"."""

    pending = {c.path: c for c in concept.low_confidence_candidates}

    unknown = sorted(path for path in answers if path not in pending)
    if unknown:
        open_paths = ', '.join(f'"{p}"' for p in sorted(pending)) or 'none'
        raise AnswersError(
            f'--answers names path(s) with no open question: '
            f'{", ".join(repr(p) for p in unknown)}. Open questions exist for: {open_paths}'
        )

    parsed = {path: _parse_answer(pending[path], value) for path, value in answers.items()}
    for path, answer in parsed.items():
        _resolve(concept, pending[path], answer)
