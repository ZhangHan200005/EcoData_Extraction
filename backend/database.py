"""Small SQLite repository for canonical parsed text and audit records."""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing, contextmanager
from pathlib import Path
from typing import Any, Iterator

from .schemas import (
    BlockRecord,
    DocumentRecord,
    EmbeddingCacheKey,
    GoldEvidenceRecord,
    ProjectSpec,
    RetrievalResponse,
    VisualAssetRecord,
)
from .settings import settings


SCHEMA = """
CREATE TABLE IF NOT EXISTS project_specs (
    spec_id TEXT PRIMARY KEY,
    brief TEXT NOT NULL,
    spec_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS documents (
    document_id TEXT PRIMARY KEY,
    sha256 TEXT NOT NULL UNIQUE,
    filename TEXT NOT NULL,
    source_path TEXT NOT NULL,
    title TEXT NOT NULL,
    publication_year INTEGER,
    language TEXT NOT NULL,
    page_count INTEGER NOT NULL,
    text_char_count INTEGER NOT NULL,
    parser_status TEXT NOT NULL,
    parser_warnings_json TEXT NOT NULL,
    parser_version TEXT NOT NULL,
    parser_backend TEXT NOT NULL DEFAULT 'pdfplumber',
    parse_elapsed_ms REAL NOT NULL DEFAULT 0,
    screening_status TEXT NOT NULL,
    screening_reasons_json TEXT NOT NULL,
    missing_required_fields_json TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS blocks (
    block_id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL,
    ordinal INTEGER NOT NULL,
    page INTEGER NOT NULL,
    section TEXT NOT NULL,
    kind TEXT NOT NULL,
    text TEXT NOT NULL,
    bbox_json TEXT NOT NULL,
    raw_text TEXT NOT NULL DEFAULT '',
    parent_id TEXT NOT NULL DEFAULT '',
    parent_text TEXT NOT NULL DEFAULT '',
    chunk_index INTEGER NOT NULL DEFAULT 0,
    chunk_count INTEGER NOT NULL DEFAULT 1,
    FOREIGN KEY(document_id) REFERENCES documents(document_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS blocks_document_ordinal_idx
ON blocks(document_id, ordinal);

CREATE INDEX IF NOT EXISTS blocks_document_page_idx
ON blocks(document_id, page);

CREATE TABLE IF NOT EXISTS visual_assets (
    asset_id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL,
    page INTEGER NOT NULL,
    kind TEXT NOT NULL,
    caption TEXT NOT NULL,
    bbox_json TEXT NOT NULL,
    detection_method TEXT NOT NULL,
    confidence REAL NOT NULL,
    summary TEXT NOT NULL,
    has_structured_content INTEGER NOT NULL DEFAULT 0,
    digitization_status TEXT NOT NULL,
    parser_backend TEXT NOT NULL,
    parser_version TEXT NOT NULL,
    FOREIGN KEY(document_id) REFERENCES documents(document_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS visual_assets_document_page_idx
ON visual_assets(document_id, page, kind);

CREATE TABLE IF NOT EXISTS gold_evidence (
    gold_id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL,
    field_name TEXT NOT NULL,
    block_id TEXT NOT NULL,
    status TEXT NOT NULL,
    note TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(document_id, field_name, block_id),
    FOREIGN KEY(document_id) REFERENCES documents(document_id) ON DELETE CASCADE,
    FOREIGN KEY(block_id) REFERENCES blocks(block_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS gold_query_idx
ON gold_evidence(document_id, field_name, status);

CREATE TABLE IF NOT EXISTS retrieval_runs (
    run_id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL,
    field_name TEXT NOT NULL,
    query_text TEXT NOT NULL,
    k INTEGER NOT NULL,
    result_json TEXT NOT NULL,
    retrieval_version TEXT NOT NULL,
    retrieval_backend TEXT NOT NULL DEFAULT 'unknown',
    backend_version TEXT NOT NULL DEFAULT 'unknown',
    embedding_model TEXT NOT NULL DEFAULT 'unknown',
    model_version TEXT NOT NULL DEFAULT 'unknown',
    parameters_json TEXT NOT NULL DEFAULT '{}',
    query_count INTEGER NOT NULL DEFAULT 1,
    corpus_size INTEGER NOT NULL DEFAULT 0,
    elapsed_ms REAL NOT NULL DEFAULT 0,
    cache_enabled INTEGER NOT NULL DEFAULT 0,
    vector_cache_hits INTEGER NOT NULL DEFAULT 0,
    vector_cache_misses INTEGER NOT NULL DEFAULT 0,
    vector_cache_writes INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS embedding_vectors (
    cache_key TEXT PRIMARY KEY,
    cache_key_version TEXT NOT NULL,
    document_sha256 TEXT NOT NULL,
    block_id TEXT NOT NULL,
    normalized_text_sha256 TEXT NOT NULL,
    retrieval_backend TEXT NOT NULL,
    backend_version TEXT NOT NULL,
    embedding_model TEXT NOT NULL,
    model_version TEXT NOT NULL,
    dimensions INTEGER NOT NULL,
    parameters_sha256 TEXT NOT NULL,
    vector_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS embedding_vectors_document_block_idx
ON embedding_vectors(document_sha256, block_id);

CREATE TABLE IF NOT EXISTS evaluations (
    evaluation_id TEXT PRIMARY KEY,
    result_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""


RETRIEVAL_RUN_MIGRATIONS = {
    "retrieval_backend": "TEXT NOT NULL DEFAULT 'unknown'",
    "backend_version": "TEXT NOT NULL DEFAULT 'unknown'",
    "embedding_model": "TEXT NOT NULL DEFAULT 'unknown'",
    "model_version": "TEXT NOT NULL DEFAULT 'unknown'",
    "parameters_json": "TEXT NOT NULL DEFAULT '{}'",
    "query_count": "INTEGER NOT NULL DEFAULT 1",
    "corpus_size": "INTEGER NOT NULL DEFAULT 0",
    "elapsed_ms": "REAL NOT NULL DEFAULT 0",
    "cache_enabled": "INTEGER NOT NULL DEFAULT 0",
    "vector_cache_hits": "INTEGER NOT NULL DEFAULT 0",
    "vector_cache_misses": "INTEGER NOT NULL DEFAULT 0",
    "vector_cache_writes": "INTEGER NOT NULL DEFAULT 0",
}

DOCUMENT_MIGRATIONS = {
    "parser_backend": "TEXT NOT NULL DEFAULT 'pdfplumber'",
    "parse_elapsed_ms": "REAL NOT NULL DEFAULT 0",
}

BLOCK_MIGRATIONS = {
    "raw_text": "TEXT NOT NULL DEFAULT ''",
    "parent_id": "TEXT NOT NULL DEFAULT ''",
    "parent_text": "TEXT NOT NULL DEFAULT ''",
    "chunk_index": "INTEGER NOT NULL DEFAULT 0",
    "chunk_count": "INTEGER NOT NULL DEFAULT 1",
}


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def initialize_database(path: Path | None = None) -> None:
    database_path = path or settings.database_path
    database_path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(database_path)) as connection:
        with connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("PRAGMA foreign_keys=ON")
            connection.executescript(SCHEMA)
            existing_columns = {
                row[1]
                for row in connection.execute(
                    "PRAGMA table_info(retrieval_runs)"
                ).fetchall()
            }
            for column, declaration in RETRIEVAL_RUN_MIGRATIONS.items():
                if column not in existing_columns:
                    connection.execute(
                        "ALTER TABLE retrieval_runs ADD COLUMN "
                        f"{column} {declaration}"
                    )
            for table, migrations in (
                ("documents", DOCUMENT_MIGRATIONS),
                ("blocks", BLOCK_MIGRATIONS),
            ):
                existing_columns = {
                    row[1]
                    for row in connection.execute(
                        f"PRAGMA table_info({table})"
                    ).fetchall()
                }
                for column, declaration in migrations.items():
                    if column not in existing_columns:
                        connection.execute(
                            f"ALTER TABLE {table} ADD COLUMN "
                            f"{column} {declaration}"
                        )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS blocks_document_parent_idx
                ON blocks(document_id, parent_id, chunk_index)
                """
            )


@contextmanager
def connect(path: Path | None = None) -> Iterator[sqlite3.Connection]:
    database_path = path or settings.database_path
    initialize_database(database_path)
    connection = sqlite3.connect(database_path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys=ON")
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


class Repository:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or settings.database_path
        initialize_database(self.path)

    def save_spec(self, spec_id: str, spec: ProjectSpec, created_at: str) -> None:
        with connect(self.path) as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO project_specs
                (spec_id, brief, spec_json, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (spec_id, spec.brief, spec.model_dump_json(), created_at),
            )

    def current_spec(self) -> ProjectSpec | None:
        with connect(self.path) as connection:
            row = connection.execute(
                "SELECT spec_json FROM project_specs ORDER BY created_at DESC LIMIT 1"
            ).fetchone()
        return ProjectSpec.model_validate_json(row["spec_json"]) if row else None

    def document_by_hash(self, sha256: str) -> DocumentRecord | None:
        with connect(self.path) as connection:
            row = connection.execute(
                "SELECT * FROM documents WHERE sha256 = ?", (sha256,)
            ).fetchone()
        return self._document(row) if row else None

    def document(self, document_id: str) -> DocumentRecord | None:
        with connect(self.path) as connection:
            row = connection.execute(
                "SELECT * FROM documents WHERE document_id = ?", (document_id,)
            ).fetchone()
        return self._document(row) if row else None

    def list_documents(self) -> list[DocumentRecord]:
        with connect(self.path) as connection:
            rows = connection.execute(
                "SELECT * FROM documents ORDER BY filename"
            ).fetchall()
        return [self._document(row) for row in rows]

    def save_document(
        self,
        document: DocumentRecord,
        blocks: list[BlockRecord],
        updated_at: str,
        assets: list[VisualAssetRecord] | None = None,
    ) -> None:
        with connect(self.path) as connection:
            gold_block_ids = {
                row["block_id"]
                for row in connection.execute(
                    "SELECT block_id FROM gold_evidence WHERE document_id = ?",
                    (document.document_id,),
                ).fetchall()
            }
            new_block_ids = {block.block_id for block in blocks}
            missing_gold = sorted(gold_block_ids - new_block_ids)
            if missing_gold:
                raise ValueError(
                    "Parser output would invalidate verified evidence. "
                    f"Preserved the existing document; {len(missing_gold)} Gold "
                    "block(s) require an explicit migration."
                )
            connection.execute(
                """
                INSERT INTO documents (
                    document_id, sha256, filename, source_path, title,
                    publication_year, language, page_count, text_char_count,
                    parser_status, parser_warnings_json, parser_version,
                    parser_backend, parse_elapsed_ms,
                    screening_status, screening_reasons_json,
                    missing_required_fields_json, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(document_id) DO UPDATE SET
                    sha256=excluded.sha256,
                    filename=excluded.filename,
                    source_path=excluded.source_path,
                    title=excluded.title,
                    publication_year=excluded.publication_year,
                    language=excluded.language,
                    page_count=excluded.page_count,
                    text_char_count=excluded.text_char_count,
                    parser_status=excluded.parser_status,
                    parser_warnings_json=excluded.parser_warnings_json,
                    parser_version=excluded.parser_version,
                    parser_backend=excluded.parser_backend,
                    parse_elapsed_ms=excluded.parse_elapsed_ms,
                    screening_status=excluded.screening_status,
                    screening_reasons_json=excluded.screening_reasons_json,
                    missing_required_fields_json=excluded.missing_required_fields_json,
                    updated_at=excluded.updated_at
                """,
                (
                    document.document_id,
                    document.sha256,
                    document.filename,
                    document.source_path,
                    document.title,
                    document.publication_year,
                    document.language,
                    document.page_count,
                    document.text_char_count,
                    document.parser_status,
                    _json(document.parser_warnings),
                    document.parser_version,
                    document.parser_backend,
                    document.parse_elapsed_ms,
                    document.screening_status,
                    _json(document.screening_reasons),
                    _json(document.missing_required_fields),
                    updated_at,
                ),
            )
            connection.executemany(
                """
                INSERT INTO blocks (
                    block_id, document_id, ordinal, page, section,
                    kind, text, bbox_json, raw_text, parent_id,
                    parent_text, chunk_index, chunk_count
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(block_id) DO UPDATE SET
                    document_id=excluded.document_id,
                    ordinal=excluded.ordinal,
                    page=excluded.page,
                    section=excluded.section,
                    kind=excluded.kind,
                    text=excluded.text,
                    bbox_json=excluded.bbox_json,
                    raw_text=excluded.raw_text,
                    parent_id=excluded.parent_id,
                    parent_text=excluded.parent_text,
                    chunk_index=excluded.chunk_index,
                    chunk_count=excluded.chunk_count
                """,
                [
                    (
                        block.block_id,
                        block.document_id,
                        block.ordinal,
                        block.page,
                        block.section,
                        block.kind,
                        block.text,
                        _json(block.bbox),
                        block.raw_text,
                        block.parent_id,
                        block.parent_text,
                        block.chunk_index,
                        block.chunk_count,
                    )
                    for block in blocks
                ],
            )
            stale_block_ids = {
                row["block_id"]
                for row in connection.execute(
                    "SELECT block_id FROM blocks WHERE document_id = ?",
                    (document.document_id,),
                ).fetchall()
            } - new_block_ids
            if stale_block_ids:
                connection.executemany(
                    "DELETE FROM blocks WHERE block_id = ?",
                    [(block_id,) for block_id in sorted(stale_block_ids)],
                )
            connection.execute(
                "DELETE FROM visual_assets WHERE document_id = ?",
                (document.document_id,),
            )
            connection.executemany(
                """
                INSERT INTO visual_assets (
                    asset_id, document_id, page, kind, caption, bbox_json,
                    detection_method, confidence, summary,
                    has_structured_content, digitization_status,
                    parser_backend, parser_version
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        asset.asset_id,
                        asset.document_id,
                        asset.page,
                        asset.kind,
                        asset.caption,
                        _json(asset.bbox),
                        asset.detection_method,
                        asset.confidence,
                        asset.summary,
                        int(asset.has_structured_content),
                        asset.digitization_status,
                        asset.parser_backend,
                        asset.parser_version,
                    )
                    for asset in assets or []
                ],
            )

    def update_screening(self, document: DocumentRecord, updated_at: str) -> None:
        with connect(self.path) as connection:
            connection.execute(
                """
                UPDATE documents
                SET screening_status = ?, screening_reasons_json = ?,
                    missing_required_fields_json = ?, updated_at = ?
                WHERE document_id = ?
                """,
                (
                    document.screening_status,
                    _json(document.screening_reasons),
                    _json(document.missing_required_fields),
                    updated_at,
                    document.document_id,
                ),
            )

    def blocks(
        self,
        document_id: str,
        query: str = "",
        limit: int | None = None,
    ) -> list[BlockRecord]:
        sql = "SELECT * FROM blocks WHERE document_id = ?"
        parameters: list[Any] = [document_id]
        if query:
            sql += " AND lower(text) LIKE ?"
            parameters.append(f"%{query.lower()}%")
        sql += " ORDER BY ordinal"
        if limit:
            sql += " LIMIT ?"
            parameters.append(limit)
        with connect(self.path) as connection:
            rows = connection.execute(sql, parameters).fetchall()
        return [self._block(row) for row in rows]

    def block(self, block_id: str) -> BlockRecord | None:
        with connect(self.path) as connection:
            row = connection.execute(
                "SELECT * FROM blocks WHERE block_id = ?", (block_id,)
            ).fetchone()
        return self._block(row) if row else None

    def visual_assets(self, document_id: str) -> list[VisualAssetRecord]:
        with connect(self.path) as connection:
            rows = connection.execute(
                """
                SELECT * FROM visual_assets
                WHERE document_id = ?
                ORDER BY page, kind, asset_id
                """,
                (document_id,),
            ).fetchall()
        return [self._visual_asset(row) for row in rows]

    def get_embedding_vectors(
        self, keys: list[EmbeddingCacheKey]
    ) -> dict[str, list[float]]:
        if not keys:
            return {}
        vectors: dict[str, list[float]] = {}
        keys_by_cache_key = {key.cache_key: key for key in keys}
        cache_keys = list(keys_by_cache_key)
        with connect(self.path) as connection:
            for start in range(0, len(cache_keys), 400):
                batch = cache_keys[start : start + 400]
                placeholders = ", ".join("?" for _ in batch)
                rows = connection.execute(
                    f"""
                    SELECT * FROM embedding_vectors
                    WHERE cache_key IN ({placeholders})
                    """,
                    batch,
                ).fetchall()
                for row in rows:
                    key = keys_by_cache_key[row["cache_key"]]
                    stored_identity = (
                        row["cache_key_version"],
                        row["document_sha256"],
                        row["block_id"],
                        row["normalized_text_sha256"],
                        row["retrieval_backend"],
                        row["backend_version"],
                        row["embedding_model"],
                        row["model_version"],
                        row["dimensions"],
                        row["parameters_sha256"],
                    )
                    requested_identity = (
                        key.cache_key_version,
                        key.document_sha256,
                        key.block_id,
                        key.normalized_text_sha256,
                        key.backend,
                        key.backend_version,
                        key.model,
                        key.model_version,
                        key.dimensions,
                        key.parameters_sha256,
                    )
                    if stored_identity != requested_identity:
                        raise ValueError("Cached embedding identity mismatch")
                    vector = json.loads(row["vector_json"])
                    if not isinstance(vector, list) or len(vector) != key.dimensions:
                        raise ValueError(
                            "Cached embedding vector has invalid dimensions"
                        )
                    vectors[key.cache_key] = [float(value) for value in vector]
        return vectors

    def save_embedding_vectors(
        self,
        records: list[tuple[EmbeddingCacheKey, list[float]]],
    ) -> None:
        if not records:
            return
        for key, vector in records:
            if len(vector) != key.dimensions:
                raise ValueError("Embedding vector has invalid dimensions")
        with connect(self.path) as connection:
            connection.executemany(
                """
                INSERT INTO embedding_vectors (
                    cache_key, cache_key_version, document_sha256, block_id,
                    normalized_text_sha256, retrieval_backend,
                    backend_version, embedding_model, model_version,
                    dimensions, parameters_sha256, vector_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(cache_key) DO NOTHING
                """,
                [
                    (
                        key.cache_key,
                        key.cache_key_version,
                        key.document_sha256,
                        key.block_id,
                        key.normalized_text_sha256,
                        key.backend,
                        key.backend_version,
                        key.model,
                        key.model_version,
                        key.dimensions,
                        key.parameters_sha256,
                        _json(vector),
                    )
                    for key, vector in records
                ],
            )

    def embedding_vector_count(self) -> int:
        with connect(self.path) as connection:
            row = connection.execute(
                "SELECT COUNT(*) AS count FROM embedding_vectors"
            ).fetchone()
        return int(row["count"])

    def save_gold(self, record: GoldEvidenceRecord) -> GoldEvidenceRecord:
        with connect(self.path) as connection:
            connection.execute(
                """
                INSERT INTO gold_evidence (
                    gold_id, document_id, field_name, block_id,
                    status, note, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(document_id, field_name, block_id)
                DO UPDATE SET status=excluded.status, note=excluded.note
                """,
                (
                    record.gold_id,
                    record.document_id,
                    record.field_name,
                    record.block_id,
                    record.status,
                    record.note,
                    record.created_at,
                ),
            )
            row = connection.execute(
                """
                SELECT * FROM gold_evidence
                WHERE document_id = ? AND field_name = ? AND block_id = ?
                """,
                (record.document_id, record.field_name, record.block_id),
            ).fetchone()
        return self._gold(row)

    def delete_gold(self, gold_id: str) -> None:
        with connect(self.path) as connection:
            connection.execute(
                "DELETE FROM gold_evidence WHERE gold_id = ?", (gold_id,)
            )

    def list_gold(
        self,
        document_id: str = "",
        field_name: str = "",
        status: str = "",
    ) -> list[GoldEvidenceRecord]:
        clauses: list[str] = []
        parameters: list[str] = []
        if document_id:
            clauses.append("document_id = ?")
            parameters.append(document_id)
        if field_name:
            clauses.append("field_name = ?")
            parameters.append(field_name)
        if status:
            clauses.append("status = ?")
            parameters.append(status)
        sql = "SELECT * FROM gold_evidence"
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY created_at, gold_id"
        with connect(self.path) as connection:
            rows = connection.execute(sql, parameters).fetchall()
        return [self._gold(row) for row in rows]

    def save_retrieval_run(
        self,
        response: RetrievalResponse,
        k: int,
        created_at: str,
    ) -> None:
        with connect(self.path) as connection:
            connection.execute(
                """
                INSERT INTO retrieval_runs (
                    run_id, document_id, field_name, query_text,
                    k, result_json, retrieval_version, retrieval_backend,
                    backend_version, embedding_model, model_version,
                    parameters_json, query_count, corpus_size, elapsed_ms,
                    cache_enabled, vector_cache_hits, vector_cache_misses,
                    vector_cache_writes, created_at
                ) VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                )
                """,
                (
                    response.run_id,
                    response.document_id,
                    response.field_name,
                    response.query,
                    k,
                    response.model_dump_json(),
                    response.retrieval_version,
                    response.backend.backend,
                    response.backend.backend_version,
                    response.backend.model,
                    response.backend.model_version,
                    _json(response.parameters),
                    response.query_count,
                    response.total_blocks,
                    response.elapsed_ms,
                    int(response.cache.enabled),
                    response.cache.hits,
                    response.cache.misses,
                    response.cache.writes,
                    created_at,
                ),
            )

    def retrieval_run(self, run_id: str) -> dict[str, Any] | None:
        with connect(self.path) as connection:
            row = connection.execute(
                "SELECT * FROM retrieval_runs WHERE run_id = ?", (run_id,)
            ).fetchone()
        if not row:
            return None
        result = dict(row)
        result["result"] = json.loads(result.pop("result_json"))
        result["parameters"] = json.loads(result.pop("parameters_json"))
        return result

    def save_evaluation(
        self,
        evaluation_id: str,
        result: dict[str, Any],
        created_at: str,
    ) -> None:
        with connect(self.path) as connection:
            connection.execute(
                """
                INSERT INTO evaluations (evaluation_id, result_json, created_at)
                VALUES (?, ?, ?)
                """,
                (evaluation_id, _json(result), created_at),
            )

    def latest_evaluation(self) -> dict[str, Any] | None:
        with connect(self.path) as connection:
            row = connection.execute(
                "SELECT result_json FROM evaluations ORDER BY created_at DESC LIMIT 1"
            ).fetchone()
        return json.loads(row["result_json"]) if row else None

    @staticmethod
    def _document(row: sqlite3.Row) -> DocumentRecord:
        return DocumentRecord(
            document_id=row["document_id"],
            sha256=row["sha256"],
            filename=row["filename"],
            source_path=row["source_path"],
            title=row["title"],
            publication_year=row["publication_year"],
            language=row["language"],
            page_count=row["page_count"],
            text_char_count=row["text_char_count"],
            parser_status=row["parser_status"],
            parser_warnings=json.loads(row["parser_warnings_json"]),
            parser_version=row["parser_version"],
            parser_backend=row["parser_backend"],
            parse_elapsed_ms=row["parse_elapsed_ms"],
            screening_status=row["screening_status"],
            screening_reasons=json.loads(row["screening_reasons_json"]),
            missing_required_fields=json.loads(
                row["missing_required_fields_json"]
            ),
        )

    @staticmethod
    def _block(row: sqlite3.Row) -> BlockRecord:
        return BlockRecord(
            block_id=row["block_id"],
            document_id=row["document_id"],
            ordinal=row["ordinal"],
            page=row["page"],
            section=row["section"],
            kind=row["kind"],
            text=row["text"],
            bbox=json.loads(row["bbox_json"]),
            raw_text=row["raw_text"],
            parent_id=row["parent_id"],
            parent_text=row["parent_text"],
            chunk_index=row["chunk_index"],
            chunk_count=row["chunk_count"],
        )

    @staticmethod
    def _visual_asset(row: sqlite3.Row) -> VisualAssetRecord:
        return VisualAssetRecord(
            asset_id=row["asset_id"],
            document_id=row["document_id"],
            page=row["page"],
            kind=row["kind"],
            caption=row["caption"],
            bbox=json.loads(row["bbox_json"]),
            detection_method=row["detection_method"],
            confidence=row["confidence"],
            summary=row["summary"],
            has_structured_content=bool(row["has_structured_content"]),
            digitization_status=row["digitization_status"],
            parser_backend=row["parser_backend"],
            parser_version=row["parser_version"],
        )

    @staticmethod
    def _gold(row: sqlite3.Row) -> GoldEvidenceRecord:
        return GoldEvidenceRecord(
            gold_id=row["gold_id"],
            document_id=row["document_id"],
            field_name=row["field_name"],
            block_id=row["block_id"],
            status=row["status"],
            note=row["note"],
            created_at=row["created_at"],
        )
