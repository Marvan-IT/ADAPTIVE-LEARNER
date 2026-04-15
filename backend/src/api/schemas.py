"""
Pydantic schemas for the Adaptive Learner REST API.
Separate from models.py (which uses dataclasses for the pipeline).
"""

from pydantic import BaseModel, Field


# ── Request Schemas ───────────────────────────────────────────────

class ConceptQuery(BaseModel):
    """Query for concepts with optional mastery context."""
    query: str = Field(..., description="Natural language query, e.g. 'Variables'")
    mastered_concepts: list[str] = Field(
        default_factory=list,
        description="List of concept_ids the child has mastered",
    )
    book_slug: str = Field(default="prealgebra")
    n_results: int = Field(default=3, ge=1, le=10)


class NextConceptsRequest(BaseModel):
    """Request frontier concepts given mastered set."""
    mastered_concepts: list[str] = Field(
        default_factory=list,
        description="List of concept_ids the child has mastered",
    )


class LearningPathRequest(BaseModel):
    """Request a learning path to a target concept."""
    target_concept_id: str = Field(..., description="The concept_id to reach")
    mastered_concepts: list[str] = Field(
        default_factory=list,
        description="List of concept_ids already mastered",
    )


# ── Response Schemas ──────────────────────────────────────────────

class PrerequisiteStatus(BaseModel):
    """Mastery status of a single prerequisite."""
    concept_id: str
    concept_title: str
    mastered: bool


class ConceptImage(BaseModel):
    """An extracted image associated with a concept."""
    filename: str
    url: str
    width: int
    height: int
    image_type: str  # "FORMULA" or "DIAGRAM"
    page: int
    description: str | None = None  # Vision annotation: what the image shows
    relevance: str | None = None    # Vision annotation: pedagogical purpose


class ConceptResult(BaseModel):
    """A single concept from RAG + Graph query."""
    concept_id: str
    concept_title: str
    chapter: str
    section: str
    text: str
    latex: list[str] = Field(default_factory=list)
    images: list[ConceptImage] = Field(default_factory=list)
    distance: float
    prerequisites: list[PrerequisiteStatus]
    all_prerequisites_met: bool
    ready_to_learn: bool


class ConceptQueryResponse(BaseModel):
    """Response for the main RAG + Graph query."""
    query: str
    results: list[ConceptResult]
    mastered_concepts: list[str]


class ConceptDetailResponse(BaseModel):
    """Full detail for a single concept."""
    concept_id: str
    concept_title: str
    chapter: str
    section: str
    text: str
    latex: list[str] = Field(default_factory=list)
    images: list[ConceptImage] = Field(default_factory=list)
    prerequisites: list[str]
    dependents: list[str]


class NextConceptsResponse(BaseModel):
    """Frontier concepts ready to learn."""
    mastered_concepts: list[str]
    ready_to_learn: list[dict]
    locked: list[dict] = Field(default_factory=list)


class GraphInfoResponse(BaseModel):
    """Dependency graph statistics."""
    num_nodes: int
    num_edges: int
    is_dag: bool
    root_concepts: list[str]
    leaf_concepts: list[str]


class GraphNodeInfo(BaseModel):
    """A single node in the graph."""
    concept_id: str
    title: str
    chapter: str
    section: str
    in_degree: int
    out_degree: int


class LearningPathStep(BaseModel):
    """A single step in a learning path."""
    concept_id: str
    concept_title: str
    chapter: str
    section: str


class LearningPathResponse(BaseModel):
    """Ordered learning path to reach a target concept."""
    target: str
    path: list[LearningPathStep]
    total_steps: int


class TopologicalOrderItem(BaseModel):
    """A concept with its depth in the dependency graph."""
    concept_id: str
    concept_title: str
    chapter: str
    section: str
    depth: int
