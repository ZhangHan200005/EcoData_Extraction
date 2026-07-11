"""End-to-end orchestration for one reproducible local extraction run."""

from __future__ import annotations

import json
import platform
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pdfplumber
import pypdf

from .config import load_configuration
from .corpus import register_pdf
from .exports import export_package
from .extractors import discover_figures, extract_tables, extract_text_candidates
from .models import Candidate, FigureTask, Study
from .quality import quality_summary, validate_candidates
from .utils import utc_now, write_json, write_jsonl


def _run_id() -> str:
    return datetime.now(timezone.utc).strftime("run-%Y%m%dT%H%M%SZ")


def run_pipeline(root: Path, input_dir: Path | None = None) -> Path:
    root = root.resolve()
    configuration = load_configuration(root / "config/project.yml", root / "config/variables.yml")
    project = configuration["project"]
    variables = configuration["variables"].get("variables", [])
    run_config = project.get("run", {})
    input_dir = (input_dir or root / run_config.get("input_directory", "example")).resolve()
    output_root = root / run_config.get("output_directory", "data/output")
    run_id = _run_id()
    run_dir = output_root / run_id
    if run_dir.exists():
        suffix = 2
        while (output_root / f"{run_id}-{suffix}").exists():
            suffix += 1
        run_id = f"{run_id}-{suffix}"
        run_dir = output_root / run_id
    run_dir.mkdir(parents=True)

    pdf_paths = sorted(input_dir.glob("*.pdf"))
    if not pdf_paths:
        raise FileNotFoundError(f"No PDF files found in {input_dir}")

    studies: list[Study] = []
    candidates: list[Candidate] = []
    figures: list[FigureTask] = []
    tables: list[dict[str, Any]] = []
    issues: list[dict[str, Any]] = []
    provenance: list[dict[str, Any]] = []
    seen_hashes: dict[str, str] = {}

    for pdf_path in pdf_paths:
        study, pages = register_pdf(pdf_path, variables)
        if study.pdf_sha256 in seen_hashes:
            issues.append({"study_id": study.study_id, "severity": "warning", "issue_type": "duplicate_pdf", "page": "", "record_id": "", "message": f"Duplicate of {seen_hashes[study.pdf_sha256]}", "status": "open"})
            continue
        seen_hashes[study.pdf_sha256] = pdf_path.name
        studies.append(study)
        write_jsonl(run_dir / "parsed" / study.study_id / "pages.jsonl", pages)

        text_candidates = extract_text_candidates(study, pages, variables)
        table_index, table_candidates, table_issues = extract_tables(
            pdf_path, study, variables, run_dir,
            int(run_config.get("max_tables_per_pdf", 20)),
        )
        figure_tasks, figure_issues = discover_figures(
            pdf_path, study, pages, run_dir,
            int(run_config.get("max_figures_per_pdf", 12)),
            int(run_config.get("render_dpi", 180)),
        )
        candidates.extend(text_candidates)
        candidates.extend(table_candidates)
        tables.extend(table_index)
        figures.extend(figure_tasks)
        issues.extend(table_issues + figure_issues)
        provenance.extend([
            {"event_id": f"{study.study_id}-parse", "study_id": study.study_id, "activity": "parse_pdf", "agent": "pdfplumber+pypdf", "version": f"pdfplumber={pdfplumber.__version__};pypdf={pypdf.__version__}", "input": pdf_path.name, "output": f"parsed/{study.study_id}/pages.jsonl", "config_sha256": configuration["config_sha256"], "timestamp": utc_now()},
            {"event_id": f"{study.study_id}-extract", "study_id": study.study_id, "activity": "extract_candidates", "agent": "ecodata_mvp_rules", "version": "0.1.0", "input": f"parsed/{study.study_id}/pages.jsonl", "output": "data.csv", "config_sha256": configuration["config_sha256"], "timestamp": utc_now()},
        ])

    issues.extend(validate_candidates(candidates, variables))
    summary = quality_summary(studies, candidates, issues, variables)
    export_package(
        run_dir, run_id, studies, candidates, tables,
        [figure.to_dict() for figure in figures], issues, variables,
        summary, configuration["config_sha256"], provenance,
    )
    write_json(run_dir / "run_manifest.json", {
        "run_id": run_id,
        "started_from": str(input_dir),
        "completed_at": utc_now(),
        "config_sha256": configuration["config_sha256"],
        "pdf_count": len(pdf_paths),
        "unique_study_count": len(studies),
        "software": {"python": platform.python_version(), "platform": platform.platform(), "pipeline": "ecodata-mvp 0.1.0"},
    })
    write_json(output_root / "latest_run.json", {"run_id": run_id, "path": str(run_dir)})
    return run_dir
