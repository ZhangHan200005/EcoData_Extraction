"""Quantitative evidence-retrieval evaluation against verified gold blocks."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from statistics import mean
from time import perf_counter
from typing import Any
from uuid import uuid4

from .database import Repository
from .retrieval import EvidenceRetriever
from .schemas import EvaluationRequest, EvaluationResponse, ProjectSpec
from .settings import settings


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _average(records: list[dict[str, float]], key: str) -> float:
    return round(mean(record[key] for record in records), 4) if records else 0.0


class RetrievalEvaluator:
    def __init__(
        self,
        repository: Repository,
        retriever: EvidenceRetriever,
    ) -> None:
        self.repository = repository
        self.retriever = retriever

    def evaluate(
        self,
        spec: ProjectSpec,
        request: EvaluationRequest,
    ) -> EvaluationResponse:
        evaluation_started_at = perf_counter()
        gold_records = self.repository.list_gold(
            status="" if request.gold_status == "all" else request.gold_status
        )
        grouped_gold: dict[tuple[str, str], set[str]] = defaultdict(set)
        for record in gold_records:
            grouped_gold[(record.document_id, record.field_name)].add(
                record.block_id
            )

        k_values = sorted({max(1, min(30, value)) for value in request.k_values})
        per_query: list[dict[str, Any]] = []
        corpus_blocks_scored = 0
        vector_cache_hits = vector_cache_misses = vector_cache_writes = 0
        for (document_id, field_name), gold_ids in grouped_gold.items():
            document = self.repository.document(document_id)
            blocks = self.repository.blocks(document_id)
            if not document or not blocks:
                continue
            corpus_blocks_scored += len(blocks)
            ranking = self.retriever.rank(
                blocks,
                field_name,
                spec,
                gold_ids,
                document_sha256=document.sha256,
            )
            vector_cache_hits += ranking.cache.hits
            vector_cache_misses += ranking.cache.misses
            vector_cache_writes += ranking.cache.writes
            ranked_ids = [hit.block.block_id for hit in ranking.hits]
            first_rank = next(
                (
                    index
                    for index, block_id in enumerate(ranked_ids, 1)
                    if block_id in gold_ids
                ),
                None,
            )
            metrics: dict[str, dict[str, float]] = {}
            for k in k_values:
                returned = ranked_ids[:k]
                relevant = len(set(returned) & gold_ids)
                metrics[str(k)] = {
                    "hit": 1.0 if relevant else 0.0,
                    "recall": relevant / len(gold_ids),
                    "precision": relevant / len(returned) if returned else 0.0,
                }
            per_query.append(
                {
                    "document_id": document_id,
                    "field_name": field_name,
                    "gold_count": len(gold_ids),
                    "gold_block_ids": sorted(gold_ids),
                    "top_block_ids": ranked_ids[: max(k_values, default=0)],
                    "first_relevant_rank": first_rank,
                    "reciprocal_rank": 1 / first_rank if first_rank else 0.0,
                    "elapsed_ms": ranking.elapsed_ms,
                    "cache": ranking.cache.model_dump(),
                    "metrics": metrics,
                }
            )

        metrics_at_k: dict[str, dict[str, float]] = {}
        for k in k_values:
            records = [
                {
                    "hit": query["metrics"][str(k)]["hit"],
                    "recall": query["metrics"][str(k)]["recall"],
                    "precision": query["metrics"][str(k)]["precision"],
                }
                for query in per_query
            ]
            metrics_at_k[str(k)] = {
                "hit_rate": _average(records, "hit"),
                "recall": _average(records, "recall"),
                "precision": _average(records, "precision"),
            }

        by_field: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for query in per_query:
            by_field[query["field_name"]].append(query)
        per_field: list[dict[str, Any]] = []
        for field_name, queries in sorted(by_field.items()):
            field_metrics: dict[str, Any] = {
                "field_name": field_name,
                "query_count": len(queries),
                "gold_count": sum(query["gold_count"] for query in queries),
                "mrr": round(
                    mean(query["reciprocal_rank"] for query in queries), 4
                ),
                "metrics": {},
            }
            for k in k_values:
                field_metrics["metrics"][str(k)] = {
                    metric: round(
                        mean(
                            query["metrics"][str(k)][metric]
                            for query in queries
                        ),
                        4,
                    )
                    for metric in ("hit", "recall", "precision")
                }
            per_field.append(field_metrics)

        generated_at = utc_now()
        retrieval_elapsed_ms = round(
            sum(query["elapsed_ms"] for query in per_query), 6
        )
        evaluation_elapsed_ms = round(
            (perf_counter() - evaluation_started_at) * 1000, 6
        )
        response = EvaluationResponse(
            evaluation_id=f"eval-{uuid4().hex[:12]}",
            generated_at=generated_at,
            retrieval_version=settings.retrieval_version,
            backend=self.retriever.backend_metadata,
            parameters=self.retriever.parameters,
            gold_status=request.gold_status,
            coverage={
                "annotated_queries": len(grouped_gold),
                "evaluated_queries": len(per_query),
                "gold_blocks": len(gold_records),
                "documents": len(
                    {document_id for document_id, _ in grouped_gold}
                ),
                "fields": len({field for _, field in grouped_gold}),
                "corpus_blocks_scored": corpus_blocks_scored,
                "vector_cache_hits": vector_cache_hits,
                "vector_cache_misses": vector_cache_misses,
                "vector_cache_writes": vector_cache_writes,
            },
            timing={
                "retrieval_elapsed_ms": retrieval_elapsed_ms,
                "evaluation_elapsed_ms": evaluation_elapsed_ms,
                "mean_query_ms": round(
                    retrieval_elapsed_ms / len(per_query), 6
                )
                if per_query
                else 0.0,
            },
            metrics_at_k=metrics_at_k,
            mean_reciprocal_rank=round(
                mean(query["reciprocal_rank"] for query in per_query), 4
            )
            if per_query
            else 0.0,
            per_field=per_field,
            per_query=per_query,
        )
        self.repository.save_evaluation(
            response.evaluation_id,
            response.model_dump(),
            generated_at,
        )
        return response
