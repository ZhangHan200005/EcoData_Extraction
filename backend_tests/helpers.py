from __future__ import annotations

from backend.schemas import BlockRecord, DocumentRecord


def document(
    document_id: str = "doc-test",
    *,
    parser_status: str = "ok",
) -> DocumentRecord:
    return DocumentRecord(
        document_id=document_id,
        sha256=f"sha-{document_id}",
        filename=f"{document_id}.pdf",
        source_path=f"/tmp/{document_id}.pdf",
        title="Synthetic stem respiration study",
        publication_year=2024,
        language="en",
        page_count=4,
        text_char_count=500,
        parser_status=parser_status,
        parser_version="test-parser-v1",
    )


def block(
    ordinal: int,
    text: str,
    *,
    document_id: str = "doc-test",
    section: str = "methods",
    kind: str = "text",
) -> BlockRecord:
    return BlockRecord(
        block_id=f"{document_id}-block-{ordinal}",
        document_id=document_id,
        ordinal=ordinal,
        page=1 + ordinal // 4,
        section=section,
        kind=kind,
        text=text,
        bbox=[50.0, 80.0, 500.0, 120.0],
    )
