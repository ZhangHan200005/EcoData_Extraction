"""Typed API contracts shared by parsing, retrieval, and evaluation."""

from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


ScreeningStatus = Literal["usable", "relative", "nodata", "failed"]


class VariableSpec(BaseModel):
    name: str
    label: str
    synonyms: list[str] = Field(default_factory=list)
    canonical_unit: str = ""


class ContextFieldSpec(BaseModel):
    name: str
    label: str
    synonyms: list[str] = Field(default_factory=list)


class ProjectSpec(BaseModel):
    version: str = "1.1"
    brief: str
    domain: str = "生态与环境科学"
    target_variables: list[VariableSpec] = Field(default_factory=list)
    required_context: list[ContextFieldSpec] = Field(default_factory=list)
    optional_context: list[ContextFieldSpec] = Field(default_factory=list)
    accepted_sources: list[str] = Field(
        default_factory=lambda: ["text", "table", "figure"]
    )
    exclusions: list[str] = Field(default_factory=list)
    interpretation_warnings: list[str] = Field(default_factory=list)


class RequirementInput(BaseModel):
    brief: str = Field(min_length=12, max_length=8000)


class BlockRecord(BaseModel):
    block_id: str
    document_id: str
    ordinal: int
    page: int
    section: str
    kind: str
    text: str
    bbox: list[float] = Field(default_factory=list)
    raw_text: str = ""
    parent_id: str = ""
    parent_text: str = ""
    chunk_index: int = Field(default=0, ge=0)
    chunk_count: int = Field(default=1, ge=1)


class VisualAssetRecord(BaseModel):
    asset_id: str
    document_id: str
    page: int = Field(ge=1)
    kind: Literal["figure", "table", "image"]
    caption: str = ""
    bbox: list[float] = Field(default_factory=list)
    detection_method: str
    confidence: float = Field(ge=0, le=1)
    summary: str
    has_structured_content: bool = False
    digitization_status: Literal[
        "not_assessed", "candidate", "not_suitable", "digitized"
    ] = "not_assessed"
    parser_backend: str
    parser_version: str


class DocumentRecord(BaseModel):
    document_id: str
    sha256: str
    filename: str
    source_path: str
    title: str
    publication_year: Optional[int] = None
    language: str
    page_count: int
    text_char_count: int
    parser_status: str
    parser_warnings: list[str] = Field(default_factory=list)
    parser_version: str
    parser_backend: str = "pdfplumber"
    parse_elapsed_ms: float = Field(default=0, ge=0)
    screening_status: ScreeningStatus = "failed"
    screening_reasons: list[str] = Field(default_factory=list)
    missing_required_fields: list[str] = Field(default_factory=list)


class SyncResult(BaseModel):
    parsed: int
    reused: int
    failed: int
    documents: list[DocumentRecord]


class RetrievalRequest(BaseModel):
    document_id: str
    field_name: str
    k: int = Field(default=8, ge=1, le=30)


class RetrievalHit(BaseModel):
    rank: int
    block: BlockRecord
    score: float
    score_components: dict[str, float]
    matched_terms: list[str] = Field(default_factory=list)
    is_gold: bool = False
    parent_context: str = ""
    context_block_ids: list[str] = Field(default_factory=list)


class RetrievalBackendMetadata(BaseModel):
    """Versioned identity for the vector-producing retrieval backend."""

    backend: str
    backend_version: str
    model: str
    model_version: str
    dimensions: int = Field(ge=1)
    is_neural: bool


class EmbeddingCacheKey(BaseModel):
    """Content- and version-addressed identity for one cached block vector."""

    cache_key: str
    cache_key_version: str
    document_sha256: str
    block_id: str
    normalized_text_sha256: str
    backend: str
    backend_version: str
    model: str
    model_version: str
    dimensions: int = Field(ge=1)
    parameters_sha256: str


class RetrievalCacheStats(BaseModel):
    enabled: bool
    hits: int = Field(ge=0)
    misses: int = Field(ge=0)
    writes: int = Field(ge=0)


class RetrievalResponse(BaseModel):
    run_id: str
    document_id: str
    field_name: str
    query: str
    retrieval_version: str
    backend: RetrievalBackendMetadata
    parameters: dict[str, Any]
    query_count: int = 1
    total_blocks: int
    elapsed_ms: float = Field(ge=0)
    cache: RetrievalCacheStats
    hits: list[RetrievalHit]


class RetrievalComparisonMetrics(BaseModel):
    gold_count: int = Field(ge=0)
    first_gold_rank: Optional[int] = Field(default=None, ge=1)
    hit_at_k: Optional[float] = Field(default=None, ge=0, le=1)
    recall_at_k: Optional[float] = Field(default=None, ge=0, le=1)
    reciprocal_rank: Optional[float] = Field(default=None, ge=0, le=1)


class RetrievalComparisonItem(BaseModel):
    strategy: Literal["bm25-only", "hashing-hybrid", "e5-hybrid"]
    label: str
    status: Literal["available", "unavailable"]
    retrieval: Optional[RetrievalResponse] = None
    metrics: Optional[RetrievalComparisonMetrics] = None
    error: str = ""


class RetrievalComparisonResponse(BaseModel):
    comparison_id: str
    document_id: str
    field_name: str
    query: str
    k: int = Field(ge=1, le=30)
    gold_status: Literal["verified"] = "verified"
    items: list[RetrievalComparisonItem]


class GoldEvidenceInput(BaseModel):
    document_id: str
    field_name: str
    block_id: str
    status: Literal["draft", "verified"] = "verified"
    note: str = ""


class GoldEvidenceRecord(GoldEvidenceInput):
    gold_id: str
    created_at: str


class VisualEvidenceAnnotationInput(BaseModel):
    document_id: str
    field_name: str
    asset_id: str
    relevance: Literal["relevant", "not_relevant", "uncertain"]
    status: Literal["draft", "verified"] = "verified"
    note: str = ""


class VisualEvidenceAnnotationRecord(VisualEvidenceAnnotationInput):
    annotation_id: str
    created_at: str


class EvaluationRequest(BaseModel):
    k_values: list[int] = Field(default_factory=lambda: [3, 5, 10])
    gold_status: Literal["verified", "all"] = "verified"


class EvaluationResponse(BaseModel):
    evaluation_id: str
    generated_at: str
    retrieval_version: str
    backend: RetrievalBackendMetadata
    parameters: dict[str, Any]
    gold_status: str
    coverage: dict[str, int]
    timing: dict[str, float]
    metrics_at_k: dict[str, dict[str, float]]
    mean_reciprocal_rank: float
    per_field: list[dict[str, Any]]
    per_query: list[dict[str, Any]]
