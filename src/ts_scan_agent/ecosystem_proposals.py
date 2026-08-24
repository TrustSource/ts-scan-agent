import typing as t

from .model import DetectedUnit, EcosystemProposal
from .llm import LLMClient, NullLLMClient

# Static baseline facts, always available with no LLM required - keys must match the display
# names produced in inventory.py's UNSUPPORTED_ECOSYSTEM_MARKERS/_EXTENSIONS.
ECOSYSTEM_FACTS = {
    'PHP (Composer)':
        'Registry: Packagist. Manifest: composer.json (dependency constraints). '
        'Lockfile: composer.lock (exact resolved versions and hashes).',
    'Ruby (Bundler)':
        'Registry: RubyGems. Manifest: Gemfile (dependency constraints, Ruby DSL). '
        'Lockfile: Gemfile.lock (exact resolved versions and dependency graph).',
    'Swift (Swift Package Manager)':
        'No central registry - dependencies resolve directly from git repository URLs and '
        'tags. Manifest: Package.swift (Swift source). Lockfile: Package.resolved (JSON, '
        'pinned revisions).',
    'Elixir (Hex)':
        'Registry: Hex.pm. Manifest: mix.exs (Elixir source, deps function). '
        'Lockfile: mix.lock.',
    'Haskell (Stack)':
        'Registry: Hackage, via Stackage snapshots. Manifest: package.yaml or *.cabal, plus '
        'stack.yaml (resolver/snapshot pinning). Lockfile: stack.yaml.lock.',
    'Haskell (Cabal)':
        'Registry: Hackage. Manifest: *.cabal. Lockfile (optional): cabal.project.freeze '
        '(pins exact versions).',
    'Perl (CPAN)':
        'Registry: CPAN / MetaCPAN. Manifest: cpanfile. '
        'Lockfile: cpanfile.snapshot (via Carton).',
    'Zig':
        'No central registry - dependencies resolve from git/tarball URLs with content '
        'hashes. Manifest: build.zig (build script) plus build.zig.zon (dependency manifest, '
        'newer Zig versions).',
    'Elm':
        'Registry: package.elm-lang.org. Manifest: elm.json (dependency version ranges, '
        'fully pinned after `elm install`; the compiler enforces semantic versioning). '
        'No separate lockfile.',
}

ENRICHMENT_SCHEMA = {
    'type': 'object',
    'properties': {
        'suggested_approach': {'type': 'string'},
        'similar_scanner': {'type': 'string'},
    },
    'required': ['suggested_approach', 'similar_scanner'],
    'additionalProperties': False,
}

DISCLOSURE_NOTE = (
    '\n\n---\n*Drafted automatically by [ts-scan-agent]'
    '(https://github.com/TrustSource/ts-scan-agent) from a real repository that hit this '
    'gap. Please review and edit before submitting - this is a starting point, not a '
    'finished spec.*'
)


def _build_body(ecosystem: str, manifest_paths: t.List[str], llm: LLMClient) -> str:
    lines = [
        f'`ts-scan` has no dependency-tree scanner for **{ecosystem}** yet.',
        '',
        f'Found in this repository at: {", ".join(f"`{p}`" for p in manifest_paths)}',
        '',
        '### Ecosystem facts',
        ECOSYSTEM_FACTS.get(
            ecosystem,
            'No static facts recorded for this ecosystem yet - please fill in the package '
            'registry, manifest format and lockfile format.',
        ),
    ]

    enrichment = llm.judge(
        prompt=(
            f'ts-scan (github.com/trustsource/ts-scan) has package-manager scanners for '
            f'PyPI, Maven, Gradle, npm, NuGet, Cargo, Go and Dart, each a subclass of its '
            f'Scanner ABC implementing accepts(path) and scan(path). Suggest, in one short '
            f'paragraph, how a new scanner for {ecosystem} could work (what to parse, how to '
            f'resolve dependency versions), and name which of the existing scanners above it '
            f'would most resemble in approach.'
        ),
        schema=ENRICHMENT_SCHEMA,
    )
    if enrichment:
        lines += [
            '',
            '### Suggested approach',
            enrichment['suggested_approach'],
            f'(Closest existing precedent: {enrichment["similar_scanner"]} scanner.)',
        ]

    lines.append(DISCLOSURE_NOTE)
    return '\n'.join(lines)


def build_proposals(units: t.List[DetectedUnit],
                     llm: t.Optional[LLMClient] = None) -> t.List[EcosystemProposal]:
    llm = llm or NullLLMClient()

    manifest_paths_by_ecosystem: t.Dict[str, t.List[str]] = {}
    for unit in units:
        if unit.kind != 'unsupported_ecosystem' or not unit.ecosystem:
            continue
        manifest_paths_by_ecosystem.setdefault(unit.ecosystem, [])
        if unit.path not in manifest_paths_by_ecosystem[unit.ecosystem]:
            manifest_paths_by_ecosystem[unit.ecosystem].append(unit.path)

    proposals = []
    for ecosystem, manifest_paths in manifest_paths_by_ecosystem.items():
        proposals.append(EcosystemProposal(
            ecosystem=ecosystem,
            manifest_paths=manifest_paths,
            title=f'Add ts-scan support for {ecosystem}',
            body=_build_body(ecosystem, manifest_paths, llm),
        ))

    return proposals
