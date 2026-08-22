import typing as t

from pydantic import BaseModel, Field


class DetectedUnit(BaseModel):
    """A single piece of evidence found during Inventory, before any Module/Infra/Linked
    judgment has been made about it."""

    path: str
    kind: t.Literal['ecosystem', 'dockerfile', 'ci_config', 'monorepo_root']
    ecosystem: t.Optional[str] = None
    evidence: str


class Candidate(BaseModel):
    """A proposed TrustSource unit (Module, Infrastructure Module or Linked Module) for one
    DetectedUnit, produced by the Mapping step and optionally refined by the Interview step."""

    name: str
    path: str
    candidate_type: t.Literal['module', 'infrastructure_module', 'linked_module']
    ecosystem: t.Optional[str] = None
    ts_scan_command: str
    confidence: float = Field(ge=0.0, le=1.0)
    rationale: str
    open_question: t.Optional[str] = None


class ScanConcept(BaseModel):
    """The root object handed to the Renderer: one TrustSource project made up of candidate
    Modules / Infrastructure Modules / Linked Modules."""

    project_name: str
    source_path: str
    candidates: t.List[Candidate] = Field(default_factory=list)

    @property
    def low_confidence_candidates(self) -> t.List[Candidate]:
        return [c for c in self.candidates if c.open_question is not None]
