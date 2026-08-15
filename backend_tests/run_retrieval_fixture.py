"""Reproduce offline M2 reports and optionally run the pinned neural model."""

from __future__ import annotations

import argparse
import json
import math
import tempfile
from pathlib import Path
from typing import Any

from backend.database import Repository
from backend.embedding_backends import MultilingualE5SmallEmbeddingBackend
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

    def __init__(
        self,
        model_version: str = "fixture-v1",
        parameter_revision: str = "params-v1",
    ) -> None:
        self.model_version = model_version
        self.parameter_revision = parameter_revision
        self.encode_calls = 0
        self.passage_batch_calls = 0

    @property
    def metadata(self) -> RetrievalBackendMetadata:
        return RetrievalBackendMetadata(
            backend="fixture-deterministic",
            backend_version="v1",
            model="deterministic-concept-vectors",
            model_version=self.model_version,
            dimensions=3,
            is_neural=False,
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "fixture_only": True,
            "normalization": "l2",
            "parameter_revision": self.parameter_revision,
        }

    @property
    def runtime_status(self) -> dict[str, Any]:
        return {
            "ready": True,
            "dependency": "test-fixture",
            "dependency_version": "fixture-v1",
        }

    def _encode(self, text: str) -> list[float]:
        self.encode_calls += 1
        lowered = text.lower()
        values = [
            float(any(term in lowered for term in ("respiration", "co2", "呼吸"))),
            float(any(term in lowered for term in ("species", "pinus", "物种"))),
            float(any(term in lowered for term in ("site", "alpine", "站点"))),
        ]
        norm = math.sqrt(sum(value * value for value in values))
        return [value / norm for value in values] if norm else values

    def encode_query(self, text: str) -> list[float]:
        return self._encode(text)

    def encode_passages(self, texts: list[str]) -> list[list[float]]:
        if texts:
            self.passage_batch_calls += 1
        return [self._encode(text) for text in texts]


def build_report(
    *,
    include_neural: bool = False,
    model_cache: Path | None = None,
    local_files_only: bool = False,
) -> list[dict[str, Any]]:
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
        retrievers = [
            EvidenceRetriever(vector_cache=repository),
            EvidenceRetriever(
                DeterministicFixtureEmbeddingBackend(),
                vector_cache=repository,
            ),
        ]
        if include_neural:
            retrievers.append(
                EvidenceRetriever(
                    MultilingualE5SmallEmbeddingBackend(
                        model_cache or Path("data/models"),
                        local_files_only=local_files_only,
                    ),
                    vector_cache=repository,
                )
            )
        results = [
            RetrievalEvaluator(repository, retriever).evaluate(spec, request)
            for retriever in retrievers
        ]
        return [result.model_dump() for result in results]


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--include-neural", action="store_true")
    parser.add_argument("--model-cache", type=Path, default=Path("data/models"))
    parser.add_argument("--local-files-only", action="store_true")
    arguments = parser.parse_args()
    print(
        json.dumps(
            build_report(
                include_neural=arguments.include_neural,
                model_cache=arguments.model_cache,
                local_files_only=arguments.local_files_only,
            ),
            ensure_ascii=False,
            indent=2,
        )
    )
