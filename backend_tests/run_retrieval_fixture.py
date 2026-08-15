"""Reproduce the M2 first-slice comparison report without network access."""

from __future__ import annotations

import json
import math
import tempfile
from pathlib import Path
from typing import Any

from backend.database import Repository
from backend.evaluation import RetrievalEvaluator
from backend.requirement_interpreter import RequirementInterpreter
from backend.retrieval import EvidenceRetriever
from backend.schemas import (
    EvaluationRequest,
    GoldEvidenceRecord,
    RetrievalBackendMetadata,
)
from backend_tests.helpers import block, document


FIXTURE_PATH = (
    Path(__file__).parent / "fixtures" / "retrieval_comparison_v1.json"
)


class DeterministicFixtureEmbeddingBackend:
    """Test-only vector backend; it is explicitly not a neural model."""

    @property
    def metadata(self) -> RetrievalBackendMetadata:
        return RetrievalBackendMetadata(
            backend="fixture-deterministic",
            backend_version="v1",
            model="deterministic-concept-vectors",
            model_version="fixture-v1",
            dimensions=3,
            is_neural=False,
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {"fixture_only": True, "normalization": "l2"}

    def encode(self, text: str) -> list[float]:
        lowered = text.lower()
        values = [
            float(any(term in lowered for term in ("respiration", "co2", "呼吸"))),
            float(any(term in lowered for term in ("species", "pinus", "物种"))),
            float(any(term in lowered for term in ("site", "alpine", "站点"))),
        ]
        norm = math.sqrt(sum(value * value for value in values))
        return [value / norm for value in values] if norm else values


def build_report() -> list[dict[str, Any]]:
    fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    with tempfile.TemporaryDirectory() as directory:
        repository = Repository(Path(directory) / "comparison.sqlite3")
        spec = RequirementInterpreter().interpret(fixture["brief"])
        blocks = [
            block(
                item["ordinal"],
                item["text"],
                section=item["section"],
            )
            for item in fixture["blocks"]
        ]
        repository.save_document(
            document(), blocks, "2026-01-01T00:00:00+00:00"
        )
        for index, query in enumerate(fixture["queries"], 1):
            gold_block = blocks[query["gold_ordinal"] - 1]
            repository.save_gold(
                GoldEvidenceRecord(
                    gold_id=f"fixture-gold-{index}",
                    document_id=gold_block.document_id,
                    field_name=query["field_name"],
                    block_id=gold_block.block_id,
                    status="verified",
                    note=f"{fixture['fixture_id']} synthetic gold",
                    created_at="2026-01-01T00:00:00+00:00",
                )
            )

        request = EvaluationRequest(k_values=[1, 3], gold_status="verified")
        results = [
            RetrievalEvaluator(repository, retriever).evaluate(spec, request)
            for retriever in (
                EvidenceRetriever(),
                EvidenceRetriever(DeterministicFixtureEmbeddingBackend()),
            )
        ]
        return [result.model_dump() for result in results]


if __name__ == "__main__":
    print(json.dumps(build_report(), ensure_ascii=False, indent=2))
