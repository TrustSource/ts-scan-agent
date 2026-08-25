from pathlib import Path

from ts_scan_agent.settings import load_settings


def _write_toml(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def test_returns_empty_dict_when_neither_file_exists(tmp_path: Path):
    settings = load_settings(user_config_path=tmp_path / 'nope.toml', project_dir=tmp_path)
    assert settings == {}


def test_reads_user_config(tmp_path: Path):
    user_cfg = tmp_path / 'user' / 'config.toml'
    _write_toml(user_cfg, 'level = "expert"\nllm = "none"\n')

    settings = load_settings(user_config_path=user_cfg, project_dir=tmp_path)

    assert settings == {'level': 'expert', 'llm': 'none'}


def test_project_config_overrides_user_config(tmp_path: Path):
    user_cfg = tmp_path / 'user' / 'config.toml'
    _write_toml(user_cfg, 'level = "expert"\nllm = "none"\n')
    project_dir = tmp_path / 'repo'
    _write_toml(project_dir / '.ts-scan-agent.toml', 'level = "beginner"\n')

    settings = load_settings(user_config_path=user_cfg, project_dir=project_dir)

    assert settings == {'level': 'beginner', 'llm': 'none'}
