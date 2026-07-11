"""Auditable baseline extraction from page text and native PDF tables."""

from __future__ import annotations

import csv
import re
from pathlib import Path
from typing import Any

import pdfplumber
import numpy as np
from PIL import Image

from .models import Candidate, FigureTask, Study
from .normalization import normalize_numeric
from .utils import stable_id, write_csv


NUMBER_RE = re.compile(r"(?<![\w.])[-+]?\d+(?:[.,]\d+)?(?:\s*[–-]\s*\d+(?:[.,]\d+)?)?")
FIGURE_RE = re.compile(r"\b(?:fig(?:ure)?\.?\s*|图\s*)([A-Z]?\d+)([a-z]?)", re.I)
LATIN_SPECIES_RE = re.compile(r"\b([A-Z][a-z]{2,}\s+[a-z][a-z-]{3,})\b")
CHINESE_SPECIES_RE = re.compile(r"(湿地松|马尾松|杉木|油松|樟子松|落叶松|红松|白桦|云杉|冷杉|杨树)")
SPECIES_STOPWORDS = {"previous", "tree", "plant", "stem", "regional", "radial", "brazilian", "maier", "larigauderie", "functional"}


def _context_chunks(text: str) -> list[str]:
    chunks = re.split(r"(?<=[.!?。；;])\s+|\n+", text)
    return [re.sub(r"\s+", " ", chunk).strip() for chunk in chunks if len(chunk.strip()) >= 8]


def _term_position(text: str, term: str) -> int:
    """Match ASCII terms as complete tokens while retaining Chinese substring matching."""
    escaped = re.escape(term.lower())
    if re.search(r"[A-Za-z0-9]", term):
        match = re.search(rf"(?<![A-Za-z0-9]){escaped}(?![A-Za-z0-9])", text)
    else:
        match = re.search(escaped, text)
    return match.start() if match else -1


def _best_unit(chunk: str, number_start: int, number_end: int, patterns: list[str]) -> str:
    window_start = max(0, number_start - 45)
    tail = chunk[window_start:number_end + 70]
    relative_number_end = number_end - window_start
    for unit in sorted(patterns, key=len, reverse=True):
        match = re.search(re.escape(str(unit)), tail, re.I)
        if match and abs(match.start() - relative_number_end) <= 45:
            expanded = tail[match.start():match.end()]
            # Preserve compound respiration denominator where present.
            suffix = re.match(r".{0,45}", tail[match.end():])
            if suffix and any(token in suffix.group().lower() for token in ("m-2", "m−2", "m⁻²", "s-1", "s−1", "s⁻¹", "co2")):
                expanded += suffix.group().strip(" ,.;:)")
            return expanded.strip()
    return ""


def _group_lines(positions: np.ndarray) -> list[int]:
    if not len(positions):
        return []
    groups: list[list[int]] = [[int(positions[0])]]
    for position in positions[1:]:
        value = int(position)
        if value <= groups[-1][-1] + 2:
            groups[-1].append(value)
        else:
            groups.append([value])
    return [round(sum(group) / len(group)) for group in groups]


def _split_plot_grid(image: Image.Image, target_dir: Path, task_id: str) -> list[tuple[str, Path]]:
    gray = np.asarray(image.convert("L"))
    dark = gray < 170
    height, width = dark.shape
    vertical = _group_lines(np.where(dark.sum(axis=0) > 0.42 * height)[0])
    horizontal = _group_lines(np.where(dark.sum(axis=1) > 0.50 * width)[0])
    vertical = [value for index, value in enumerate(vertical) if index == 0 or value - vertical[index - 1] >= width * 0.12]
    horizontal = [value for index, value in enumerate(horizontal) if index == 0 or value - horizontal[index - 1] >= height * 0.12]
    rows, columns = len(horizontal) - 1, len(vertical) - 1
    if rows < 1 or columns < 1 or rows * columns <= 1 or rows * columns > 12:
        return []
    panels: list[tuple[str, Path]] = []
    panel_dir = target_dir / f"{task_id}-panels"
    panel_dir.mkdir(parents=True, exist_ok=True)
    for row in range(rows):
        for column in range(columns):
            x0, x1 = vertical[column], vertical[column + 1]
            y0, y1 = horizontal[row], horizontal[row + 1]
            cell_width, cell_height = x1 - x0, y1 - y0
            crop = (
                max(0, int(x0 - cell_width * (0.20 if column == 0 else 0.04))),
                max(0, int(y0 - cell_height * 0.10)),
                min(width, int(x1 + cell_width * 0.04)),
                min(height, int(y1 + cell_height * (0.28 if row == rows - 1 else 0.05))),
            )
            panel_label = f"{chr(ord('a') + row)}-{column + 1}"
            panel_path = panel_dir / f"{task_id}-{panel_label}.png"
            image.crop(crop).save(panel_path, "PNG")
            panels.append((panel_label, panel_path))
    return panels


def extract_text_candidates(
    study: Study,
    pages: list[dict[str, Any]],
    variables: list[dict[str, Any]],
) -> list[Candidate]:
    candidates: list[Candidate] = []
    for page_record in pages:
        page_number = int(page_record["page"])
        for chunk_index, chunk in enumerate(_context_chunks(page_record["text"])):
            lowered = chunk.lower()
            for variable in variables:
                synonyms = [str(term) for term in variable.get("synonyms", [])]
                matched_positions = [(term, _term_position(lowered, term)) for term in synonyms]
                matched_positions = [(term, position) for term, position in matched_positions if position >= 0]
                matched = [term for term, _ in matched_positions]
                if not matched:
                    continue
                if variable.get("kind") == "numeric":
                    for number_index, number in enumerate(NUMBER_RE.finditer(chunk)):
                        nearest = min(abs(number.start() - position) for _, position in matched_positions)
                        if nearest > 100:
                            continue
                        value_raw = number.group().replace(",", ".")
                        if "–" in value_raw or re.search(r"\d\s*-\s*\d", value_raw):
                            continue
                        try:
                            value = float(value_raw)
                        except ValueError:
                            continue
                        unit = _best_unit(chunk, number.start(), number.end(), variable.get("unit_patterns", []))
                        if not unit:
                            continue
                        normalized, normalized_unit, conversion = normalize_numeric(variable["name"], value, unit)
                        confidence = 0.48 + (0.16 if unit else 0) + (0.08 if nearest < 60 else 0)
                        locator = f"page:{page_number}:chunk:{chunk_index + 1}:number:{number_index + 1}"
                        candidates.append(Candidate(
                            candidate_id=stable_id("cand", study.study_id, variable["name"], locator, value_raw),
                            study_id=study.study_id,
                            variable_name=variable["name"],
                            value_raw=value_raw,
                            value_numeric=value,
                            unit_raw=unit,
                            value_normalized=normalized,
                            unit_normalized=normalized_unit,
                            value_text="",
                            source_type="text",
                            source_path=study.pdf_filename,
                            page=page_number,
                            source_locator=locator,
                            evidence_text=chunk[:1000],
                            extraction_method="rule_text_near_synonym_v1",
                            confidence=min(round(confidence, 3), 0.85),
                            notes=f"matched={matched[0]}; conversion={conversion}",
                        ))
                else:
                    if variable["name"] == "species":
                        species = [
                            value for value in LATIN_SPECIES_RE.findall(chunk)
                            if value.split()[0].lower() not in SPECIES_STOPWORDS
                            and value.lower() not in {"plant ecology", "tree physiology"}
                        ]
                        species.extend(CHINESE_SPECIES_RE.findall(chunk))
                        if not species:
                            continue
                        value_text = "; ".join(dict.fromkeys(species))
                        confidence = 0.7
                    elif variable["name"] == "bark_treatment":
                        token = matched[0].lower()
                        if "girdl" in token or "环剥" in token:
                            value_text = "girdled"
                        elif "remov" in token or "debark" in token or "去皮" in token or "剥皮" in token:
                            value_text = "bark_removed"
                        elif "untreated" in token:
                            value_text = "untreated"
                        else:
                            value_text = "sealed"
                        confidence = 0.7
                    else:
                        value_text = matched[0]
                        confidence = 0.66 if matched[0].lower() not in {"bark", "species", "种"} else 0.5
                    locator = f"page:{page_number}:chunk:{chunk_index + 1}"
                    candidates.append(Candidate(
                        candidate_id=stable_id("cand", study.study_id, variable["name"], locator, chunk),
                        study_id=study.study_id,
                        variable_name=variable["name"],
                        value_raw=value_text,
                        value_numeric=None,
                        unit_raw="",
                        value_normalized=None,
                        unit_normalized="",
                        value_text=value_text,
                        source_type="text",
                        source_path=study.pdf_filename,
                        page=page_number,
                        source_locator=locator,
                        evidence_text=chunk[:1000],
                        extraction_method="rule_categorical_evidence_v1",
                        confidence=confidence,
                        notes=f"matched={matched[0]}",
                    ))
    limits = {"bark_treatment": 5, "species": 15, "measurement_method": 10}
    selected: list[Candidate] = []
    counts: dict[str, int] = {}
    seen: set[tuple[Any, ...]] = set()
    for candidate in sorted(candidates, key=lambda item: (item.confidence, bool(item.unit_raw)), reverse=True):
        signature = (
            candidate.variable_name,
            candidate.page,
            candidate.value_text or candidate.value_normalized,
            candidate.unit_normalized,
        )
        if signature in seen:
            continue
        limit = limits.get(candidate.variable_name, 45)
        if counts.get(candidate.variable_name, 0) >= limit:
            continue
        seen.add(signature)
        counts[candidate.variable_name] = counts.get(candidate.variable_name, 0) + 1
        selected.append(candidate)
    return sorted(selected, key=lambda item: (item.page, item.source_locator, item.variable_name))


def extract_tables(
    pdf_path: Path,
    study: Study,
    variables: list[dict[str, Any]],
    output_dir: Path,
    max_tables: int,
) -> tuple[list[dict[str, Any]], list[Candidate], list[dict[str, Any]]]:
    tables: list[dict[str, Any]] = []
    candidates: list[Candidate] = []
    issues: list[dict[str, Any]] = []
    found = 0
    try:
        with pdfplumber.open(pdf_path) as pdf:
            for page_number, page in enumerate(pdf.pages, 1):
                if found >= max_tables:
                    break
                try:
                    page_tables = page.extract_tables() or []
                    if not page_tables:
                        layout = page.extract_text(layout=True, x_density=7.25, y_density=13) or ""
                        lines = layout.splitlines()
                        starts = [index for index, line in enumerate(lines) if re.match(r"^\s*Table\s*\d+", line, re.I)]
                        for start_index, start in enumerate(starts):
                            end = starts[start_index + 1] if start_index + 1 < len(starts) else min(len(lines), start + 55)
                            block = []
                            for line in lines[start:end]:
                                stripped = line.strip()
                                if not stripped or re.search(r"TREE PHYSIOLOGY|Downloaded$", stripped, re.I):
                                    continue
                                cells = [cell.strip() for cell in re.split(r"\s{2,}", stripped) if cell.strip()]
                                if cells:
                                    block.append(cells)
                            if len(block) >= 3:
                                page_tables.append(block)
                except Exception as exc:
                    issues.append({"study_id": study.study_id, "severity": "warning", "issue_type": "table_parse_failure", "page": page_number, "record_id": "", "message": str(exc), "status": "open"})
                    continue
                for table_index, rows in enumerate(page_tables, 1):
                    if found >= max_tables:
                        break
                    cleaned = [[re.sub(r"\s+", " ", str(cell or "")).strip() for cell in row] for row in rows if row]
                    width = max((len(row) for row in cleaned), default=0)
                    if len(cleaned) < 2 or width < 2:
                        continue
                    blob = " ".join(cell for row in cleaned for cell in row).lower()
                    matched_variables = [var for var in variables if any(str(term).lower() in blob for term in var.get("synonyms", []))]
                    numeric_cells = sum(bool(NUMBER_RE.search(cell)) for row in cleaned for cell in row)
                    if not matched_variables and numeric_cells < 3:
                        continue
                    found += 1
                    table_id = stable_id("table", study.study_id, page_number, table_index)
                    table_path = output_dir / "tables" / study.study_id / f"{table_id}.csv"
                    table_path.parent.mkdir(parents=True, exist_ok=True)
                    with table_path.open("w", encoding="utf-8-sig", newline="") as handle:
                        writer = csv.writer(handle)
                        writer.writerows([row + [""] * (width - len(row)) for row in cleaned])
                    structured_path = ""
                    structured_rows: list[dict[str, Any]] = []
                    if re.search(r"mean.*CO\s*efflux", blob, re.I) and "intercept" in blob:
                        organ = ""
                        for row in cleaned:
                            joined = " ".join(row)
                            if joined.strip().lower() in {"stems", "roots"}:
                                organ = joined.strip().lower()
                                continue
                            match = re.match(r"^\s*(\d{2,4})\s+(\d+)\s+([0-9.]+)\s+\(([0-9.]+)\)", joined)
                            if not match or not organ:
                                continue
                            structured_rows.append({"organ": organ, "elevation_m": match.group(1), "sample_size": match.group(2), "mean_respiration_rate": match.group(3), "sd_respiration_rate": match.group(4), "unit": "µmol CO2 m⁻² s⁻¹", "source_row": joined})
                        if structured_rows:
                            structured_file = output_dir / "tables" / study.study_id / f"{table_id}-structured.csv"
                            write_csv(structured_file, structured_rows)
                            structured_path = str(structured_file.relative_to(output_dir))
                            for row_index, row in enumerate(structured_rows, 1):
                                if row["organ"] != "stems":
                                    continue
                                value = float(row["mean_respiration_rate"])
                                locator = f"{table_id}:structured_row:{row_index}:mean_respiration_rate"
                                candidates.append(Candidate(
                                    candidate_id=stable_id("cand", study.study_id, "stem_respiration_rate", locator, value),
                                    study_id=study.study_id, variable_name="stem_respiration_rate",
                                    value_raw=str(value), value_numeric=value, unit_raw=row["unit"],
                                    value_normalized=value, unit_normalized=row["unit"], value_text="",
                                    source_type="table", source_path=structured_path, page=page_number,
                                    source_locator=locator, evidence_text=row["source_row"],
                                    extraction_method="domain_table_mean_sd_v1", confidence=0.86,
                                    observation_level="site_mean", value_role="mean",
                                    notes=f"organ=stems; elevation_m={row['elevation_m']}; n={row['sample_size']}; sd={row['sd_respiration_rate']}",
                                ))
                    elif re.search(r"elevation\s*\(m\).*t\s*\(°c\)", blob, re.I):
                        for row in cleaned:
                            joined = " ".join(row)
                            match = re.match(r"^\s*(\d{2,4})\s+([0-9.]+)\s+\(", joined)
                            if not match:
                                continue
                            structured_rows.append({"elevation_m": match.group(1), "mean_temperature": match.group(2), "unit": "°C", "source_row": joined})
                        if structured_rows:
                            structured_file = output_dir / "tables" / study.study_id / f"{table_id}-structured.csv"
                            write_csv(structured_file, structured_rows)
                            structured_path = str(structured_file.relative_to(output_dir))
                            for row_index, row in enumerate(structured_rows, 1):
                                value = float(row["mean_temperature"])
                                locator = f"{table_id}:structured_row:{row_index}:mean_temperature"
                                candidates.append(Candidate(
                                    candidate_id=stable_id("cand", study.study_id, "measurement_temperature", locator, value),
                                    study_id=study.study_id, variable_name="measurement_temperature",
                                    value_raw=str(value), value_numeric=value, unit_raw="°C", value_normalized=value,
                                    unit_normalized="°C", value_text="", source_type="table", source_path=structured_path,
                                    page=page_number, source_locator=locator, evidence_text=row["source_row"],
                                    extraction_method="domain_table_mean_range_v1", confidence=0.84,
                                    observation_level="site_mean", value_role="mean",
                                    notes=f"elevation_m={row['elevation_m']}",
                                ))
                    tables.append({
                        "table_id": table_id,
                        "study_id": study.study_id,
                        "page": page_number,
                        "rows": len(cleaned),
                        "columns": width,
                        "numeric_cell_count": numeric_cells,
                        "matched_variables": ";".join(var["name"] for var in matched_variables),
                        "csv_path": str(table_path.relative_to(output_dir)),
                        "structured_csv_path": structured_path,
                        "review_status": "pending",
                    })
                    for variable in matched_variables:
                        header_rows = [row for row in cleaned[:10] if len(row) >= 2]
                        relevant_columns = {
                            column
                            for row in header_rows
                            for column, cell in enumerate(row)
                            if any(_term_position(cell.lower(), str(term)) >= 0 for term in variable.get("synonyms", []))
                            or (variable["name"] == "stem_respiration_rate" and cell.strip().lower() in {"r", "rs", "r s"})
                            or (variable["name"] == "measurement_temperature" and re.match(r"^t\s*(?:\(|$)", cell.strip(), re.I))
                        }
                        for row_index, row in enumerate(cleaned[1:], 2):
                            for column in relevant_columns:
                                if column >= len(row):
                                    continue
                                if variable.get("kind") != "numeric":
                                    value_text = row[column].strip()
                                    if not value_text or not re.search(r"[A-Za-z\u4e00-\u9fff]", value_text):
                                        continue
                                    locator = f"{table_id}:row:{row_index}:column:{column + 1}"
                                    candidates.append(Candidate(
                                        candidate_id=stable_id("cand", study.study_id, variable["name"], locator, value_text),
                                        study_id=study.study_id, variable_name=variable["name"], value_raw=value_text,
                                        value_numeric=None, unit_raw="", value_normalized=None, unit_normalized="",
                                        value_text=value_text, source_type="table", source_path=str(table_path.relative_to(output_dir)),
                                        page=page_number, source_locator=locator, evidence_text=" | ".join(row)[:1000],
                                        extraction_method="pdfplumber_table_categorical_v1", confidence=0.72,
                                        notes="table header and cell relation requires review",
                                    ))
                                    continue
                                match = NUMBER_RE.search(row[column])
                                if not match:
                                    continue
                                try:
                                    value = float(match.group().replace(",", "."))
                                except ValueError:
                                    continue
                                unit = _best_unit(" ".join(cell for header in header_rows for cell in header), 0, 0, variable.get("unit_patterns", []))
                                if not unit:
                                    continue
                                normalized, normalized_unit, conversion = normalize_numeric(variable["name"], value, unit)
                                locator = f"{table_id}:row:{row_index}:column:{column + 1}"
                                candidates.append(Candidate(
                                    candidate_id=stable_id("cand", study.study_id, variable["name"], locator, value),
                                    study_id=study.study_id,
                                    variable_name=variable["name"],
                                    value_raw=match.group(), value_numeric=value, unit_raw=unit,
                                    value_normalized=normalized, unit_normalized=normalized_unit,
                                    value_text="", source_type="table", source_path=str(table_path.relative_to(output_dir)),
                                    page=page_number, source_locator=locator,
                                    evidence_text=" | ".join(row)[:1000],
                                    extraction_method="pdfplumber_table_header_match_v1", confidence=0.68,
                                    notes=f"conversion={conversion}",
                                ))
    except Exception as exc:
        issues.append({"study_id": study.study_id, "severity": "error", "issue_type": "table_document_failure", "page": "", "record_id": "", "message": str(exc), "status": "open"})
    return tables, candidates, issues


def discover_figures(
    pdf_path: Path,
    study: Study,
    pages: list[dict[str, Any]],
    output_dir: Path,
    max_figures: int,
    dpi: int,
) -> tuple[list[FigureTask], list[dict[str, Any]]]:
    tasks: list[FigureTask] = []
    issues: list[dict[str, Any]] = []
    captions: list[tuple[int, str, str]] = []
    for page in pages:
        lines = [re.sub(r"\s+", " ", line).strip() for line in page["text"].splitlines()]
        for line_index, line in enumerate(lines):
            match = FIGURE_RE.match(line)
            if match:
                following = []
                for candidate in lines[line_index:line_index + 14]:
                    if following and (FIGURE_RE.match(candidate) or re.search(r"TREE PHYSIOLOGY", candidate, re.I)):
                        break
                    if candidate:
                        following.append(candidate)
                captions.append((int(page["page"]), f"Figure {match.group(1)}{match.group(2)}", " ".join(following)[:1200]))
    seen: set[tuple[int, str]] = set()
    try:
        with pdfplumber.open(pdf_path) as pdf:
            for page_number, label, caption in captions:
                if len(seen) >= max_figures or (page_number, label) in seen:
                    continue
                seen.add((page_number, label))
                page = pdf.pages[page_number - 1]
                image_path = ""
                if page.images:
                    image = max(page.images, key=lambda item: float(item.get("width", 0)) * float(item.get("height", 0)))
                    bbox = (image["x0"], image["top"], image["x1"], image["bottom"])
                    try:
                        rendered = page.crop(bbox).to_image(resolution=dpi, antialias=True).original
                        task_id = stable_id("figure", study.study_id, page_number, label)
                        target = output_dir / "figures" / study.study_id / f"{task_id}.png"
                        target.parent.mkdir(parents=True, exist_ok=True)
                        rendered.save(target, "PNG")
                        image_path = str(target.relative_to(output_dir))
                    except Exception as exc:
                        issues.append({"study_id": study.study_id, "severity": "warning", "issue_type": "figure_crop_failure", "page": page_number, "record_id": label, "message": str(exc), "status": "open"})
                if not image_path:
                    task_id = stable_id("figure", study.study_id, page_number, label)
                    issues.append({"study_id": study.study_id, "severity": "info", "issue_type": "figure_requires_manual_bbox", "page": page_number, "record_id": task_id, "message": f"{label}: no reliable embedded image crop", "status": "open"})
                panels = _split_plot_grid(rendered, target.parent, task_id) if image_path else []
                if panels:
                    issues.append({"study_id": study.study_id, "severity": "info", "issue_type": "figure_grid_auto_split", "page": page_number, "record_id": task_id, "message": f"{label} split into {len(panels)} coordinate-system tasks; review crops before WPD", "status": "open"})
                    for panel_label, panel_path in panels:
                        panel_task_id = f"{task_id}-{panel_label}"
                        tasks.append(FigureTask(task_id=panel_task_id, study_id=study.study_id, page=page_number, figure_label=f"{label} {panel_label}", caption=caption, image_path=str(panel_path.relative_to(output_dir)), source_pdf=study.pdf_filename))
                else:
                    tasks.append(FigureTask(task_id=task_id, study_id=study.study_id, page=page_number, figure_label=label, caption=caption, image_path=image_path, source_pdf=study.pdf_filename))
    except Exception as exc:
        issues.append({"study_id": study.study_id, "severity": "warning", "issue_type": "figure_document_failure", "page": "", "record_id": "", "message": str(exc), "status": "open"})
    return tasks, issues
