"""Shared data records for extraction, review, and export."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class Study:
    study_id: str
    pdf_filename: str
    pdf_sha256: str
    file_size_bytes: int
    page_count: int
    text_char_count: int
    title: str = ""
    authors: str = ""
    publication_year: int | None = None
    journal: str = ""
    doi: str = ""
    language: str = "unknown"
    screening_status: str = "review"
    screening_reasons: list[str] = field(default_factory=list)
    target_hit_count: int = 0
    data_availability_statement: str = ""
    external_data_links: list[str] = field(default_factory=list)
    site_context: str = ""
    parser_status: str = "ok"
    parser_warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Candidate:
    candidate_id: str
    study_id: str
    variable_name: str
    value_raw: str
    value_numeric: float | None
    unit_raw: str
    value_normalized: float | None
    unit_normalized: str
    value_text: str
    source_type: str
    source_path: str
    page: int
    source_locator: str
    evidence_text: str
    extraction_method: str
    confidence: float
    review_status: str = "pending"
    observation_level: str = "uncertain"
    value_role: str = "uncertain"
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class FigureTask:
    task_id: str
    study_id: str
    page: int
    figure_label: str
    caption: str
    image_path: str
    source_pdf: str
    status: str = "pending"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

