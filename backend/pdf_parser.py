"""Full-document PDF parser with stable block ids and layout provenance."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from statistics import median
from typing import Any

import pdfplumber
from pypdf import PdfReader

from .schemas import BlockRecord, DocumentRecord
from .settings import settings


DOI_RE = re.compile(r"\b10\.\d{4,9}/[-._;()/:A-Z0-9]+", re.I)
YEAR_RE = re.compile(r"\b(?:19|20)\d{2}\b")
CAPTION_RE = re.compile(
    r"^(?:fig(?:ure)?\.?\s*\w+|图\s*\d+|table\s*\w+|表\s*\d+)",
    re.I,
)
SECTION_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("abstract", re.compile(r"^(abstract|摘要)\b", re.I)),
    (
        "introduction",
        re.compile(r"^(?:\d+(?:\.\d+)*\s*)?(introduction|引言|前言)\b", re.I),
    ),
    (
        "methods",
        re.compile(
            r"^(?:\d+(?:\.\d+)*\s*)?(materials?\s+and\s+methods?|methods?|方法|材料与方法|研究区|试验地)\b",
            re.I,
        ),
    ),
    (
        "results",
        re.compile(r"^(?:\d+(?:\.\d+)*\s*)?(results?|结果)\b", re.I),
    ),
    (
        "discussion",
        re.compile(r"^(?:\d+(?:\.\d+)*\s*)?(discussion|讨论)\b", re.I),
    ),
    (
        "conclusion",
        re.compile(r"^(?:\d+(?:\.\d+)*\s*)?(conclusions?|结论)\b", re.I),
    ),
    (
        "references",
        re.compile(r"^(references|literature cited|参考文献)\b", re.I),
    ),
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def stable_id(prefix: str, *parts: object) -> str:
    payload = "|".join(str(part) for part in parts)
    return f"{prefix}-{hashlib.sha256(payload.encode('utf-8')).hexdigest()[:14]}"


def _language(text: str) -> str:
    chinese = len(re.findall(r"[\u4e00-\u9fff]", text[:20000]))
    latin = len(re.findall(r"[A-Za-z]", text[:20000]))
    if chinese > latin * 0.12:
        return "zh"
    return "en" if latin else "unknown"


def _section_name(text: str) -> str | None:
    cleaned = re.sub(r"\s+", " ", text).strip(" ·•—–-")
    if len(cleaned) > 100:
        return None
    for name, pattern in SECTION_PATTERNS:
        if pattern.search(cleaned):
            return name
    return None


def _line_records(page: pdfplumber.page.Page) -> list[dict[str, Any]]:
    try:
        lines = page.extract_text_lines(
            layout=True,
            strip=True,
            return_chars=False,
        )
    except Exception:
        lines = []
    records: list[dict[str, Any]] = []
    for line in lines or []:
        text = re.sub(r"\s+", " ", str(line.get("text", ""))).strip()
        if not text:
            continue
        records.append(
            {
                "text": text,
                "x0": float(line.get("x0", 0)),
                "top": float(line.get("top", 0)),
                "x1": float(line.get("x1", page.width)),
                "bottom": float(line.get("bottom", 0)),
            }
        )
    return records


def _merge_lines(lines: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not lines:
        return []
    line_heights = [
        max(1.0, line["bottom"] - line["top"])
        for line in lines
    ]
    typical_height = median(line_heights) if line_heights else 10.0
    blocks: list[dict[str, Any]] = []
    current: list[dict[str, Any]] = []

    def flush() -> None:
        if not current:
            return
        blocks.append(
            {
                "text": " ".join(item["text"] for item in current),
                "x0": min(item["x0"] for item in current),
                "top": min(item["top"] for item in current),
                "x1": max(item["x1"] for item in current),
                "bottom": max(item["bottom"] for item in current),
            }
        )
        current.clear()

    for line in lines:
        heading = _section_name(line["text"])
        caption = bool(CAPTION_RE.match(line["text"]))
        previous = current[-1] if current else None
        vertical_gap = (
            line["top"] - previous["bottom"] if previous is not None else 0
        )
        column_jump = (
            previous is not None
            and abs(line["x0"] - previous["x0"]) > 160
            and line["top"] <= previous["bottom"] + typical_height
        )
        char_count = sum(len(item["text"]) for item in current)
        if current and (
            heading
            or caption
            or vertical_gap > typical_height * 1.5
            or column_jump
            or char_count > 850
        ):
            flush()
        current.append(line)
        if heading or caption:
            flush()
    flush()
    return blocks


def _metadata(reader: PdfReader, blocks: list[BlockRecord], filename: str) -> dict:
    metadata = reader.metadata or {}
    title = str(metadata.get("/Title") or "").strip()
    generic_titles = {"", "untitled", "microsoft word", "acrobat distiller"}
    first_lines = [
        block.text
        for block in blocks
        if block.page <= 2 and 12 <= len(block.text) <= 300
    ]
    if title.lower() in generic_titles or len(title) < 8:
        title = next(
            (
                line
                for line in first_lines[:20]
                if not YEAR_RE.fullmatch(line)
                and not DOI_RE.search(line)
                and "journal" not in line.lower()
            ),
            Path(filename).stem,
        )
    filename_year = YEAR_RE.search(filename)
    year = int(filename_year.group()) if filename_year else None
    if year is None:
        date = str(metadata.get("/CreationDate") or "")
        match = YEAR_RE.search(date)
        year = int(match.group()) if match else None
    return {"title": title[:500], "publication_year": year}


class FullDocumentParser:
    def parse(self, path: Path) -> tuple[DocumentRecord, list[BlockRecord]]:
        digest = sha256_file(path)
        document_id = stable_id("doc", digest)
        blocks: list[BlockRecord] = []
        warnings: list[str] = []
        current_section = "front_matter"
        page_count = 0

        try:
            with pdfplumber.open(path) as pdf:
                page_count = len(pdf.pages)
                ordinal = 0
                for page_number, page in enumerate(pdf.pages, 1):
                    try:
                        page_blocks = _merge_lines(_line_records(page))
                    except Exception as exc:
                        warnings.append(
                            f"page_{page_number}: {type(exc).__name__}: {exc}"
                        )
                        page_blocks = []
                    if not page_blocks:
                        warnings.append(f"page_{page_number}: low_or_missing_text")
                    for raw in page_blocks:
                        text = raw["text"].strip()
                        detected_section = _section_name(text)
                        kind = "text"
                        if detected_section:
                            current_section = detected_section
                            kind = "heading"
                        elif CAPTION_RE.match(text):
                            kind = (
                                "table_caption"
                                if re.match(r"^(?:table|表)", text, re.I)
                                else "figure_caption"
                            )
                        ordinal += 1
                        blocks.append(
                            BlockRecord(
                                block_id=stable_id(
                                    "block",
                                    document_id,
                                    page_number,
                                    ordinal,
                                    text,
                                ),
                                document_id=document_id,
                                ordinal=ordinal,
                                page=page_number,
                                section=current_section,
                                kind=kind,
                                text=text,
                                bbox=[
                                    round(raw["x0"], 2),
                                    round(raw["top"], 2),
                                    round(raw["x1"], 2),
                                    round(raw["bottom"], 2),
                                ],
                            )
                        )
        except Exception as exc:
            warnings.append(f"document: {type(exc).__name__}: {exc}")

        full_text = "\n".join(block.text for block in blocks)
        try:
            reader = PdfReader(str(path))
            page_count = len(reader.pages)
            metadata = _metadata(reader, blocks, path.name)
        except Exception as exc:
            warnings.append(f"metadata: {type(exc).__name__}: {exc}")
            metadata = {
                "title": path.stem,
                "publication_year": None,
            }

        low_text_pages = sum(
            warning.endswith("low_or_missing_text") for warning in warnings
        )
        if len(full_text) < 100 or not blocks:
            parser_status = "failed"
        elif page_count and low_text_pages / page_count >= 0.2:
            parser_status = "warning"
        else:
            parser_status = "ok"

        document = DocumentRecord(
            document_id=document_id,
            sha256=digest,
            filename=path.name,
            source_path=str(path.resolve()),
            title=metadata["title"],
            publication_year=metadata["publication_year"],
            language=_language(full_text),
            page_count=page_count,
            text_char_count=len(full_text),
            parser_status=parser_status,
            parser_warnings=warnings,
            parser_version=settings.parser_version,
        )
        return document, blocks
