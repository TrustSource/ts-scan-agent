import re
import typing as t

from pydantic import BaseModel


class CommandParam(BaseModel):
    flags: t.List[str]
    required: bool
    is_argument: bool


class CommandRef(BaseModel):
    name: str
    params: t.List[CommandParam]

    def known_flags(self) -> t.Set[str]:
        return {flag for p in self.params for flag in p.flags if not p.is_argument}


def load_reference() -> t.Dict[str, CommandRef]:
    """Ground truth for every real `ts-scan` CLI command and its flags, introspected directly
    from the installed `ts-scan` package's Click command tree - never hand-transcribed, so it
    tracks whatever `ts-scan` version is actually pinned in pyproject.toml instead of drifting
    from it. This is the only source `mapping.py` may build `ts_scan_command` strings from, and
    the only source `tests/test_ts_scan_reference.py` checks them against - no command text in
    this project may reference a flag that doesn't really exist. See ARCHITECTURE.md ADR-007."""

    import click
    import ts_scan.cli.scan
    import ts_scan.cli.analyse
    import ts_scan.cli.check
    import ts_scan.cli.upload
    import ts_scan.cli.import_sbom
    import ts_scan.cli.convert
    import ts_scan.cli.init
    from ts_scan.cli import cli as ts_scan_cli

    reference = {}
    for name, cmd in ts_scan_cli.commands.items():
        params = []
        for p in cmd.params:
            params.append(CommandParam(
                flags=list(getattr(p, 'opts', [])),
                required=bool(p.required),
                is_argument=isinstance(p, click.Argument),
            ))
        reference[name] = CommandRef(name=name, params=params)

    return reference


_FLAG_TOKEN_RE = re.compile(r'(?<!\S)(--[a-zA-Z][\w-]*|-[a-zA-Z](?!\w))')


def extract_flags(command_text: str) -> t.Set[str]:
    """Pulls flag-looking tokens (`--foo`, `-f`) out of a generated shell command string, for
    validating it against load_reference(). Deliberately simple (no shell parsing) - good
    enough for the fixed templates this project generates, not meant for arbitrary input."""
    return set(_FLAG_TOKEN_RE.findall(command_text))


def subcommand_used(command_text: str, known_subcommands: t.Iterable[str]) -> t.Optional[str]:
    """Which `ts-scan <subcommand>` appears in this command string, if any - used together with
    extract_flags() to check flags against the right command's reference."""
    for token in command_text.split():
        if token in known_subcommands:
            return token
    return None
