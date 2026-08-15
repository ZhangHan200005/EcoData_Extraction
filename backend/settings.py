"""Project paths and versioned processing settings."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _env_bool(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} must be a boolean value")


def _env_positive_int(name: str, default: int) -> int:
    value = int(os.environ.get(name, str(default)))
    if value < 1:
        raise ValueError(f"{name} must be at least 1")
    return value


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
    model_cache_directory: Path = Path(
        os.environ.get(
            "ECODATA_MODEL_CACHE_DIR",
            str(PROJECT_ROOT / "data" / "models"),
        )
    ).resolve()
    retrieval_backend: str = os.environ.get(
        "ECODATA_RETRIEVAL_BACKEND", "hashing"
    ).strip()
    embedding_device: str = os.environ.get(
        "ECODATA_EMBEDDING_DEVICE", "cpu"
    ).strip()
    embedding_batch_size: int = _env_positive_int(
        "ECODATA_EMBEDDING_BATCH_SIZE", 32
    )
    embedding_local_files_only: bool = _env_bool(
        "ECODATA_MODEL_LOCAL_FILES_ONLY", False
    )
    parser_backend: str = os.environ.get(
        "ECODATA_PARSER_BACKEND", "pdfplumber"
    ).strip()
    parser_version: str = "pdfplumber-reading-order-v2"
    chunking_version: str = "parent-child-480char-v1"
    retrieval_version: str = "hybrid-parent-context-v6"


settings = Settings()
