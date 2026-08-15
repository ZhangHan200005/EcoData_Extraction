"""FastAPI entry point for the local evidence-retrieval workbench."""

from __future__ import annotations

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from .database import Repository, initialize_database
from .embedding_backends import EmbeddingBackendUnavailableError
from .evaluation import RetrievalEvaluator
from .retrieval import EMBEDDING_CACHE_KEY_VERSION
from .schemas import (
    EvaluationRequest,
    EvaluationResponse,
    GoldEvidenceInput,
    GoldEvidenceRecord,
    RequirementInput,
    RetrievalComparisonResponse,
    RetrievalRequest,
    RetrievalResponse,
    SyncResult,
    VisualAssetRecord,
)
from .services import EcoEvidenceService
from .settings import settings


initialize_database()
repository = Repository()
service = EcoEvidenceService(repository)
evaluator = RetrievalEvaluator(repository, service.retriever)

app = FastAPI(
    title="EcoEvidence MVP 1.1",
    version="1.1.0",
    description="Project-guided PDF parsing and measurable evidence retrieval.",
)
app.add_middleware(
    CORSMiddleware,
    # Local development may move the frontend to 3001/3002 when a stale
    # preview still owns 3000. Restrict the regex to loopback hosts while
    # allowing any local development port.
    allow_origin_regex=r"^https?://(?:localhost|127\.0\.0\.1)(?::\d+)?$",
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health() -> dict:
    return {
        "ok": True,
        "source_directory": str(settings.source_directory),
        "database_path": str(settings.database_path),
        "parser_version": settings.parser_version,
        "parser_backend": settings.parser_backend,
        "chunking_version": settings.chunking_version,
        "retrieval_version": settings.retrieval_version,
        "retrieval_backend": service.retriever.backend_metadata.model_dump(),
        "retrieval_backend_runtime": (
            service.retriever.backend_runtime_status
        ),
        "vector_cache": {
            "enabled": service.retriever.cache_enabled,
            "key_version": EMBEDDING_CACHE_KEY_VERSION,
        },
    }


@app.get("/api/state")
def state() -> dict:
    return {
        "spec": service.current_spec(),
        "documents": service.document_overviews(),
        "gold": repository.list_gold(),
        "latest_evaluation": repository.latest_evaluation(),
        "source_directory": str(settings.source_directory),
    }


@app.post("/api/spec/interpret")
def interpret_requirements(payload: RequirementInput) -> dict:
    try:
        return {"spec": service.interpret_and_save(payload.brief)}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/documents/sync", response_model=SyncResult)
def sync_documents() -> SyncResult:
    try:
        return service.sync_documents()
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/documents/{document_id}/blocks")
def document_blocks(
    document_id: str,
    query: str = Query(default="", max_length=200),
    limit: int = Query(default=80, ge=1, le=300),
) -> dict:
    if not repository.document(document_id):
        raise HTTPException(status_code=404, detail="Document not found")
    return {
        "blocks": repository.blocks(document_id, query=query, limit=limit),
        "query": query,
    }


@app.get(
    "/api/documents/{document_id}/assets",
    response_model=list[VisualAssetRecord],
)
def document_assets(document_id: str) -> list[VisualAssetRecord]:
    if not repository.document(document_id):
        raise HTTPException(status_code=404, detail="Document not found")
    return repository.visual_assets(document_id)


@app.post("/api/retrieve", response_model=RetrievalResponse)
def retrieve(payload: RetrievalRequest) -> RetrievalResponse:
    try:
        return service.retrieve(
            payload.document_id,
            payload.field_name,
            payload.k,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except EmbeddingBackendUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post(
    "/api/retrieve/compare",
    response_model=RetrievalComparisonResponse,
)
def compare_retrieval(
    payload: RetrievalRequest,
) -> RetrievalComparisonResponse:
    try:
        return service.compare_retrieval(
            payload.document_id,
            payload.field_name,
            payload.k,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/gold", response_model=list[GoldEvidenceRecord])
def list_gold(
    document_id: str = "",
    field_name: str = "",
    status: str = "",
) -> list[GoldEvidenceRecord]:
    return repository.list_gold(document_id, field_name, status)


@app.post("/api/gold", response_model=GoldEvidenceRecord)
def add_gold(payload: GoldEvidenceInput) -> GoldEvidenceRecord:
    try:
        return service.add_gold(payload)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.delete("/api/gold/{gold_id}")
def delete_gold(gold_id: str) -> dict:
    repository.delete_gold(gold_id)
    return {"ok": True}


@app.post("/api/evaluate", response_model=EvaluationResponse)
def evaluate(payload: EvaluationRequest) -> EvaluationResponse:
    spec = service.current_spec()
    if not spec:
        raise HTTPException(status_code=400, detail="请先解释并确认研究需求。")
    try:
        return evaluator.evaluate(spec, payload)
    except EmbeddingBackendUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
