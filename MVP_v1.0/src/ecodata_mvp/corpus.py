"""Register PDFs, extract page text, metadata, screening, and availability clues."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pdfplumber
from pypdf import PdfReader

from .models import Study
from .utils import sha256_file, stable_id


DOI_RE = re.compile(r"\b10\.\d{4,9}/[-._;()/:A-Z0-9]+", re.I)
URL_RE = re.compile(r"https?://[^\s<>\]\)]+", re.I)
DATA_HOSTS = ("zenodo", "dryad", "figshare", "github", "datadryad", "osf.io", "dataverse")
DATA_STATEMENT_RE = re.compile(
    r"(?:data availability|availability of data|数据可用性|数据获取)[\s\S]{0,900}", re.I
)
YEAR_RE = re.compile(r"\b(?:19|20)\d{2}\b")


def _language(text: str) -> str:
    chinese = len(re.findall(r"[\u4e00-\u9fff]", text[:10000]))
    latin = len(re.findall(r"[A-Za-z]", text[:10000]))
    if chinese > latin * 0.15:
        return "zh"
    return "en" if latin else "unknown"


def _term_count(text: str, term: str) -> int:
    escaped = re.escape(term.lower())
    if re.search(r"[A-Za-z0-9]", term):
        return len(re.findall(rf"(?<![A-Za-z0-9]){escaped}(?![A-Za-z0-9])", text))
    return text.count(term.lower())


def _metadata(reader: PdfReader, first_pages: str, filename: str) -> dict[str, Any]:
    meta = reader.metadata or {}
    lines = [re.sub(r"\s+", " ", line).strip() for line in first_pages.splitlines()]
    lines = [line for line in lines if 12 <= len(line) <= 260]
    title = str(meta.get("/Title") or "").strip()
    if not title or title.lower() in {"untitled", "microsoft word"}:
        title = next((line for line in lines[:24] if not YEAR_RE.fullmatch(line)), filename)
    author = str(meta.get("/Author") or "").strip()
    doi_match = DOI_RE.search(first_pages)
    years = [int(item) for item in YEAR_RE.findall(first_pages[:8000])]
    years = [year for year in years if 1900 <= year <= 2100]
    filename_year = YEAR_RE.search(filename)
    return {
        "title": title[:500],
        "authors": author[:500],
        "publication_year": int(filename_year.group()) if filename_year else (min(years) if years else None),
        "doi": doi_match.group().rstrip(".,;") if doi_match else "",
    }


def extract_pages(pdf_path: Path) -> tuple[list[dict[str, Any]], list[str]]:
    pages: list[dict[str, Any]] = []
    warnings: list[str] = []
    try:
        with pdfplumber.open(pdf_path) as pdf:
            for page_number, page in enumerate(pdf.pages, 1):
                try:
                    text = page.extract_text(layout=False) or ""
                    pages.append({
                        "page": page_number,
                        "text": text,
                        "width": round(float(page.width), 3),
                        "height": round(float(page.height), 3),
                    })
                except Exception as exc:  # parser failures belong in provenance
                    warnings.append(f"page_{page_number}: {type(exc).__name__}: {exc}")
                    pages.append({"page": page_number, "text": "", "width": 0, "height": 0})
    except Exception as exc:
        warnings.append(f"pdfplumber: {type(exc).__name__}: {exc}")
    return pages, warnings


def register_pdf(pdf_path: Path, variables: list[dict[str, Any]]) -> tuple[Study, list[dict[str, Any]]]:
    digest = sha256_file(pdf_path)
    pages, warnings = extract_pages(pdf_path)
    full_text = "\n".join(page["text"] for page in pages)
    try:
        reader = PdfReader(str(pdf_path))
        metadata = _metadata(reader, full_text[:18000], pdf_path.stem)
        page_count = len(reader.pages)
    except Exception as exc:
        metadata = {"title": pdf_path.stem, "authors": "", "publication_year": None, "doi": ""}
        page_count = len(pages)
        warnings.append(f"pypdf: {type(exc).__name__}: {exc}")

    lowered = full_text.lower()
    hits = sum(_term_count(lowered, str(term)) for var in variables for term in var.get("synonyms", []))
    respiration_hits = sum(lowered.count(term) for term in ("stem respiration", "stem co2", "树干呼吸", "woody tissue"))
    screening_status = "include" if respiration_hits > 0 else "review"
    reasons = [f"target synonym hits: {hits}", f"stem-respiration core hits: {respiration_hits}"]
    statement = ""
    match = DATA_STATEMENT_RE.search(full_text)
    if match:
        statement = re.sub(r"\s+", " ", match.group()).strip()[:1000]
    links = sorted({url.rstrip(".,;") for url in URL_RE.findall(full_text) if any(host in url.lower() for host in DATA_HOSTS)})

    study = Study(
        study_id=stable_id("study", digest),
        pdf_filename=pdf_path.name,
        pdf_sha256=digest,
        file_size_bytes=pdf_path.stat().st_size,
        page_count=page_count,
        text_char_count=len(full_text),
        title=metadata["title"],
        authors=metadata["authors"],
        publication_year=metadata["publication_year"],
        doi=metadata["doi"],
        language=_language(full_text),
        screening_status=screening_status,
        screening_reasons=reasons,
        target_hit_count=hits,
        data_availability_statement=statement,
        external_data_links=links,
        parser_status="warning" if warnings else "ok",
        parser_warnings=warnings,
    )
    return study, pages
