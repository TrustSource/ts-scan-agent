#!/usr/bin/env node
// Dependency-free Node.js (18+) port of the ts-scan-agent pipeline for the ts-scan-agent Agent
// Skill, for machines that have Node but no Python. Same CLI, same output as scan_concept.py:
// tests/test_skill_scripts.py runs both (and the installable package) on the same fixtures and
// fails on any difference. Keep the three in step when changing detection, rules or text.
//
// Usage: node scan_concept.mjs analyze PATH [--format json|markdown] [--answers FILE] [--level ...]

import fs from 'node:fs';
import path from 'node:path';

const VERSION = '0.7.0';

// --- Inventory (mirrors src/ts_scan_agent/inventory.py) -------------------------------------

const IGNORED_DIRS = new Set([
  '.git', '.hg', '.svn',
  'node_modules', 'vendor', 'venv', '.venv', '__pycache__',
  'dist', 'build', 'target', 'bin', 'obj',
  '.mypy_cache', '.pytest_cache', '.ruff_cache', '.tox',
  'Pods',
]);

const MAX_DEPTH = 6;

const CI_CONFIG_FILES = new Set(['.gitlab-ci.yml', 'Jenkinsfile', 'azure-pipelines.yml']);

const DOCKERFILE_NAMES = new Set(['Dockerfile']);

const MONOREPO_MARKER_FILES = new Set(['pnpm-workspace.yaml', 'lerna.json', 'nx.json', 'rush.json', 'melos.yaml']);

const UNSUPPORTED_ECOSYSTEM_MARKERS = {
  'composer.json': 'PHP (Composer)',
  'Gemfile': 'Ruby (Bundler)',
  'Package.swift': 'Swift (Swift Package Manager)',
  'Podfile': 'iOS (CocoaPods)',
  'mix.exs': 'Elixir (Hex)',
  'stack.yaml': 'Haskell (Stack)',
  'cpanfile': 'Perl (CPAN)',
  'build.zig': 'Zig',
  'elm.json': 'Elm',
};

const UNSUPPORTED_ECOSYSTEM_EXTENSIONS = { '.cabal': 'Haskell (Cabal)' };

const own = (obj, key) => Object.prototype.hasOwnProperty.call(obj, key);

function reEscape(s) {
  return s.replace(/[.*+?^${}()|[\]\\\/\-#&~ ]/g, '\\$&');
}

function globAny(entries, pattern) {
  const regex = new RegExp('^' + translateSegmentGlob(pattern) + '$');
  return entries.some((e) => regex.test(e));
}

// Each check mirrors one ts_scan.pm.*Scanner.accepts(dir), in the order inventory.py asks them.
function detectEcosystems(dir) {
  let entries;
  try {
    entries = fs.readdirSync(dir);
  } catch {
    return [];
  }
  const names = new Set(entries);
  const found = [];
  if (names.has('setup.py') || names.has('pyproject.toml')) found.push('PyPI');
  if (names.has('pom.xml')) found.push('Maven');
  if (names.has('build.gradle') || names.has('build.gradle.kts')) found.push('Gradle');
  if (names.has('package.json')) found.push('Node');
  if (globAny(entries, '*.nuspec') || globAny(entries, '*.*proj')
      || names.has('packages.config') || globAny(entries, '*.sln')) found.push('NuGet');
  if (names.has('Cargo.toml')) found.push('Cargo');
  if (names.has('go.mod')) found.push('Golang');
  if (names.has('pubspec.yaml')) found.push('Dart');
  return found;
}

// gitignore matching: a port of pathspec 0.12's GitWildMatchPattern, which inventory.py uses.
function translateSegmentGlob(pattern) {
  let escape = false;
  let regex = '';
  let i = 0;
  const end = pattern.length;
  while (i < end) {
    const char = pattern[i];
    i += 1;
    if (escape) {
      escape = false;
      regex += reEscape(char);
    } else if (char === '\\') {
      escape = true;
    } else if (char === '*') {
      regex += '[^/]*';
    } else if (char === '?') {
      regex += '[^/]';
    } else if (char === '[') {
      let j = i;
      if (j < end && (pattern[j] === '!' || pattern[j] === '^')) j += 1;
      if (j < end && pattern[j] === ']') j += 1;
      while (j < end && pattern[j] !== ']') j += 1;
      if (j < end) {
        j += 1;
        let expr = '[';
        if (pattern[i] === '!' || pattern[i] === '^') {
          expr += '^';
          i += 1;
        }
        expr += pattern.slice(i, j).replace(/\\/g, '\\\\');
        regex += expr;
        i = j;
      } else {
        regex += '\\[';
      }
    } else {
      regex += reEscape(char);
    }
  }
  if (escape) throw new Error('dangling escape');
  return regex;
}

function gitignorePatternToRegex(raw) {
  let pattern = raw.endsWith('\\ ') ? raw.trimStart() : raw.trim();
  if (!pattern || pattern.startsWith('#') || pattern === '/') return null;

  let include = true;
  if (pattern.startsWith('!')) {
    include = false;
    pattern = pattern.slice(1);
  }

  const segs = pattern.split('/');
  for (let i = segs.length - 1; i > 0; i -= 1) {
    if (segs[i - 1] === '**' && segs[i] === '**') segs.splice(i, 1);
  }

  if (segs.length === 2 && segs[0] === '**' && !segs[1]) return { regex: '^.+/.*$', include };

  if (!segs[0]) {
    segs.shift();
  } else if (segs.length === 1 || (segs.length === 2 && !segs[1])) {
    if (segs[0] !== '**') segs.unshift('**');
  }
  if (!segs.length) return null;
  if (!segs[segs.length - 1] && segs.length > 1) segs[segs.length - 1] = '**';

  const out = ['^'];
  let needSlash = false;
  const end = segs.length - 1;
  for (let i = 0; i < segs.length; i += 1) {
    const seg = segs[i];
    if (seg === '**') {
      if (i === 0 && i === end) {
        out.push('[^/]+(?:/.*)?');
      } else if (i === 0) {
        out.push('(?:.+/)?');
        needSlash = false;
      } else if (i === end) {
        out.push('/.*');
      } else {
        out.push('(?:/.+)?');
        needSlash = true;
      }
    } else if (seg === '*') {
      if (needSlash) out.push('/');
      out.push('[^/]+');
      if (i === end) out.push('(?:/.*)?');
      needSlash = true;
    } else {
      if (needSlash) out.push('/');
      try {
        out.push(translateSegmentGlob(seg));
      } catch {
        return null;
      }
      if (i === end) out.push('(?:/.*)?');
      needSlash = true;
    }
  }
  out.push('$');
  return { regex: out.join(''), include };
}

function loadGitignore(root) {
  let text;
  try {
    text = fs.readFileSync(path.join(root, '.gitignore'), 'utf8');
  } catch {
    return null;
  }
  const spec = [];
  for (const line of text.split(/\r\n|\r|\n/)) {
    const parsed = gitignorePatternToRegex(line);
    if (!parsed) continue;
    try {
      spec.push({ regex: new RegExp(parsed.regex), include: parsed.include });
    } catch {
      // A character class JS can't compile - skip it rather than abort the whole walk.
    }
  }
  return spec;
}

function gitignored(spec, relPath) {
  let matched = false;
  for (const { regex, include } of spec) {
    if (regex.test(relPath)) matched = include;
  }
  return matched;
}

function readJson(file) {
  try {
    return JSON.parse(fs.readFileSync(file, 'utf8'));
  } catch {
    return undefined;
  }
}

function isPlainObject(v) {
  return v !== null && typeof v === 'object' && !Array.isArray(v);
}

// Python truthiness, so the JSON-field checks match the package exactly.
function truthy(v) {
  if (Array.isArray(v)) return v.length > 0;
  if (isPlainObject(v)) return Object.keys(v).length > 0;
  return Boolean(v);
}

function hasNpmWorkspaces(file) {
  const data = readJson(file);
  return isPlainObject(data) && truthy(data.workspaces);
}

const unit = (p, kind, evidence, ecosystem = null) => ({ path: p, kind, ecosystem, evidence });

function isDir(p) {
  try {
    return fs.statSync(p).isDirectory();
  } catch {
    return false;
  }
}

function isSymlink(p) {
  try {
    return fs.lstatSync(p).isSymbolicLink();
  } catch {
    return false;
  }
}

function scanInventory(root, maxDepth = MAX_DEPTH) {
  const spec = loadGitignore(root);
  const units = [];
  const rel = (...parts) => parts.filter(Boolean).join('/') || '.';

  function walk(relDir, depth) {
    const absDir = relDir ? path.join(root, relDir) : root;
    let entries;
    try {
      entries = fs.readdirSync(absDir).sort();
    } catch {
      return;
    }
    let dirnames = entries.filter((e) => isDir(path.join(absDir, e)) && !isSymlink(path.join(absDir, e)));
    let filenames = entries.filter((e) => !dirnames.includes(e) && !isDir(path.join(absDir, e)));

    dirnames = dirnames.filter((d) => !IGNORED_DIRS.has(d));
    if (spec !== null) {
      dirnames = dirnames.filter((d) => !gitignored(spec, rel(relDir, d) + '/'));
      filenames = filenames.filter((f) => !gitignored(spec, rel(relDir, f)));
    }

    if (depth > maxDepth) return;

    const here = rel(relDir);
    const ecosystems = detectEcosystems(absDir);
    for (const name of ecosystems) units.push(unit(here, 'ecosystem', `${name} manifest found`, name));

    if (!ecosystems.length) {
      for (const filename of filenames) {
        const ext = path.extname(filename);
        const display = (own(UNSUPPORTED_ECOSYSTEM_MARKERS, filename) && UNSUPPORTED_ECOSYSTEM_MARKERS[filename])
          || (own(UNSUPPORTED_ECOSYSTEM_EXTENSIONS, ext) && UNSUPPORTED_ECOSYSTEM_EXTENSIONS[ext]);
        if (display) {
          units.push(unit(here, 'unsupported_ecosystem', `${filename} found, no ts-scan scanner for ${display}`, display));
        }
      }
    }

    for (const filename of filenames) {
      if (DOCKERFILE_NAMES.has(filename) || filename.startsWith('Dockerfile.')) {
        units.push(unit(rel(relDir, filename), 'dockerfile', `${filename} found`));
      } else if (MONOREPO_MARKER_FILES.has(filename)) {
        units.push(unit(here, 'monorepo_root', `${filename} found`));
      } else if (filename === 'package.json' && hasNpmWorkspaces(path.join(absDir, filename))) {
        units.push(unit(here, 'monorepo_root', 'package.json "workspaces" field found'));
      } else if (CI_CONFIG_FILES.has(filename)) {
        units.push(unit(rel(relDir, filename), 'ci_config', `${filename} found`));
      }
    }

    if (path.basename(absDir) === '.github' && dirnames.includes('workflows')) {
      const workflows = path.join(absDir, 'workflows');
      let wfEntries = [];
      try {
        wfEntries = fs.readdirSync(workflows).sort();
      } catch {
        wfEntries = [];
      }
      for (const ext of ['.yml', '.yaml']) {
        for (const wf of wfEntries) {
          if (wf.endsWith(ext) && !isDir(path.join(workflows, wf))) {
            units.push(unit(rel(relDir, 'workflows', wf), 'ci_config', 'GitHub Actions workflow found'));
          }
        }
      }
    }

    for (const d of dirnames) walk(relDir ? rel(relDir, d) : d, depth + 1);
  }

  walk('', 0);
  return units;
}

// --- Mapping (mirrors src/ts_scan_agent/mapping.py, no-LLM path) ----------------------------

const DOCKER_TAG_VERSION_RE = /:v?\d+(\.\d+)*([-_][a-zA-Z0-9.]+)?$/;
const DOTTED_VERSION_RE = /(?:^|[-_ ])v?\d+\.\d+(?:\.\d+)?(?:$|[-_ ])/;
const BARE_V_SUFFIX_RE = /[-_]v\d+$/;

function namingWarnings(name) {
  if (DOCKER_TAG_VERSION_RE.test(name) || DOTTED_VERSION_RE.test(name) || BARE_V_SUFFIX_RE.test(name)) {
    return [
      `"${name}" looks like it embeds a version or image tag. Keep TrustSource module `
      + 'names stable across releases (e.g. "api-runtime", not "api-1.4.2" or '
      + '"node-22-alpine") - a version bump would otherwise create a brand-new module and '
      + 'silently lose everything attached to the old one, including muted vulnerabilities '
      + 'and approval history.',
    ];
  }
  return [];
}

function moduleName(p, projectName) {
  if (p === '.' || p === '') return projectName;
  const parts = p.replace(/\/+$/, '').split('/');
  return parts[parts.length - 1];
}

function scanCommand(p, name, projectName) {
  const target = p === '.' || p === '' ? '.' : p;
  return `ts-scan scan ${target} -o ${name}.json && `
    + `ts-scan upload --project-name "${projectName}" --api-key "$TS_API_KEY" ${name}.json`;
}

function dockerScanCommand(name, projectName) {
  return `ts-scan scan --use-syft docker:<image> -o ${name}.json && `
    + `ts-scan upload --project-name "${projectName}" --api-key "$TS_API_KEY" ${name}.json`;
}

function looksIndependentlyReleased(root, ecosystem, relPath) {
  if (ecosystem !== 'Node') return false;
  const data = readJson(path.join(root, relPath, 'package.json'));
  if (!isPlainObject(data)) return false;
  return truthy(data.version) && !truthy(own(data, 'private') ? data.private : false);
}

function candidate(name, p, candidateType, command, confidence, rationale, openQuestion = null, ecosystem = null) {
  return {
    name,
    path: p,
    candidate_type: candidateType,
    ecosystem,
    ts_scan_command: command,
    confidence,
    rationale,
    open_question: openQuestion,
    warnings: [],
  };
}

function buildCandidates(projectName, root, units) {
  const monorepoRoots = new Set(units.filter((u) => u.kind === 'monorepo_root').map((u) => u.path));
  const candidates = [];

  for (const u of units.filter((x) => x.kind === 'ecosystem')) {
    const { path: p, ecosystem, evidence } = u;
    const name = moduleName(p, projectName);
    const isNested = !(p === '.' || p === '');
    const underMonorepo = [...monorepoRoots].some((r) => r === '.' || p === r || p.startsWith(r + '/'));
    const command = scanCommand(p, name, projectName);

    if (!isNested) {
      candidates.push(candidate(name, p, 'module', command, 0.95, `${evidence}; root of the repository`, null, ecosystem));
    } else if (underMonorepo && ecosystem && looksIndependentlyReleased(root, ecosystem, p)) {
      candidates.push(candidate(
        name, p, 'linked_module', command, 0.75,
        `${evidence} in a monorepo workspace; its manifest declares its own `
        + 'version and is not marked private, suggesting it is published/released '
        + 'independently - consider scanning it as its own TrustSource project and '
        + 'linking the release into this project as a Linked Module',
        `Does "${p}" get published/released on its own (npm registry, `
        + 'internal registry, separate versioning)? If yes, set it up as its own '
        + 'TrustSource project and link its release here instead of scanning it as '
        + 'a plain Module.',
        ecosystem,
      ));
    } else if (underMonorepo) {
      candidates.push(candidate(
        name, p, 'module', command, 0.9,
        `${evidence} inside a detected monorepo workspace, so it is a `
        + "separately scanned package per ts-scan's documented monorepo pattern "
        + '(scan each workspace package individually, never the monorepo root)',
        null, ecosystem,
      ));
    } else {
      candidates.push(candidate(
        name, p, 'module', command, 0.5,
        `${evidence} in a nested directory with no monorepo marker found - could `
        + 'be its own module, or just a vendored/example subfolder of the parent module',
        `Is "${p}" released/deployed separately from the rest of the repo? `
        + "If yes, it should be its own Module; if no, fold it into the parent module's "
        + 'scan instead.',
        ecosystem,
      ));
    }
  }

  for (const u of units.filter((x) => x.kind === 'dockerfile')) {
    const dirPath = u.path.includes('/') ? u.path.slice(0, u.path.lastIndexOf('/')) : '.';
    const name = `${moduleName(dirPath, projectName)}-container`;
    candidates.push(candidate(
      name, u.path, 'infrastructure_module', dockerScanCommand(name, projectName), 0.4,
      `${u.evidence}; defaulting to Infrastructure Module per TrustSource's `
      + 'container-scanning guidance, but this is only a default, not a judgment',
      `Is the image built from "${u.path}" your own deployable service, or `
      + 'runtime infrastructure (base image, sidecar, etc.)? This changes whether '
      + 'it should be a Module or an Infrastructure Module.',
    ));
  }

  for (const c of candidates) c.warnings = namingWarnings(c.name);
  return candidates;
}

// --- Ecosystem proposals (mirrors src/ts_scan_agent/ecosystem_proposals.py, no-LLM path) ----

const ECOSYSTEM_FACTS = {
  'PHP (Composer)':
    'Registry: Packagist. Manifest: composer.json (dependency constraints). '
    + 'Lockfile: composer.lock (exact resolved versions and hashes).',
  'Ruby (Bundler)':
    'Registry: RubyGems. Manifest: Gemfile (dependency constraints, Ruby DSL). '
    + 'Lockfile: Gemfile.lock (exact resolved versions and dependency graph).',
  'Swift (Swift Package Manager)':
    'No central registry - dependencies resolve directly from git repository URLs and '
    + 'tags. Manifest: Package.swift (Swift source). Lockfile: Package.resolved (JSON, '
    + 'pinned revisions). Prior art: TrustSource previously shipped a standalone SPM plugin, '
    + 'github.com/TrustSource/ts-spm (deprecated, unmaintained) - its scanner core is just '
    + '`swift package show-dependencies --format json` plus a recursive walk of the result, '
    + 'directly portable to a ts_scan.pm.swift.SwiftScanner.',
  'iOS (CocoaPods)':
    'Registry: the CocoaPods Specs CDN (no TrustSource plugin has ever covered this - '
    + 'verified against the full github.com/trustsource and github.com/eacg-gmbh org history, '
    + '2026-08-26). Manifest: Podfile (Ruby DSL, dependency constraints). '
    + 'Lockfile: Podfile.lock (YAML-like, exact resolved pod versions) - the more reliable '
    + 'thing to parse, similar to how other lockfile-based scanners in this codebase work.',
  'Elixir (Hex)':
    'Registry: Hex.pm. Manifest: mix.exs (Elixir source, deps function). '
    + 'Lockfile: mix.lock.',
  'Haskell (Stack)':
    'Registry: Hackage, via Stackage snapshots. Manifest: package.yaml or *.cabal, plus '
    + 'stack.yaml (resolver/snapshot pinning). Lockfile: stack.yaml.lock.',
  'Haskell (Cabal)':
    'Registry: Hackage. Manifest: *.cabal. Lockfile (optional): cabal.project.freeze '
    + '(pins exact versions).',
  'Perl (CPAN)':
    'Registry: CPAN / MetaCPAN. Manifest: cpanfile. '
    + 'Lockfile: cpanfile.snapshot (via Carton).',
  'Zig':
    'No central registry - dependencies resolve from git/tarball URLs with content '
    + 'hashes. Manifest: build.zig (build script) plus build.zig.zon (dependency manifest, '
    + 'newer Zig versions).',
  'Elm':
    'Registry: package.elm-lang.org. Manifest: elm.json (dependency version ranges, '
    + 'fully pinned after `elm install`; the compiler enforces semantic versioning). '
    + 'No separate lockfile.',
};

const DISCLOSURE_NOTE = '\n\n---\n*Drafted automatically by [ts-scan-agent]'
  + '(https://github.com/TrustSource/ts-scan-agent) from a real repository that hit this '
  + 'gap. Please review and edit before submitting - this is a starting point, not a '
  + 'finished spec.*';

function buildProposals(units) {
  const pathsByEcosystem = new Map();
  for (const u of units) {
    if (u.kind !== 'unsupported_ecosystem' || !u.ecosystem) continue;
    if (!pathsByEcosystem.has(u.ecosystem)) pathsByEcosystem.set(u.ecosystem, []);
    const paths = pathsByEcosystem.get(u.ecosystem);
    if (!paths.includes(u.path)) paths.push(u.path);
  }

  const proposals = [];
  for (const [ecosystem, paths] of pathsByEcosystem) {
    const body = [
      `\`ts-scan\` has no dependency-tree scanner for **${ecosystem}** yet.`,
      '',
      `Found in this repository at: ${paths.map((p) => `\`${p}\``).join(', ')}`,
      '',
      '### Ecosystem facts',
      own(ECOSYSTEM_FACTS, ecosystem)
        ? ECOSYSTEM_FACTS[ecosystem]
        : 'No static facts recorded for this ecosystem yet - please fill in the package '
          + 'registry, manifest format and lockfile format.',
      DISCLOSURE_NOTE,
    ].join('\n');
    proposals.push({
      ecosystem,
      manifest_paths: paths,
      title: `Add ts-scan support for ${ecosystem}`,
      body,
      existing_issue: null,
    });
  }
  return proposals;
}

// --- Answers (mirrors src/ts_scan_agent/interview.py apply_answers) --------------------------

const DOCKERFILE_ANSWERS = ['module', 'infrastructure_module'];
const YES_NO_ANSWERS = ['yes', 'no'];

class UsageFailure extends Error {}

function pyRepr(v) {
  if (typeof v === 'string') return `'${v}'`;
  if (v === true) return 'True';
  if (v === false) return 'False';
  if (v === null) return 'None';
  return JSON.stringify(v);
}

// Inline JSON (starts with "{") or a JSON file, like the package's --answers.
function loadAnswers(value) {
  let data;
  let source;
  if (value.trimStart().startsWith('{')) {
    source = 'inline --answers JSON';
    try {
      data = JSON.parse(value);
    } catch (err) {
      throw new UsageFailure(`Could not parse ${source}: ${err.message}`);
    }
  } else {
    source = `--answers file ${value}`;
    try {
      data = JSON.parse(fs.readFileSync(value, 'utf8'));
    } catch (err) {
      throw new UsageFailure(`Could not read ${source}: ${err.message}`);
    }
  }
  if (!isPlainObject(data)) {
    throw new UsageFailure(
      `${source} must contain a map from candidate path to answer, `
      + 'e.g. {"tools/helper": "yes", "Dockerfile": "module"}',
    );
  }
  return data;
}

function parseAnswer(c, value) {
  let allowed;
  if (c.candidate_type === 'infrastructure_module') {
    if (typeof value === 'string' && DOCKERFILE_ANSWERS.includes(value)) return value;
    allowed = DOCKERFILE_ANSWERS;
  } else {
    if (typeof value === 'boolean') return value;
    if (typeof value === 'string' && YES_NO_ANSWERS.includes(value.toLowerCase())) return value.toLowerCase() === 'yes';
    allowed = YES_NO_ANSWERS;
  }
  throw new UsageFailure(`Invalid answer ${pyRepr(value)} for "${c.path}" - expected one of: ${allowed.join(', ')}`);
}

function resolve(concept, c, answer) {
  const parts = c.path.replace(/\/+$/, '').split('/');
  const name = parts[parts.length - 1];

  if (c.candidate_type === 'infrastructure_module') {
    c.candidate_type = answer;
    c.rationale = answer === 'module'
      ? `${name} found; the user confirmed the image is their own deployable `
        + 'service, so it is a Module'
      : `${name} found; the user confirmed the image is runtime infrastructure `
        + '(base image, sidecar, etc.), so it is an Infrastructure Module';
  } else if (c.candidate_type === 'linked_module') {
    if (answer) {
      c.rationale = `${c.ecosystem} manifest found in a monorepo workspace; the user `
        + 'confirmed it is published/released on its own - set it up as its own '
        + 'TrustSource project and link its release into this project as a Linked Module';
    } else {
      c.candidate_type = 'module';
      c.rationale = `${c.ecosystem} manifest found in a monorepo workspace; the user `
        + 'confirmed it is not released on its own, so it is scanned as a Module of '
        + 'this project';
    }
  } else if (answer) {
    c.rationale = `${c.ecosystem} manifest found in a nested directory; the user confirmed `
      + 'it is released/deployed separately, so it is its own Module';
  } else {
    // Belongs to its parent: no scan of its own, so it leaves `candidates`.
    concept.candidates.splice(concept.candidates.indexOf(c), 1);
    concept.folded_into_parent.push({ name: c.name, path: c.path, ecosystem: c.ecosystem });
    return;
  }
  c.confidence = 1.0;
  c.open_question = null;
}

function applyAnswers(concept, answers) {
  const pending = new Map(concept.candidates.filter((c) => c.open_question !== null).map((c) => [c.path, c]));
  const unknown = Object.keys(answers).filter((p) => !pending.has(p)).sort();
  if (unknown.length) {
    const openPaths = [...pending.keys()].sort().map((p) => `"${p}"`).join(', ') || 'none';
    throw new UsageFailure(
      '--answers names path(s) with no open question: '
      + `${unknown.map(pyRepr).join(', ')}. Open questions exist for: ${openPaths}`,
    );
  }
  const parsed = Object.entries(answers).map(([p, v]) => [p, parseAnswer(pending.get(p), v)]);
  for (const [p, answer] of parsed) resolve(concept, pending.get(p), answer);
}

// --- Render (mirrors src/ts_scan_agent/render.py) --------------------------------------------

const LEVEL_CHOICES = ['beginner', 'intermediate', 'expert'];
const FORMAT_CHOICES = ['markdown', 'json'];

const SECTION_TITLES = [
  ['module', 'Modules'],
  ['infrastructure_module', 'Infrastructure Modules'],
  ['linked_module', 'Linked Module candidates'],
];

const NAMING_TIP = '> **Naming tip:** `ts-scan scan`/`upload` have no flag to set the module name - '
  + 'TrustSource auto-derives it from what ts-scan detects (the package name, or for a '
  + 'container scan, the image reference *including its tag*, e.g. `node:22-alpine`). '
  + 'Check the module name TrustSource assigns after the first scan and rename it if it '
  + 'looks version-y **before** the next release: TrustSource keys a module by name, so a '
  + 'name that changes with every release creates a brand-new module each time, silently '
  + 'losing everything attached to the old one - whitelist decisions, muted '
  + 'vulnerabilities, approval history. (A pinnable module ID for `scan`/`upload` is '
  + 'planned upstream - see ARCHITECTURE.md.)';

const GETTING_STARTED = `## Getting started

New to TrustSource? This report only covers *what* to scan and *which command* to run for
each piece (below). Here's the rest of the journey, in order - steps 1-3 and 5-8 happen in
the TrustSource app itself, not on the command line:

1. **Create a TrustSource account and project**, if you don't have one yet
   ([app.trustsource.io](https://app.trustsource.io)).
2. **Create an API key**: **Administration → Scanners & API Keys** → *Create API Key*. It's
   shown once - copy it somewhere safe, e.g. \`export TS_API_KEY="..."\` in your shell for now.
3. **Install \`ts-scan\`**, if you haven't: \`pip install ts-scan\`.
4. **Run the command(s) below**, one per unit listed in this report.
5. **Open the module in the app.** It's created automatically on first upload - you don't
   create it by hand. Give it a minute, then check its **Components** tab.
6. **Look at the traffic-light status.** Yellow or red on a first scan is normal - it means
   there's something to look at (a license, a vulnerability), not that something broke.
7. **Ask your project or compliance manager for an approval** once the status looks good
   enough to ship - that's a deliberate governance step, not automatic.
8. **Create a release** from the approved state. This is what TrustSource keeps watching for
   new vulnerabilities going forward, and what you'd hand a customer as an SBOM.

Full walkthrough: [ts-scan/recipes/01-first-module-to-sbom](https://trustsource.github.io/ts-scan).

## Concepts used in this report

- **Module** - one deployable piece of your software (a service, a library, a container
  image) that gets its own bill of materials and its own approval/release history.
- **Infrastructure Module** - a runtime dependency you don't build yourself (a database, a
  message broker, a base image) - tracked the same way, kept conceptually separate from
  what your team actually ships.
- **Linked Module** - when a Module has its own release cycle (e.g. a shared library with
  its own version), that release can be linked into another project instead of scanned a
  second time there.
`;

// Python's shlex.quote.
function shellQuote(s) {
  if (!s) return "''";
  if (!/[^\w@%+=:,./-]/.test(s)) return s;
  return "'" + s.replace(/'/g, "'\"'\"'") + "'";
}

function renderCandidate(c, level) {
  const lines = [`### \`${c.path}\` — ${c.name}`];
  if (level === 'expert') {
    lines.push('- Recommended command:');
    lines.push(`  \`\`\`bash\n  ${c.ts_scan_command}\n  \`\`\``);
    return lines.join('\n');
  }
  if (c.ecosystem) lines.push(`- Ecosystem: ${c.ecosystem}`);
  lines.push(`- Confidence: ${Math.round(c.confidence * 100)}%`);
  lines.push(`- Rationale: ${c.rationale}`);
  lines.push('- Recommended command:');
  lines.push(`  \`\`\`bash\n  ${c.ts_scan_command}\n  \`\`\``);
  for (const warning of c.warnings) lines.push(`- ⚠️ **Naming:** ${warning}`);
  if (c.open_question) lines.push(`- ⚠️ **Open question:** ${c.open_question}`);
  return lines.join('\n');
}

function renderEcosystemProposal(p, issueRepo, level) {
  const lines = [`### ${p.ecosystem}`];
  lines.push(`- Found at: ${p.manifest_paths.map((x) => `\`${x}\``).join(', ')}`);
  const titleArg = shellQuote(p.title);
  const bodyArg = shellQuote(p.body);
  if (level === 'expert') {
    lines.push(`  \`\`\`bash\n  gh issue create --repo ${issueRepo} --title ${titleArg} `
      + `--body ${bodyArg} --label enhancement\n  \`\`\``);
    return lines.join('\n');
  }
  lines.push('- No existing issue found for this ecosystem.');
  lines.push('');
  lines.push(`**Draft title:** ${p.title}`);
  lines.push('');
  lines.push(p.body);
  lines.push('');
  lines.push(
    'File it yourself with:\n'
    + '  ```bash\n'
    + `  gh issue create --repo ${issueRepo} --title ${titleArg} --body ${bodyArg} `
    + '--label enhancement\n'
    + '  ```\n'
    + '  or re-run with `--file-issues` to be walked through review + filing.',
  );
  return lines.join('\n');
}

function renderMarkdown(concept, units, issueRepo, level) {
  const lines = [`# TrustSource Scan Concept: ${concept.project_name}`, '', `Generated for \`${concept.source_path}\`.`, ''];

  if (level === 'beginner') {
    lines.push(GETTING_STARTED);
    lines.push('');
  }

  if (level !== 'expert') {
    lines.push(`Create one TrustSource project (\`${concept.project_name}\`) and add the following units to it:`);
    lines.push('');
    lines.push(NAMING_TIP);
    lines.push('');
  }

  for (const [candidateType, title] of SECTION_TITLES) {
    const items = concept.candidates.filter((c) => c.candidate_type === candidateType);
    if (!items.length) continue;
    lines.push(`## ${title}`);
    lines.push('');
    const sorted = [...items].sort((a, b) => (a.path < b.path ? -1 : a.path > b.path ? 1 : 0));
    for (const c of sorted) {
      lines.push(renderCandidate(c, level));
      lines.push('');
    }
  }

  if (concept.folded_into_parent.length) {
    lines.push('## Folded into parent modules');
    lines.push('');
    if (level !== 'expert') {
      lines.push('You said these belong to their parent module, so they get no scan of their own:');
      lines.push('');
    }
    const folded = [...concept.folded_into_parent].sort((a, b) => (a.path < b.path ? -1 : a.path > b.path ? 1 : 0));
    for (const f of folded) lines.push(`- \`${f.path}\` - ${f.name}`);
    lines.push('');
  }

  const openQuestions = concept.candidates.filter((c) => c.open_question !== null);
  if (openQuestions.length) {
    lines.push('## Still open');
    lines.push('');
    if (level === 'expert') {
      for (const c of openQuestions) lines.push(`- \`${c.path}\``);
    } else {
      lines.push(
        'The following items could not be classified with confidence and were not '
        + 'resolved (re-run interactively, or pass `--answers FILE` mapping each path '
        + 'below to its answer, to resolve them):',
      );
      lines.push('');
      for (const c of openQuestions) lines.push(`- \`${c.path}\` — ${c.open_question}`);
    }
    lines.push('');
  }

  const ciUnits = units.filter((u) => u.kind === 'ci_config');
  if (ciUnits.length) {
    lines.push('## Detected CI/CD configuration');
    lines.push('');
    if (level !== 'expert') {
      lines.push('Wire the recommended `ts-scan` commands above into these pipelines so scans run on every build:');
      lines.push('');
    }
    for (const u of ciUnits) lines.push(`- \`${u.path}\``);
    lines.push('');
  }

  if (units.some((u) => u.kind === 'monorepo_root') && level !== 'expert') {
    lines.push('## Monorepo markers detected');
    lines.push('');
    lines.push(
      'ts-scan has no built-in monorepo mode - scan each workspace package individually '
      + '(as reflected in the Modules above), never the monorepo root.',
    );
    lines.push('');
  }

  if (concept.ecosystem_proposals.length) {
    lines.push('## Unsupported ecosystems detected');
    lines.push('');
    if (level !== 'expert') {
      lines.push(
        'ts-scan has no scanner for these yet. A proposal for each is drafted below - '
        + 'review it (nothing is ever filed on GitHub automatically):',
      );
      lines.push('');
    }
    for (const p of concept.ecosystem_proposals) {
      lines.push(renderEcosystemProposal(p, issueRepo, level));
      lines.push('');
    }
  }

  return lines.join('\n');
}

// --- CLI -------------------------------------------------------------------------------------

const USAGE = 'usage: scan_concept.mjs analyze PATH [--level {beginner,intermediate,expert}] '
  + '[--project NAME] [--answers FILE|JSON] [--format {markdown,json}] '
  + '[--propose-issues | --no-propose-issues] [--issue-repo REPO] [-o FILE]';

function parseArgs(argv) {
  if (argv[0] === '--version') return { version: true };
  if (argv[0] === '-h' || argv[0] === '--help') return { help: true };
  if (argv[0] !== 'analyze') throw new UsageFailure(USAGE);

  const valued = { '--level': 'level', '--project': 'project', '--answers': 'answers', '--format': 'format', '--issue-repo': 'issueRepo', '--output': 'output', '-o': 'output' };
  const opts = { level: 'beginner', format: 'markdown', proposeIssues: true, issueRepo: 'trustsource/ts-scan' };
  const positional = [];
  for (let i = 1; i < argv.length; i += 1) {
    let arg = argv[i];
    let inline;
    if (arg.startsWith('--') && arg.includes('=')) {
      [arg, inline] = [arg.slice(0, arg.indexOf('=')), arg.slice(arg.indexOf('=') + 1)];
    }
    if (arg === '--propose-issues') opts.proposeIssues = true;
    else if (arg === '--no-propose-issues') opts.proposeIssues = false;
    else if (arg === '-h' || arg === '--help') return { help: true };
    else if (own(valued, arg)) {
      const value = inline !== undefined ? inline : argv[++i];
      if (value === undefined) throw new UsageFailure(`argument ${arg}: expected one argument`);
      opts[valued[arg]] = value;
    } else if (arg.startsWith('-') && arg !== '-') throw new UsageFailure(`unrecognized arguments: ${arg}`);
    else positional.push(arg);
  }
  if (positional.length !== 1) throw new UsageFailure(`${USAGE}\nexpected exactly one PATH`);
  if (!LEVEL_CHOICES.includes(opts.level)) throw new UsageFailure(`argument --level: invalid choice: '${opts.level}'`);
  if (!FORMAT_CHOICES.includes(opts.format)) throw new UsageFailure(`argument --format: invalid choice: '${opts.format}'`);
  opts.path = positional[0];
  return opts;
}

function main(argv) {
  let args;
  try {
    args = parseArgs(argv);
  } catch (err) {
    process.stderr.write(`${err.message}\n`);
    return 2;
  }
  if (args.version) {
    process.stdout.write(`ts-scan-agent skill ${VERSION}\n`);
    return 0;
  }
  if (args.help) {
    process.stdout.write(`${USAGE}\n`);
    return 0;
  }

  let concept;
  let units;
  try {
    if (!isDir(args.path)) throw new UsageFailure(`Directory "${args.path}" does not exist.`);
    const root = fs.realpathSync(args.path);
    const answers = args.answers ? loadAnswers(args.answers) : null;
    const projectName = args.project || path.basename(root);

    process.stderr.write(`Scanning ${root} ...\n`);
    units = scanInventory(root);
    concept = {
      project_name: projectName,
      source_path: root,
      candidates: buildCandidates(projectName, root, units),
      folded_into_parent: [],
      ecosystem_proposals: [],
    };
    if (answers !== null) applyAnswers(concept, answers);
    if (args.proposeIssues) concept.ecosystem_proposals = buildProposals(units);
  } catch (err) {
    if (!(err instanceof UsageFailure)) throw err;
    process.stderr.write(`Error: ${err.message}\n`);
    return 1;
  }

  const report = args.format === 'json'
    ? JSON.stringify(concept, null, 2)
    : renderMarkdown(concept, units, args.issueRepo, args.level);

  if (args.output) {
    fs.writeFileSync(args.output, report, 'utf8');
    process.stderr.write(`Wrote scan concept to ${args.output}\n`);
  } else {
    process.stdout.write(`${report}\n`);
  }
  return 0;
}

process.exitCode = main(process.argv.slice(2));
