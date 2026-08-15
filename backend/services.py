"""Application use-cases that keep the API layer thin."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from .database import Repository
from .embedding_backends import build_embedding_backend
from .pdf_parser import FullDocumentParser, sha256_file
from .requirement_interpreter import RequirementInterpreter
from .retrieval import EvidenceRetriever
from .schemas import (
    GoldEvidenceInput,
    GoldEvidenceRecord,
    ProjectSpec,
    RetrievalResponse,
    SyncResult,
)
from .screening import DocumentScreener
from .settings import settings


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


class EcoEvidenceService:
    def __init__(
        self,
        repository: Repository | None = None,
        retriever: EvidenceRetriever | None = None,
    ) -> None:
        self.repository = repository or Repository()
        self.interpreter = RequirementInterpreter()
        self.parser = FullDocumentParser()
        self.screener = DocumentScreener()
        self.retriever = retriever or EvidenceRetriever(
            build_embedding_backend(
                settings.retrieval_backend,
                cache_folder=settings.model_cache_directory,
                batch_size=settings.embedding_batch_size,
                device=settings.embedding_device,
                local_files_only=settings.embedding_local_files_only,
            ),
            vector_cache=self.repository,
        )

    def interpret_and_save(self, brief: str) -> ProjectSpec:
        spec = self.interpreter.interpret(brief)
        self.repository.save_spec(
            f"spec-{uuid4().hex[:12]}",
            spec,
            utc_now(),
        )
        self.rescreen_documents(spec)
        return spec

    def current_spec(self) -> ProjectSpec | None:
        return self.repository.current_spec()

    def document_overviews(self) -> list[dict]:
        """Derive compact review summaries without duplicating full text."""
        spec = self.current_spec()
        fields = (
            [
                *spec.target_variables,
                *spec.required_context,
                *spec.optional_context,
            ]
            if spec
            else []
        )
        overviews: list[dict] = []
        for document in self.repository.list_documents():
            blocks = self.repository.blocks(document.document_id)
            lowered_text = "\n".join(block.text.lower() for block in blocks)
            covered_fields = [
                field.label
                for field in fields
                if any(
                    term.lower() in lowered_text
                    for term in [field.label, field.name, *field.synonyms]
                    if term
                )
            ]
            figure_count = sum(
                block.kind == "figure_caption" for block in blocks
            )
            table_count = sum(
                block.kind == "table_caption" for block in blocks
            )
            sections = sorted(
                {
                    block.section
                    for block in blocks
                    if block.section != "front_matter"
                }
            )
            if document.parser_status == "failed":
                summary = (
                    f"共 {document.page_count} 页，未读取到可靠文本层；"
                    "需要 OCR 或人工处理后才能判断数据覆盖。"
                )
            else:
                field_text = (
                    "、".join(dict.fromkeys(covered_fields))
                    if covered_fields
                    else "暂无需求字段"
                )
                summary = (
                    f"全文 {document.page_count} 页、{len(blocks)} 个证据块；"
                    f"已定位 {field_text}；"
                    f"识别到 {figure_count} 个图题、{table_count} 个表题。"
                )
            overviews.append(
                {
                    **document.model_dump(),
                    "block_count": len(blocks),
                    "figure_caption_count": figure_count,
                    "table_caption_count": table_count,
                    "sections": sections,
                    "covered_fields": list(dict.fromkeys(covered_fields)),
                    "summary": summary,
                }
            )
        return overviews

    def sync_documents(self, source_directory: Path | None = None) -> SyncResult:
        source = (source_directory or settings.source_directory).resolve()
        if not source.exists():
            raise FileNotFoundError(f"PDF source directory not found: {source}")
        pdf_paths = sorted(source.glob("*.pdf"))
        if not pdf_paths:
            raise FileNotFoundError(f"No PDF files found in: {source}")
        spec = self.current_spec()
        parsed = reused = failed = 0
        for path in pdf_paths:
            digest = sha256_file(path)
            existing = self.repository.document_by_hash(digest)
            if (
                existing
                and existing.parser_version == settings.parser_version
            ):
                reused += 1
                continue
            document, blocks = self.parser.parse(path)
            if spec:
                document = self.screener.screen(document, blocks, spec)
            if document.parser_status == "failed":
                failed += 1
            else:
                parsed += 1
            self.repository.save_document(document, blocks, utc_now())
        if spec:
            self.rescreen_documents(spec)
        return SyncResult(
            parsed=parsed,
            reused=reused,
            failed=failed,
            documents=self.repository.list_documents(),
        )

    def rescreen_documents(self, spec: ProjectSpec) -> None:
        for document in self.repository.list_documents():
            blocks = self.repository.blocks(document.document_id)
            updated = self.screener.screen(document, blocks, spec)
            self.repository.update_screening(updated, utc_now())

    def retrieve(
        self,
        document_id: str,
        field_name: str,
        k: int,
    ) -> RetrievalResponse:
        spec = self.current_spec()
        if not spec:
            raise ValueError("请先解释并确认研究需求。")
        document = self.repository.document(document_id)
        if not document:
            raise KeyError(f"Unknown document: {document_id}")
        blocks = self.repository.blocks(document_id)
        gold_ids = {
            record.block_id
            for record in self.repository.list_gold(
                document_id=document_id,
                field_name=field_name,
            )
        }
        ranking = self.retriever.rank(
            blocks,
            field_name,
            spec,
            gold_ids,
            document_sha256=document.sha256,
        )
        response = RetrievalResponse(
            run_id=f"retrieval-{uuid4().hex[:12]}",
            document_id=document_id,
            field_name=field_name,
            query=ranking.query,
            retrieval_version=settings.retrieval_version,
            backend=self.retriever.backend_metadata,
            parameters=self.retriever.parameters,
            query_count=1,
            total_blocks=len(blocks),
            elapsed_ms=ranking.elapsed_ms,
            cache=ranking.cache,
            hits=ranking.hits[:k],
        )
        self.repository.save_retrieval_run(
            response,
            k,
            utc_now(),
        )
        return response

    def add_gold(self, payload: GoldEvidenceInput) -> GoldEvidenceRecord:
        if not self.repository.document(payload.document_id):
            raise KeyError(f"Unknown document: {payload.document_id}")
        block = self.repository.block(payload.block_id)
        if not block or block.document_id != payload.document_id:
            raise KeyError(f"Unknown block for document: {payload.block_id}")
        return self.repository.save_gold(
            GoldEvidenceRecord(
                gold_id=f"gold-{uuid4().hex[:12]}",
                created_at=utc_now(),
                **payload.model_dump(),
            )
        )
