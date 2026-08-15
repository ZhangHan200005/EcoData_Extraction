from __future__ import annotations

import unittest

from backend.requirement_interpreter import RequirementInterpreter


class RequirementInterpreterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.interpreter = RequirementInterpreter()

    def test_free_text_is_split_into_reviewable_fields(self) -> None:
        spec = self.interpreter.interpret(
            "我希望提取树干呼吸速率数据，必须报告物种和样本量；"
            "关注站点、经纬度、胸径、测量温度和测量方法。"
            "接受正文、表格和数据图，不接受模型预测值。"
        )

        self.assertIn(
            "stem_respiration_rate",
            {field.name for field in spec.target_variables},
        )
        self.assertEqual(
            {"species", "sample_size"},
            {field.name for field in spec.required_context},
        )
        self.assertTrue(
            {"site_name", "latitude", "longitude", "measurement_method"}
            <= {field.name for field in spec.optional_context}
        )
        self.assertEqual(["text", "table", "figure"], spec.accepted_sources)
        self.assertIn("model_prediction", spec.exclusions)

    def test_unknown_target_stays_reviewable_instead_of_disappearing(self) -> None:
        spec = self.interpreter.interpret(
            "我要提取叶片韧性数据，关注物种和站点，不限制数据来源。"
        )

        self.assertEqual("custom_target", spec.target_variables[0].name)
        self.assertTrue(spec.target_variables[0].synonyms)
        self.assertTrue(spec.interpretation_warnings)


if __name__ == "__main__":
    unittest.main()
