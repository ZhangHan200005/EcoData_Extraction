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


class RetrievalResponse(BaseModel):
    run_id: str
    document_id: str
    field_name: str
    query: str
    retrieval_version: str
    total_blocks: int
    hits: list[RetrievalHit]


class GoldEvidenceInput(BaseModel):
    document_id: str
    field_name: str
    block_id: str
    status: Literal["draft", "verified"] = "verified"
    note: str = ""


class GoldEvidenceRecord(GoldEvidenceInput):
    gold_id: str
    created_at: str


class EvaluationRequest(BaseModel):
    k_values: list[int] = Field(default_factory=lambda: [3, 5, 10])
    gold_status: Literal["verified", "all"] = "verified"


class EvaluationResponse(BaseModel):
    evaluation_id: str
    generated_at: str
    retrieval_version: str
    gold_status: str
    coverage: dict[str, int]
    metrics_at_k: dict[str, dict[str, float]]
    mean_reciprocal_rank: float
    per_field: list[dict[str, Any]]
    per_query: list[dict[str, Any]]
