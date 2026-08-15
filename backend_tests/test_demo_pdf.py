from __future__ import annotations

import unittest
from pathlib import Path

from backend.pdf_parser import FullDocumentParser
from backend.requirement_interpreter import RequirementInterpreter
from backend.retrieval import EvidenceRetriever
from backend.screening import DocumentScreener


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEMO_PDF = (
    PROJECT_ROOT
    / "demo"
    / "pdfs"
    / "synthetic_stem_respiration_study.pdf"
)
DEMO_BRIEF = (
    "我希望提取树干呼吸速率数据，必须报告物种和样本量；"
    "关注站点、经纬度、胸径、测量温度和测量方法。"
    "接受正文、表格和数据图中的观测值或均值，不接受模型预测值。"
)


class PublicDemoPdfTests(unittest.TestCase):
    def test_demo_pdf_runs_through_parse_screen_and_retrieve(self) -> None:
        self.assertTrue(DEMO_PDF.is_file())

        document, blocks = FullDocumentParser().parse(DEMO_PDF)
        self.assertEqual("ok", document.parser_status)
        self.assertEqual(1, document.page_count)
        self.assertTrue(all(block.page == 1 for block in blocks))
        self.assertTrue(all(len(block.bbox) == 4 for block in blocks))

        spec = RequirementInterpreter().interpret(DEMO_BRIEF)
        screened = DocumentScreener().screen(document, blocks, spec)
        self.assertEqual("usable", screened.screening_status)
        self.assertEqual([], screened.missing_required_fields)

        ranking = EvidenceRetriever().rank(
            blocks,
            "stem_respiration_rate",
            spec,
        )
        self.assertIn("2.40 micromol CO2 m-2 s-1", ranking.hits[0].block.text)
        self.assertEqual(1, ranking.hits[0].block.page)
        self.assertEqual("results", ranking.hits[0].block.section)


if __name__ == "__main__":
    unittest.main()
