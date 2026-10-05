import importlib.util
import sys
import json
import re

from pathlib import Path

import pytest
import toml

from ts_scan_agent.ts_scan_reference import extract_flags

REPO_ROOT = Path(__file__).resolve().parent.parent
SKILL_DIR = REPO_ROOT / 'skills' / 'ts-scan-agent'
SKILL_MD = SKILL_DIR / 'SKILL.md'
PLUGIN_JSON = REPO_ROOT / '.claude-plugin' / 'plugin.json'
MARKETPLACE_JSON = REPO_ROOT / '.claude-plugin' / 'marketplace.json'

# Frontmatter keys the Agent Skills spec (agentskills.io) allows. Anything else is rejected by
# some hosts (claude.ai uploads, the Skills API) and ignored by others (Copilot, Codex), so the
# skill sticks to these to stay portable across agents.
SPEC_FRONTMATTER_KEYS = {'name', 'description', 'license', 'compatibility', 'metadata', 'allowed-tools'}

SCRIPTS = SKILL_DIR / 'scripts'

# `RUN analyze ...` in SKILL.md stands for either bundled script (see its step 1).
_INVOCATION_RE = re.compile(r'(?:RUN|scan_concept\.(?:py|mjs)) analyze([^`\n)]*)')


def _project_version() -> str:
    return toml.loads((REPO_ROOT / 'pyproject.toml').read_text())['project']['version']


def _split_frontmatter(text: str):
    match = re.match(r'^---\n(.*?)\n---\n(.*)$', text, re.DOTALL)
    assert match, 'SKILL.md must start with a --- delimited YAML frontmatter block'
    return match.group(1), match.group(2)


def _frontmatter_keys(frontmatter: str):
    return {line.split(':', 1)[0] for line in frontmatter.splitlines()
            if line and not line.startswith(' ') and ':' in line}


def _frontmatter_value(frontmatter: str, key: str) -> str:
    # Leading whitespace allowed so nested `metadata:` keys (e.g. version) can be looked up too.
    match = re.search(rf'^\s*{re.escape(key)}:\s*(.*)$', frontmatter, re.MULTILINE)
    assert match, f'SKILL.md frontmatter has no {key!r}'
    return match.group(1).strip().strip('"')


@pytest.fixture(scope='module')
def skill_text() -> str:
    return SKILL_MD.read_text()


def _script_module():
    spec = importlib.util.spec_from_file_location('scan_concept', SCRIPTS / 'scan_concept.py')
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # No __pycache__ inside the skill folder - it gets copied verbatim into users' skill dirs.
    dont_write, sys.dont_write_bytecode = sys.dont_write_bytecode, True
    try:
        spec.loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = dont_write
    return module


def _analyze_flags():
    parser = _script_module().build_parser()
    analyze = parser._subparsers._group_actions[0].choices['analyze']
    return {opt for action in analyze._actions for opt in action.option_strings}


def test_skill_invokes_analyze_at_least_once(skill_text):
    assert len(_INVOCATION_RE.findall(skill_text)) >= 2


def test_every_analyze_flag_in_skill_exists(skill_text):
    # Same guard test_ts_scan_reference.py puts on ts-scan commands: renaming or removing a
    # script flag must fail CI before it silently breaks the published skill. The Node port
    # accepts the same flags - test_skill_scripts.py runs it with them.
    known = _analyze_flags()
    for tail in _INVOCATION_RE.findall(skill_text):
        unknown = extract_flags(tail) - known
        assert not unknown, (
            f'SKILL.md uses analyze flag(s) {sorted(unknown)} that do not exist '
            f'(in: {tail.strip()!r}); known flags: {sorted(known)}'
        )


def test_skill_frontmatter_follows_agent_skills_spec(skill_text):
    frontmatter, body = _split_frontmatter(skill_text)
    keys = _frontmatter_keys(frontmatter)
    assert keys <= SPEC_FRONTMATTER_KEYS, f'non-spec frontmatter keys: {keys - SPEC_FRONTMATTER_KEYS}'

    name = _frontmatter_value(frontmatter, 'name')
    assert name == SKILL_DIR.name
    assert re.fullmatch(r'[a-z0-9]+(-[a-z0-9]+)*', name)
    assert 0 < len(_frontmatter_value(frontmatter, 'description')) <= 1024
    assert len(_frontmatter_value(frontmatter, 'compatibility')) <= 500
    assert len(skill_text.splitlines()) < 500


def test_allowed_tools_only_pre_approve_the_bundled_scripts(skill_text):
    frontmatter, _ = _split_frontmatter(skill_text)
    rules = re.findall(r'Bash\(([^)]*)\)', _frontmatter_value(frontmatter, 'allowed-tools'))
    assert rules
    for rule in rules:
        assert re.fullmatch(
            r'(python3|python|node) \$\{CLAUDE_SKILL_DIR\}/scripts/scan_concept\.(py|mjs) analyze \*',
            rule,
        ), f'allowed-tools rule is broader than the bundled analyze script: {rule!r}'


def test_skill_needs_no_installs(skill_text):
    # The whole point of the skill: nothing to pip/npm/uv install to run it.
    for forbidden in ('uvx', 'pip install git+', 'npm install', 'ts-scan-agent analyze'):
        assert forbidden not in skill_text


def test_skill_and_scripts_carry_the_package_version(skill_text):
    version = _project_version()
    frontmatter, _ = _split_frontmatter(skill_text)
    assert _frontmatter_value(frontmatter, 'version') == version
    assert f"VERSION = '{version}'" in (SCRIPTS / 'scan_concept.py').read_text()
    assert f"const VERSION = '{version}';" in (SCRIPTS / 'scan_concept.mjs').read_text()


def test_python_script_is_stdlib_only():
    # scan_concept.py must run on a bare Python 3.8+ with nothing installed.
    source = (SCRIPTS / 'scan_concept.py').read_text()
    imports = set(re.findall(r'^(?:import|from) (\w+)', source, re.MULTILINE))
    assert imports <= {'argparse', 'json', 'os', 're', 'shlex', 'sys'}, imports


def test_node_script_has_only_builtin_imports():
    source = (SCRIPTS / 'scan_concept.mjs').read_text()
    imports = set(re.findall(r"^import .* from '([^']+)';", source, re.MULTILINE))
    assert imports and all(i.startswith('node:') for i in imports), imports


def test_bundled_scripts_can_never_write_or_run_anything():
    # SKILL.md pre-approves both scripts with *any* trailing arguments, so the scripts themselves
    # must be incapable of side effects: no file writes, no process spawning, no deletion. The
    # import allow-list above doesn't cover this - `os` alone offers os.system/os.remove.
    # Patterns target API *calls*, not words - the report prose legitimately says "rename it".
    forbidden = {
        'scan_concept.py': r"open\([^)]*mode\s*=\s*['\"][^'\"]*[wax+]|"
                           r"open\([^,()]+,\s*['\"][^'\"]*[wax+][^'\"]*['\"]|"
                           r"\.write_text\(|\.write_bytes\(|"
                           r"\bos\.(system|popen|remove|unlink|rename|replace|rmdir|mkdir|makedirs|"
                           r"exec\w*|spawn\w*|fork|kill)\(|"
                           r"\bsubprocess\b|\bshutil\b|\btempfile\b|\beval\(|\bexec\(|__import__",
        'scan_concept.mjs': r"\b(writeFile|writeFileSync|appendFile|appendFileSync|createWriteStream|"
                            r"unlink|unlinkSync|rmSync|rmdirSync|renameSync|mkdirSync|copyFileSync|"
                            r"truncateSync|symlinkSync|chmodSync)\(|child_process|\beval\(|"
                            r"new Function|\bimport\(|\brequire\(",
    }
    for name, pattern in forbidden.items():
        source = (SCRIPTS / name).read_text()
        hits = [m.group(0) for m in re.finditer(pattern, source)]
        assert not hits, f'{name} must stay read-only and side-effect free, found: {hits}'


def test_plugin_version_matches_pyproject():
    assert json.loads(PLUGIN_JSON.read_text())['version'] == _project_version()


def test_marketplace_lists_this_repo_as_the_plugin():
    plugin = json.loads(PLUGIN_JSON.read_text())
    marketplace = json.loads(MARKETPLACE_JSON.read_text())

    assert marketplace['name'] == 'trustsource'
    [entry] = marketplace['plugins']
    assert entry['name'] == plugin['name'] == 'ts-scan-agent'
    assert entry['source'] == '.'
    # plugin.json is the single source for the version; an entry version would only drift.
    assert 'version' not in entry
