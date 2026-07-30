"""Small SQLite repository for canonical parsed text and audit records."""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from .schemas import BlockRecord, DocumentRecord, GoldEvidenceRecord, ProjectSpec
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
    FOREIGN KEY(document_id) REFERENCES documents(document_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS blocks_document_ordinal_idx
ON blocks(document_id, ordinal);

CREATE INDEX IF NOT EXISTS blocks_document_page_idx
ON blocks(document_id, page);

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
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS evaluations (
    evaluation_id TEXT PRIMARY KEY,
    result_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def initialize_database(path: Path | None = None) -> None:
    database_path = path or settings.database_path
    database_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(database_path) as connection:
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA foreign_keys=ON")
        connection.executescript(SCHEMA)


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
    ) -> None:
        with connect(self.path) as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO documents (
                    document_id, sha256, filename, source_path, title,
                    publication_year, language, page_count, text_char_count,
                    parser_status, parser_warnings_json, parser_version,
                    screening_status, screening_reasons_json,
                    missing_required_fields_json, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    document.screening_status,
                    _json(document.screening_reasons),
                    _json(document.missing_required_fields),
                    updated_at,
                ),
            )
            connection.execute(
                "DELETE FROM blocks WHERE document_id = ?", (document.document_id,)
            )
            connection.executemany(
                """
                INSERT INTO blocks (
                    block_id, document_id, ordinal, page, section,
                    kind, text, bbox_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
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
                    )
                    for block in blocks
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
        run_id: str,
        document_id: str,
        field_name: str,
        query: str,
        k: int,
        result: dict[str, Any],
        retrieval_version: str,
        created_at: str,
    ) -> None:
        with connect(self.path) as connection:
            connection.execute(
                """
                INSERT INTO retrieval_runs (
                    run_id, document_id, field_name, query_text,
                    k, result_json, retrieval_version, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    document_id,
                    field_name,
                    query,
                    k,
                    _json(result),
                    retrieval_version,
                    created_at,
                ),
            )

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
