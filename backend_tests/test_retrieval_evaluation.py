from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
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
        self.assertEqual(
            "embedding-cache-key-v1",
            response.parameters["vector_cache"]["key_version"],
        )
        self.assertGreaterEqual(saved["elapsed_ms"], 0)
        self.assertTrue(response.cache.enabled)
        self.assertEqual(len(self.blocks), response.cache.misses)
        self.assertEqual(len(self.blocks), response.cache.writes)
        self.assertEqual(0, response.cache.hits)
        self.assertEqual(1, saved["cache_enabled"])
        self.assertEqual(len(self.blocks), saved["vector_cache_misses"])

        warm_response = service.retrieve(
            "doc-test", "stem_respiration_rate", 3
        )

        self.assertEqual(len(self.blocks), warm_response.cache.hits)
        self.assertEqual(0, warm_response.cache.misses)
        self.assertEqual(0, warm_response.cache.writes)
        self.assertEqual(
            len(self.blocks),
            self.repository.embedding_vector_count(),
        )

    def test_vector_cache_invalidates_on_identity_or_content_change(self) -> None:
        first_backend = DeterministicFixtureEmbeddingBackend()
        first_retriever = EvidenceRetriever(
            first_backend,
            vector_cache=self.repository,
        )
        document_sha256 = document().sha256

        cold = first_retriever.rank(
            self.blocks,
            "stem_respiration_rate",
            self.spec,
            document_sha256=document_sha256,
        )
        warm = first_retriever.rank(
            self.blocks,
            "stem_respiration_rate",
            self.spec,
            document_sha256=document_sha256,
        )

        self.assertEqual(len(self.blocks), cold.cache.misses)
        self.assertEqual(len(self.blocks), warm.cache.hits)
        self.assertEqual(2 + len(self.blocks), first_backend.encode_calls)
        self.assertEqual(1, first_backend.passage_batch_calls)

        document_changed = first_retriever.rank(
            self.blocks,
            "stem_respiration_rate",
            self.spec,
            document_sha256="sha-different-document",
        )

        self.assertEqual(0, document_changed.cache.hits)
        self.assertEqual(len(self.blocks), document_changed.cache.misses)

        changed_blocks = [*self.blocks]
        changed_blocks[0] = self.blocks[0].model_copy(
            update={"text": self.blocks[0].text + " Changed normalized text."}
        )
        text_changed = first_retriever.rank(
            changed_blocks,
            "stem_respiration_rate",
            self.spec,
            document_sha256=document_sha256,
        )

        self.assertEqual(len(self.blocks) - 1, text_changed.cache.hits)
        self.assertEqual(1, text_changed.cache.misses)

        versioned_backend = DeterministicFixtureEmbeddingBackend(
            model_version="fixture-v2"
        )
        versioned_retriever = EvidenceRetriever(
            versioned_backend,
            vector_cache=self.repository,
        )
        model_changed = versioned_retriever.rank(
            self.blocks,
            "stem_respiration_rate",
            self.spec,
            document_sha256=document_sha256,
        )

        self.assertEqual(0, model_changed.cache.hits)
        self.assertEqual(len(self.blocks), model_changed.cache.misses)
        self.assertEqual(1 + len(self.blocks), versioned_backend.encode_calls)

        parameter_backend = DeterministicFixtureEmbeddingBackend(
            parameter_revision="params-v2"
        )
        parameter_changed = EvidenceRetriever(
            parameter_backend,
            vector_cache=self.repository,
        ).rank(
            self.blocks,
            "stem_respiration_rate",
            self.spec,
            document_sha256=document_sha256,
        )

        self.assertEqual(0, parameter_changed.cache.hits)
        self.assertEqual(len(self.blocks), parameter_changed.cache.misses)

    def test_legacy_retrieval_runs_are_preserved_during_schema_upgrade(self) -> None:
        legacy_path = Path(self.temporary_directory.name) / "legacy.sqlite3"
        with closing(sqlite3.connect(legacy_path)) as connection:
            with connection:
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
                    INSERT INTO retrieval_runs
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
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
                EvidenceRetriever(vector_cache=repository),
                EvidenceRetriever(
                    DeterministicFixtureEmbeddingBackend(),
                    vector_cache=repository,
                ),
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
            self.assertEqual(8, report.coverage["vector_cache_hits"])
            self.assertEqual(4, report.coverage["vector_cache_misses"])
            self.assertTrue(
                all(query["top_block_ids"] for query in report.per_query)
            )


if __name__ == "__main__":
    unittest.main()
