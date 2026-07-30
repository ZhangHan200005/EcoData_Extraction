from __future__ import annotations

import unittest

from backend.requirement_interpreter import RequirementInterpreter
from backend.screening import DocumentScreener

from backend_tests.helpers import block, document


class DocumentScreenerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.screener = DocumentScreener()
        self.spec = RequirementInterpreter().interpret(
            "提取树干呼吸数据，必须报告物种和样本量。"
        )

    def test_usable_requires_numeric_target_and_all_required_context(self) -> None:
        blocks = [
            block(1, "Methods. We sampled 12 trees (sample size n=12)."),
            block(2, "Species was Pinus sylvestris."),
            block(
                3,
                "Stem respiration was 1.8 µmol CO2 m-2 s-1.",
                section="results",
            ),
        ]
        screened = self.screener.screen(document(), blocks, self.spec)

        self.assertEqual("usable", screened.screening_status)
        self.assertEqual([], screened.missing_required_fields)

    def test_relative_keeps_numeric_target_with_missing_context(self) -> None:
        blocks = [
            block(1, "Species was Pinus sylvestris."),
            block(
                2,
                "Stem respiration was 1.8 µmol CO2 m-2 s-1.",
                section="results",
            ),
        ]
        screened = self.screener.screen(document(), blocks, self.spec)

        self.assertEqual("relative", screened.screening_status)
        self.assertIn("sample_size", screened.missing_required_fields)

    def test_nodata_and_failed_are_distinct(self) -> None:
        no_data = self.screener.screen(
            document(),
            [block(1, "Stem respiration was discussed without observations.")],
            self.spec,
        )
        failed = self.screener.screen(
            document(parser_status="failed"),
            [],
            self.spec,
        )

        self.assertEqual("nodata", no_data.screening_status)
        self.assertEqual("failed", failed.screening_status)

    def test_excluded_model_prediction_does_not_count_as_observed_data(self) -> None:
        spec = RequirementInterpreter().interpret(
            "提取树干呼吸数据，不接受模型预测值。"
        )
        screened = self.screener.screen(
            document(),
            [
                block(
                    1,
                    "The model predicted stem respiration of "
                    "1.8 µmol CO2 m-2 s-1.",
                    section="results",
                )
            ],
            spec,
        )

        self.assertEqual("nodata", screened.screening_status)
        self.assertTrue(
            any("排除模型预测证据块" in reason for reason in screened.screening_reasons)
        )


if __name__ == "__main__":
    unittest.main()
