from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from backend.database import Repository
from backend.evaluation import RetrievalEvaluator
from backend.requirement_interpreter import RequirementInterpreter
from backend.retrieval import EvidenceRetriever
from backend.schemas import (
    EvaluationRequest,
    GoldEvidenceRecord,
)
from backend.services import EcoEvidenceService

from backend_tests.helpers import block, document
from backend_tests.run_retrieval_fixture import (
    FIXTURE_PATH,
    DeterministicFixtureEmbeddingBackend,
)


class RetrievalEvaluationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.repository = Repository(
            Path(self.temporary_directory.name) / "test.sqlite3"
        )
        self.spec = RequirementInterpreter().interpret(
            "提取树干呼吸速率数据，必须报告物种。"
        )
        self.blocks = [
            block(1, "The experiment was conducted at an alpine site."),
            block(2, "Five Pinus trees were measured with an IRGA chamber."),
            block(
                3,
                "Mean stem respiration was 1.8 µmol CO2 m-2 s-1 at 20 °C.",
                section="results",
            ),
            block(4, "Soil water content varied during the season."),
        ]
        self.repository.save_document(
            document(),
            self.blocks,
            "2026-01-01T00:00:00+00:00",
        )

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def test_hybrid_ranker_exposes_components_and_places_evidence_first(self) -> None:
        retriever = EvidenceRetriever()
        ranking = retriever.rank(
            self.blocks,
            "stem_respiration_rate",
            self.spec,
        )

        self.assertIn("stem respiration", ranking.query.lower())
        self.assertEqual(self.blocks[2].block_id, ranking.hits[0].block.block_id)
        self.assertEqual(
            {"bm25", "semantic", "term_coverage", "section_prior"},
            set(ranking.hits[0].score_components),
        )
        self.assertEqual("hashing", retriever.backend_metadata.backend)
        self.assertFalse(retriever.backend_metadata.is_neural)
        self.assertGreaterEqual(ranking.elapsed_ms, 0)

    def test_evaluator_computes_gold_based_metrics(self) -> None:
        gold_block = self.blocks[2]
        self.repository.save_gold(
            GoldEvidenceRecord(
                gold_id="gold-1",
                document_id=gold_block.document_id,
                field_name="stem_respiration_rate",
                block_id=gold_block.block_id,
                status="verified",
                note="synthetic gold",
                created_at="2026-01-01T00:00:00+00:00",
            )
        )
        evaluator = RetrievalEvaluator(self.repository, EvidenceRetriever())
        result = evaluator.evaluate(
            self.spec,
            EvaluationRequest(k_values=[1, 3], gold_status="verified"),
        )

        self.assertEqual(1, result.coverage["evaluated_queries"])
        self.assertEqual(1.0, result.metrics_at_k["1"]["hit_rate"])
        self.assertEqual(1.0, result.metrics_at_k["1"]["recall"])
        self.assertEqual(1.0, result.metrics_at_k["1"]["precision"])
        self.assertEqual(1.0, result.mean_reciprocal_rank)
        self.assertEqual("hashing", result.backend.backend)
        self.assertGreaterEqual(result.timing["evaluation_elapsed_ms"], 0)
        self.assertEqual(
            [gold_block.block_id], result.per_query[0]["gold_block_ids"]
        )

    def test_retrieval_run_persists_backend_model_parameters_and_latency(self) -> None:
        self.repository.save_spec(
            "spec-test", self.spec, "2026-01-01T00:00:00+00:00"
        )
        service = EcoEvidenceService(self.repository)

        response = service.retrieve("doc-test", "stem_respiration_rate", 3)
        saved = self.repository.retrieval_run(response.run_id)

        self.assertIsNotNone(saved)
        assert saved is not None
        self.assertEqual("hashing", saved["retrieval_backend"])
        self.assertEqual("blake2b-character-ngram", saved["embedding_model"])
        self.assertEqual(response.backend.model_version, saved["model_version"])
        self.assertEqual(1, saved["query_count"])
        self.assertEqual(len(self.blocks), saved["corpus_size"])
        self.assertEqual(response.parameters, saved["parameters"])
        self.assertGreaterEqual(saved["elapsed_ms"], 0)

    def test_legacy_retrieval_runs_are_preserved_during_schema_upgrade(self) -> None:
        legacy_path = Path(self.temporary_directory.name) / "legacy.sqlite3"
        with sqlite3.connect(legacy_path) as connection:
            connection.execute(
                """
                CREATE TABLE retrieval_runs (
                    run_id TEXT PRIMARY KEY,
                    document_id TEXT NOT NULL,
                    field_name TEXT NOT NULL,
                    query_text TEXT NOT NULL,
                    k INTEGER NOT NULL,
                    result_json TEXT NOT NULL,
                    retrieval_version TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                INSERT INTO retrieval_runs VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "legacy-run",
                    "legacy-doc",
                    "species",
                    "species",
                    3,
                    "{}",
                    "hybrid-bm25-hash-v1",
                    "2026-01-01T00:00:00+00:00",
                ),
            )

        upgraded = Repository(legacy_path).retrieval_run("legacy-run")

        self.assertIsNotNone(upgraded)
        assert upgraded is not None
        self.assertEqual("unknown", upgraded["retrieval_backend"])
        self.assertEqual("hybrid-bm25-hash-v1", upgraded["retrieval_version"])
        self.assertEqual({}, upgraded["result"])

    def test_versioned_multi_query_fixture_runs_with_both_backends(self) -> None:
        fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
        repository = Repository(
            Path(self.temporary_directory.name) / "comparison.sqlite3"
        )
        spec = RequirementInterpreter().interpret(fixture["brief"])
        fixture_blocks = [
            block(
                item["ordinal"],
                item["text"],
                section=item["section"],
            )
            for item in fixture["blocks"]
        ]
        repository.save_document(
            document(), fixture_blocks, "2026-01-01T00:00:00+00:00"
        )
        for index, query in enumerate(fixture["queries"], 1):
            gold_block = fixture_blocks[query["gold_ordinal"] - 1]
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
        reports = [
            RetrievalEvaluator(repository, retriever).evaluate(spec, request)
            for retriever in (
                EvidenceRetriever(),
                EvidenceRetriever(DeterministicFixtureEmbeddingBackend()),
            )
        ]

        self.assertEqual(
            ["hashing", "fixture-deterministic"],
            [report.backend.backend for report in reports],
        )
        for report in reports:
            self.assertEqual(
                len(fixture["queries"]),
                report.coverage["evaluated_queries"],
            )
            self.assertEqual(len(fixture["queries"]), len(report.per_query))
            self.assertIn("1", report.metrics_at_k)
            self.assertGreaterEqual(report.mean_reciprocal_rank, 0)
            self.assertTrue(
                all(query["top_block_ids"] for query in report.per_query)
            )


if __name__ == "__main__":
    unittest.main()
