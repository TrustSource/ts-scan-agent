import typing as t

from pathlib import Path

import toml

USER_CONFIG_PATH = Path('~/.ts-scan-agent/config.toml')
PROJECT_CONFIG_FILENAME = '.ts-scan-agent.toml'


def load_settings(user_config_path: Path = USER_CONFIG_PATH,
                   project_dir: Path = Path('.')) -> t.Dict[str, t.Any]:
    """Merges the user-level and project-level settings files into one dict, keyed by the same
    names shown in `--help` (`level`, `llm`, `project`, `issue_repo`, ...) - installed as the
    `analyze` command's Click `default_map`, so any value here is overridden by an environment
    variable (`TS_SCAN_AGENT_<NAME>`) or an explicit CLI flag, and itself overrides the flag's
    own hardcoded default.

    Mirrors ts-scan's own `~/.ts-scan/config` + `tsproject.toml` layering (`ts_scan/cli/
    __init__.py`), simplified: no profiles, and the project file is looked up in the current
    working directory rather than pre-parsed out of the `path` argument (ts-scan's own approach
    for that needs a custom Group subclass and a manual pre-parse pass - more machinery than
    this single-command CLI needs; in the common case of running `ts-scan-agent analyze .` from
    the repo root, CWD *is* the analyzed path anyway).

    Precedence, lowest to highest: hardcoded CLI default < user config < project config <
    environment variable < explicit CLI flag. This function only produces the middle two."""

    settings: t.Dict[str, t.Any] = {}

    user_cfg = user_config_path.expanduser()
    if user_cfg.is_file():
        settings.update(toml.load(user_cfg))

    project_cfg = project_dir / PROJECT_CONFIG_FILENAME
    if project_cfg.is_file():
        settings.update(toml.load(project_cfg))

    return settings
