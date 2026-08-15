"""Project paths and versioned processing settings."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class Settings:
    project_root: Path = PROJECT_ROOT
    source_directory: Path = Path(
        os.environ.get(
            "ECODATA_SOURCE_DIR",
            str(PROJECT_ROOT / "demo" / "pdfs"),
        )
    ).resolve()
    data_directory: Path = Path(
        os.environ.get("ECODATA_DATA_DIR", str(PROJECT_ROOT / "data"))
    ).resolve()
    database_path: Path = Path(
        os.environ.get(
            "ECODATA_DB_PATH",
            str(PROJECT_ROOT / "data" / "ecoevidence.sqlite3"),
        )
    ).resolve()
    parser_version: str = "pdfplumber-layout-v1"
    retrieval_version: str = "hybrid-persistent-vector-cache-v3"


settings = Settings()
