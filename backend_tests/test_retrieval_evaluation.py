from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from backend.database import Repository
from backend.evaluation import RetrievalEvaluator
from backend.requirement_interpreter import RequirementInterpreter
from backend.retrieval import EvidenceRetriever
from backend.schemas import EvaluationRequest, GoldEvidenceRecord

from backend_tests.helpers import block, document


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
        query, ranked = retriever.rank(
            self.blocks,
            "stem_respiration_rate",
            self.spec,
        )

        self.assertIn("stem respiration", query.lower())
        self.assertEqual(self.blocks[2].block_id, ranked[0].block.block_id)
        self.assertEqual(
            {"bm25", "semantic", "term_coverage", "section_prior"},
            set(ranked[0].score_components),
        )

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


if __name__ == "__main__":
    unittest.main()
