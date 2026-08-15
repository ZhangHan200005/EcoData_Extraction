"""Versioned PDF parsing with reading-order and evidence provenance."""

from __future__ import annotations

import hashlib
import math
import re
import unicodedata
from collections import Counter
from pathlib import Path
from statistics import median
from time import perf_counter
from typing import Any

import pdfplumber
from pypdf import PdfReader

from .schemas import BlockRecord, DocumentRecord, VisualAssetRecord
from .settings import settings


DOI_RE = re.compile(r"\b10\.\d{4,9}/[-._;()/:A-Z0-9]+", re.I)
YEAR_RE = re.compile(r"\b(?:19|20)\d{2}\b")
CAPTION_RE = re.compile(
    r"^(?:fig(?:ure)?\.?\s*[A-Z]?\d+|图\s*[A-Z]?\d+|"
    r"table\s*[A-Z]?\d+|表\s*[A-Z]?\d+)\b",
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
            r"^(?:\d+(?:\.\d+)*\s*)?(materials?\s+and\s+methods?|methods?|"
            r"方法|材料与方法|研究区|试验地)\b",
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


def _normalized_text(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", text)
    normalized = "".join(
        " " if unicodedata.category(character) == "Cc" else character
        for character in normalized
    )
    normalized = re.sub(r"\s+", " ", normalized).strip()
    normalized = re.sub(r"\s+([,.;:!?，。；：！？])", r"\1", normalized)
    normalized = re.sub(r"(?<=\d)\.\s+(?=\d)", ".", normalized)
    normalized = re.sub(r"\b(CO|Q|R)\s+(10|2)\b", r"\1\2", normalized)
    normalized = re.sub(r"\b([nN])\s*=\s*(?=\d)", r"\1=", normalized)
    return normalized


def _section_name(text: str) -> str | None:
    cleaned = _normalized_text(text).strip(" ·•—–-")
    if len(cleaned) > 100:
        return None
    for name, pattern in SECTION_PATTERNS:
        if pattern.search(cleaned):
            return name
    return None


def _caption_kind(text: str) -> str | None:
    if not CAPTION_RE.match(_normalized_text(text)):
        return None
    return (
        "table_caption"
        if re.match(r"^(?:table|表)", _normalized_text(text), re.I)
        else "figure_caption"
    )


def _is_cjk(character: str) -> bool:
    return bool(character and re.match(r"[\u3400-\u9fff]", character))


def _join_words(words: list[dict[str, Any]]) -> str:
    if not words:
        return ""
    text = str(words[0]["text"])
    previous = words[0]
    for word in words[1:]:
        current = str(word["text"])
        gap = float(word["x0"]) - float(previous["x1"])
        previous_text = str(previous["text"])
        character_width = max(
            1.0,
            (float(previous["x1"]) - float(previous["x0"]))
            / max(1, len(previous_text)),
        )
        join_without_space = (
            (_is_cjk(previous_text[-1:]) and _is_cjk(current[:1]))
            or current[:1] in ",.;:!?%)]}，。；：！？％）】》"
            or previous_text[-1:] in "([{（【《"
        ) and gap <= character_width * 1.25
        text += current if join_without_space else f" {current}"
        previous = word
    return _normalized_text(text)


def _line_records(page: pdfplumber.page.Page) -> list[dict[str, Any]]:
    """Build lines from positioned words so cross-column baselines stay split."""

    try:
        words = page.extract_words(
            x_tolerance=1.5,
            y_tolerance=3,
            keep_blank_chars=False,
            use_text_flow=False,
        )
    except Exception:
        words = []
    if not words:
        try:
            fallback = page.extract_text_lines(
                layout=True,
                strip=True,
                return_chars=False,
            )
        except Exception:
            fallback = []
        return [
            {
                "text": _normalized_text(str(line.get("text", ""))),
                "raw_text": str(line.get("text", "")).strip(),
                "x0": float(line.get("x0", 0)),
                "top": float(line.get("top", 0)),
                "x1": float(line.get("x1", page.width)),
                "bottom": float(line.get("bottom", 0)),
            }
            for line in fallback or []
            if str(line.get("text", "")).strip()
        ]

    heights = [
        max(1.0, float(word["bottom"]) - float(word["top"])) for word in words
    ]
    # Superscripts/subscripts such as CO2, R2 and Q10 often sit 4-7 points
    # above or below their baseline. A wider tolerance keeps them inside the
    # containing line without merging normally spaced body lines.
    row_tolerance = max(2.5, median(heights) * 0.65)
    rows: list[list[dict[str, Any]]] = []
    for word in sorted(words, key=lambda item: (float(item["top"]), float(item["x0"]))):
        if rows:
            row_top = median(float(item["top"]) for item in rows[-1])
            if abs(float(word["top"]) - row_top) <= row_tolerance:
                rows[-1].append(word)
                continue
        rows.append([word])

    records: list[dict[str, Any]] = []
    # Scientific two-column PDFs commonly leave only a 15-25 point gutter.
    # Normal word spacing is far smaller, so this separates columns while
    # retaining full-width prose as one line.
    split_gap = max(12.0, float(page.width) * 0.025)
    for row in rows:
        ordered = sorted(row, key=lambda item: float(item["x0"]))
        segments: list[list[dict[str, Any]]] = [[]]
        for word in ordered:
            if (
                segments[-1]
                and float(word["x0"]) - float(segments[-1][-1]["x1"])
                > split_gap
            ):
                segments.append([])
            segments[-1].append(word)
        for segment in segments:
            text = _join_words(segment)
            if not text:
                continue
            records.append(
                {
                    "text": text,
                    "raw_text": " ".join(str(item["text"]) for item in segment),
                    "x0": min(float(item["x0"]) for item in segment),
                    "top": min(float(item["top"]) for item in segment),
                    "x1": max(float(item["x1"]) for item in segment),
                    "bottom": max(float(item["bottom"]) for item in segment),
                }
            )
    return records


def _order_lines(
    lines: list[dict[str, Any]], page_width: float
) -> list[dict[str, Any]]:
    """Use a conservative two-column order with full-width anchors."""

    if not lines:
        return []
    midpoint = page_width / 2
    wide: list[dict[str, Any]] = []
    column_lines: list[dict[str, Any]] = []
    for line in lines:
        width = line["x1"] - line["x0"]
        crosses_middle = line["x0"] < midpoint - 55 and line["x1"] > midpoint + 55
        if width >= page_width * 0.68 or crosses_middle:
            line["column"] = 0
            wide.append(line)
        else:
            line["column"] = 1 if (line["x0"] + line["x1"]) / 2 < midpoint else 2
            column_lines.append(line)
    left_count = sum(line["column"] == 1 for line in column_lines)
    right_count = sum(line["column"] == 2 for line in column_lines)
    if min(left_count, right_count) < 4:
        for line in lines:
            line["column"] = 0
        return sorted(lines, key=lambda item: (item["top"], item["x0"]))

    ordered: list[dict[str, Any]] = []
    remaining = list(column_lines)
    for anchor in sorted(wide, key=lambda item: (item["top"], item["x0"])):
        before = [line for line in remaining if line["top"] < anchor["top"]]
        remaining = [line for line in remaining if line["top"] >= anchor["top"]]
        ordered.extend(
            sorted(before, key=lambda item: (item["column"], item["top"], item["x0"]))
        )
        ordered.append(anchor)
    ordered.extend(
        sorted(remaining, key=lambda item: (item["column"], item["top"], item["x0"]))
    )
    return ordered


def _header_footer_signature(text: str) -> str:
    normalized = _normalized_text(text).lower()
    normalized = re.sub(r"\d+", "#", normalized)
    return re.sub(r"\W+", "", normalized)


def _remove_repeated_margins(
    pages: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if len(pages) < 2:
        return pages
    occurrences: Counter[str] = Counter()
    for page in pages:
        signatures = {
            _header_footer_signature(line["text"])
            for line in page["lines"]
            if (
                line["top"] <= page["height"] * 0.09
                or line["bottom"] >= page["height"] * 0.92
            )
            and len(_header_footer_signature(line["text"])) >= 4
        }
        occurrences.update(signatures)
    threshold = max(2, math.ceil(len(pages) * 0.5))
    repeated = {key for key, count in occurrences.items() if count >= threshold}
    for page in pages:
        page["lines"] = [
            line
            for line in page["lines"]
            if not (
                (
                    line["top"] <= page["height"] * 0.09
                    or line["bottom"] >= page["height"] * 0.92
                )
                and _header_footer_signature(line["text"]) in repeated
            )
        ]
    return pages


def _join_line_texts(lines: list[dict[str, Any]]) -> tuple[str, str]:
    raw_text = "\n".join(str(line.get("raw_text", line["text"])) for line in lines)
    if not lines:
        return "", raw_text
    text = _normalized_text(lines[0]["text"])
    for line in lines[1:]:
        next_text = _normalized_text(line["text"])
        if not next_text:
            continue
        if re.search(r"[A-Za-z]-$", text) and re.match(r"[a-z]", next_text):
            text = text[:-1] + next_text
        elif _is_cjk(text[-1:]) and _is_cjk(next_text[:1]):
            text += next_text
        elif next_text[:1] in ",.;:!?%)]}，。；：！？％）】》":
            text += next_text
        else:
            text += f" {next_text}"
    return _normalized_text(text), raw_text


def _merge_lines(lines: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Merge ordered lines into provenance-preserving parent paragraphs."""

    if not lines:
        return []
    typical_height = median(
        max(1.0, line["bottom"] - line["top"]) for line in lines
    )
    parents: list[dict[str, Any]] = []
    current: list[dict[str, Any]] = []

    def flush() -> None:
        if not current:
            return
        text, raw_text = _join_line_texts(current)
        parents.append(
            {
                "text": text,
                "raw_text": raw_text,
                "x0": min(item["x0"] for item in current),
                "top": min(item["top"] for item in current),
                "x1": max(item["x1"] for item in current),
                "bottom": max(item["bottom"] for item in current),
            }
        )
        current.clear()

    for line in lines:
        heading = _section_name(line["text"])
        caption = _caption_kind(line["text"])
        previous = current[-1] if current else None
        vertical_gap = line["top"] - previous["bottom"] if previous else 0
        column_change = previous is not None and line.get("column") != previous.get("column")
        char_count = sum(len(item["text"]) for item in current)
        indented_new_sentence = (
            bool(current)
            and line["x0"] > current[0]["x0"] + 14
            and bool(re.search(r"[.!?。！？]$", current[-1]["text"]))
        )
        if current and (
            heading
            or caption
            or column_change
            or vertical_gap > typical_height * 0.72
            or indented_new_sentence
            or char_count > 1400
        ):
            flush()
        current.append(line)
        if heading or caption:
            flush()
    flush()
    return parents


def _sentence_units(text: str) -> list[str]:
    units = re.split(
        r"(?<=[。！？!?；;])\s*|(?<=[.])\s+(?=[A-Z\u3400-\u9fff])",
        text,
    )
    return [unit.strip() for unit in units if unit.strip()]


def _hard_chunks(text: str, target: int = 480, overlap: int = 60) -> list[str]:
    if len(text) <= target:
        return [text]
    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = min(len(text), start + target)
        if end < len(text):
            split = max(text.rfind(" ", start + target // 2, end), text.rfind("，", start + target // 2, end))
            if split > start:
                end = split + 1
        chunks.append(text[start:end].strip())
        if end >= len(text):
            break
        start = max(start + 1, end - overlap)
    return [chunk for chunk in chunks if chunk]


def _child_chunks(text: str, target: int = 480, maximum: int = 680) -> list[str]:
    if len(text) <= maximum:
        return [text]
    units = _sentence_units(text)
    if len(units) <= 1:
        return _hard_chunks(text, target)
    chunks: list[str] = []
    current = ""
    for unit_index, unit in enumerate(units):
        candidate = f"{current} {unit}".strip()
        if current and len(candidate) > maximum:
            chunks.append(current)
            overlap_unit = units[max(0, unit_index - 1)]
            current = overlap_unit if len(overlap_unit) <= 120 else ""
            candidate = f"{current} {unit}".strip()
        current = candidate
        if len(current) >= target:
            chunks.append(current)
            current = unit if len(unit) <= 120 else ""
    if current and (not chunks or current != chunks[-1]):
        chunks.append(current)
    return chunks or _hard_chunks(text, target)


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


def _visual_assets(
    page: pdfplumber.page.Page,
    document_id: str,
    page_number: int,
    parents: list[dict[str, Any]],
) -> list[VisualAssetRecord]:
    candidates: list[dict[str, Any]] = []
    for parent in parents:
        caption_kind = _caption_kind(parent["text"])
        if not caption_kind:
            continue
        kind = "table" if caption_kind == "table_caption" else "figure"
        candidates.append(
            {
                "kind": kind,
                "caption": parent["text"],
                "bbox": [parent["x0"], parent["top"], parent["x1"], parent["bottom"]],
                "detection_method": "caption-text",
                "confidence": 0.72,
                "has_structured_content": False,
                "layout_matched": False,
            }
        )

    try:
        tables = page.find_tables()
    except Exception:
        tables = []
    for table in tables:
        bbox = [float(value) for value in table.bbox]
        matching = next(
            (
                item
                for item in candidates
                if item["kind"] == "table" and not item["layout_matched"]
            ),
            None,
        )
        if matching:
            matching["bbox"] = bbox
            matching["detection_method"] = "caption+pdfplumber-table"
            matching["confidence"] = 0.92
            matching["has_structured_content"] = True
            matching["layout_matched"] = True
        else:
            candidates.append(
                {
                    "kind": "table",
                    "caption": "",
                    "bbox": bbox,
                    "detection_method": "pdfplumber-table",
                    "confidence": 0.82,
                    "has_structured_content": True,
                    "layout_matched": True,
                }
            )

    page_area = max(1.0, float(page.width) * float(page.height))
    for image in page.images:
        bbox = [
            float(image.get("x0", 0)),
            float(image.get("top", 0)),
            float(image.get("x1", 0)),
            float(image.get("bottom", 0)),
        ]
        area = max(0.0, bbox[2] - bbox[0]) * max(0.0, bbox[3] - bbox[1])
        area_ratio = area / page_area
        if area_ratio < 0.02:
            continue
        if area_ratio > 0.9:
            if parents:
                continue
            candidates.append(
                {
                    "kind": "image",
                    "caption": "",
                    "bbox": bbox,
                    "detection_method": "full-page-image-scan-candidate",
                    "confidence": 0.95,
                    "has_structured_content": False,
                    "layout_matched": True,
                }
            )
            continue
        matching = next(
            (
                item
                for item in candidates
                if item["kind"] == "figure" and not item["layout_matched"]
            ),
            None,
        )
        if matching:
            matching["bbox"] = bbox
            matching["detection_method"] = "caption+pdf-image-object"
            matching["confidence"] = 0.88
            matching["layout_matched"] = True
        else:
            candidates.append(
                {
                    "kind": "image",
                    "caption": "",
                    "bbox": bbox,
                    "detection_method": "pdf-image-object",
                    "confidence": 0.7,
                    "has_structured_content": False,
                    "layout_matched": True,
                }
            )

    records: list[VisualAssetRecord] = []
    for index, candidate in enumerate(candidates, 1):
        caption = candidate["caption"]
        kind = candidate["kind"]
        summary = caption or (
            "检测到整页图像，当前没有可靠文本层，需要 OCR。"
            if candidate["detection_method"]
            == "full-page-image-scan-candidate"
            else "检测到表格区域，尚未提取单元格。"
            if kind == "table"
            else "检测到 PDF 图像对象，尚未理解图像内容。"
        )
        records.append(
            VisualAssetRecord(
                asset_id=stable_id(
                    "asset", document_id, page_number, index, kind, caption, candidate["bbox"]
                ),
                document_id=document_id,
                page=page_number,
                kind=kind,
                caption=caption,
                bbox=[round(value, 2) for value in candidate["bbox"]],
                detection_method=candidate["detection_method"],
                confidence=candidate["confidence"],
                summary=summary,
                has_structured_content=candidate["has_structured_content"],
                digitization_status="candidate",
                parser_backend="pdfplumber",
                parser_version=settings.parser_version,
            )
        )
    return records


class FullDocumentParser:
    """Default offline parser; Docling remains an optional later backend."""

    def parse(self, path: Path) -> tuple[DocumentRecord, list[BlockRecord]]:
        document, blocks, _ = self.parse_with_assets(path)
        return document, blocks

    def parse_with_assets(
        self, path: Path
    ) -> tuple[DocumentRecord, list[BlockRecord], list[VisualAssetRecord]]:
        if settings.parser_backend != "pdfplumber":
            raise ValueError(
                "Unsupported parser backend. This slice keeps pdfplumber as the "
                "offline default; Docling is an optional follow-up experiment."
            )
        started_at = perf_counter()
        digest = sha256_file(path)
        document_id = stable_id("doc", digest)
        blocks: list[BlockRecord] = []
        assets: list[VisualAssetRecord] = []
        warnings: list[str] = []
        current_section = "front_matter"
        page_count = 0

        try:
            with pdfplumber.open(path) as pdf:
                page_count = len(pdf.pages)
                pages: list[dict[str, Any]] = []
                for page_number, page in enumerate(pdf.pages, 1):
                    try:
                        lines = _order_lines(_line_records(page), float(page.width))
                    except Exception as exc:
                        warnings.append(
                            f"page_{page_number}: {type(exc).__name__}: {exc}"
                        )
                        lines = []
                    if not lines:
                        warnings.append(f"page_{page_number}: low_or_missing_text")
                    pages.append(
                        {
                            "number": page_number,
                            "page": page,
                            "height": float(page.height),
                            "lines": lines,
                        }
                    )
                _remove_repeated_margins(pages)

                ordinal = 0
                parent_ordinal = 0
                for page_record in pages:
                    page_number = page_record["number"]
                    parents = _merge_lines(page_record["lines"])
                    page_assets = _visual_assets(
                        page_record["page"], document_id, page_number, parents
                    )
                    if any(
                        asset.detection_method
                        == "full-page-image-scan-candidate"
                        for asset in page_assets
                    ):
                        warnings.append(f"page_{page_number}: scan_image_candidate")
                    assets.extend(page_assets)
                    for raw in parents:
                        text = raw["text"].strip()
                        if not text:
                            continue
                        detected_section = _section_name(text)
                        kind = "text"
                        if detected_section:
                            current_section = detected_section
                            kind = "heading"
                        else:
                            kind = _caption_kind(text) or "text"
                        parent_ordinal += 1
                        parent_id = stable_id(
                            "parent",
                            document_id,
                            page_number,
                            parent_ordinal,
                            text,
                        )
                        chunks = _child_chunks(text)
                        for chunk_index, chunk in enumerate(chunks):
                            ordinal += 1
                            blocks.append(
                                BlockRecord(
                                    block_id=stable_id(
                                        "block", parent_id, chunk_index, chunk
                                    ),
                                    document_id=document_id,
                                    ordinal=ordinal,
                                    page=page_number,
                                    section=current_section,
                                    kind=kind,
                                    text=chunk,
                                    bbox=[
                                        round(raw["x0"], 2),
                                        round(raw["top"], 2),
                                        round(raw["x1"], 2),
                                        round(raw["bottom"], 2),
                                    ],
                                    raw_text=raw["raw_text"],
                                    parent_id=parent_id,
                                    parent_text=text,
                                    chunk_index=chunk_index,
                                    chunk_count=len(chunks),
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
            metadata = {"title": path.stem, "publication_year": None}

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
            parser_backend="pdfplumber",
            parse_elapsed_ms=round((perf_counter() - started_at) * 1000, 3),
        )
        return document, blocks, assets
