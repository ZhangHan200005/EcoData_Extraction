from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from pypdf import PdfWriter
from pypdf.generic import (
    DecodedStreamObject,
    DictionaryObject,
    NameObject,
)

from backend.database import Repository
from backend.pdf_parser import (
    FullDocumentParser,
    _child_chunks,
    _normalized_text,
    _order_lines,
    _remove_repeated_margins,
    _visual_assets,
)
from backend.requirement_interpreter import RequirementInterpreter
from backend.retrieval import EvidenceRetriever
from backend.schemas import GoldEvidenceRecord
from backend_tests.helpers import block, document


def _write_two_column_pdf(path: Path) -> None:
    writer = PdfWriter()
    page = writer.add_blank_page(width=612, height=792)
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    font_ref = writer._add_object(font)
    page[NameObject("/Resources")] = DictionaryObject(
        {
            NameObject("/Font"): DictionaryObject(
                {NameObject("/F1"): font_ref}
            )
        }
    )
    lines = [
        (72, 760, "Synthetic two-column ecology study"),
        (72, 720, "Methods"),
        (72, 700, "Study site coordinates were 23.50 N,"),
        (72, 684, "101.25 E in a subtropical forest."),
        (72, 668, "Stem respiration was measured monthly"),
        (72, 652, "with an infrared gas analyzer."),
        (330, 720, "Results"),
        (330, 700, "Observed stem respiration increased."),
        (330, 684, "Figure 1 Stem respiration by month"),
        (330, 668, "Table 1 Site observations"),
        (330, 652, "Values are observations, not predictions."),
    ]
    commands = ["BT", "/F1 10 Tf"]
    for x, y, text in lines:
        escaped = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        commands.append(f"1 0 0 1 {x} {y} Tm ({escaped}) Tj")
    commands.append("ET")
    stream = DecodedStreamObject()
    stream.set_data("\n".join(commands).encode("ascii"))
    page[NameObject("/Contents")] = writer._add_object(stream)
    with path.open("wb") as handle:
        writer.write(handle)


class PdfParserV2Tests(unittest.TestCase):
    def test_full_page_image_is_reported_as_scan_candidate(self) -> None:
        class FullPageImage:
            width = 100
            height = 100
            images = [
                {"x0": 0, "top": 0, "x1": 100, "bottom": 100}
            ]

            @staticmethod
            def find_tables() -> list[object]:
                return []

        assets = _visual_assets(FullPageImage(), "doc-scan", 1, [])

        self.assertEqual(1, len(assets))
        self.assertEqual("image", assets[0].kind)
        self.assertEqual(
            "full-page-image-scan-candidate", assets[0].detection_method
        )
        self.assertIn("OCR", assets[0].summary)

    def test_scientific_spacing_and_control_characters_are_normalized(self) -> None:
        self.assertEqual(
            "Q10 and CO2; n=12 at 17.9 °C",
            _normalized_text("Q 10 and CO 2\u0082; n = 12 at 17. 9 °C"),
        )

    def test_two_column_pdf_keeps_column_reading_order_and_visual_inventory(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            pdf_path = Path(directory) / "two-column.pdf"
            _write_two_column_pdf(pdf_path)

            parsed, blocks, assets = FullDocumentParser().parse_with_assets(
                pdf_path
            )

        joined = "\n".join(item.text for item in blocks)
        self.assertEqual("ok", parsed.parser_status)
        self.assertEqual("pdfplumber-reading-order-v2", parsed.parser_version)
        self.assertLess(joined.index("Study site coordinates"), joined.index("Results"))
        self.assertIn("23.50 N, 101.25 E", joined)
        self.assertEqual({"figure", "table"}, {asset.kind for asset in assets})
        self.assertTrue(all(len(asset.bbox) == 4 for asset in assets))

    def test_reading_order_places_left_column_before_right_column(self) -> None:
        lines = [
            {"text": f"left {index}", "x0": 40, "x1": 260, "top": index * 12, "bottom": index * 12 + 10}
            for index in range(5)
        ] + [
            {"text": f"right {index}", "x0": 330, "x1": 550, "top": index * 12, "bottom": index * 12 + 10}
            for index in range(5)
        ]

        ordered = _order_lines(lines, 600)

        self.assertEqual(
            [f"left {index}" for index in range(5)],
            [line["text"] for line in ordered[:5]],
        )

    def test_repeated_headers_are_removed_without_touching_body(self) -> None:
        pages = [
            {
                "height": 800,
                "lines": [
                    {"text": f"Journal 202{page}", "top": 10, "bottom": 20},
                    {"text": f"body {page}", "top": 100, "bottom": 110},
                ],
            }
            for page in range(3)
        ]

        cleaned = _remove_repeated_margins(pages)

        self.assertEqual(
            [[f"body {page}"] for page in range(3)],
            [[line["text"] for line in item["lines"]] for item in cleaned],
        )

    def test_long_parent_is_split_into_overlapping_retrieval_children(self) -> None:
        text = " ".join(
            f"Sentence {index} reports stem respiration measurements."
            for index in range(30)
        )

        chunks = _child_chunks(text)

        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(len(chunk) <= 680 for chunk in chunks))
        self.assertIn("stem respiration", " ".join(chunks))

    def test_child_ranking_returns_parent_context_and_sibling_ids(self) -> None:
        parent_text = (
            "The study site was in Jiangxi. "
            "Coordinates were 26.44 N and 115.04 E."
        )
        first = block(1, "The study site was in Jiangxi.")
        second = block(2, "Coordinates were 26.44 N and 115.04 E.")
        first.parent_id = second.parent_id = "parent-site"
        first.parent_text = second.parent_text = parent_text
        first.chunk_count = second.chunk_count = 2
        second.chunk_index = 1
        spec = RequirementInterpreter().interpret(
            "提取树干呼吸速率，必须包括物种和样本量，关注研究站点与经纬度信息。"
        )

        ranking = EvidenceRetriever().rank(
            [first, second], "longitude", spec
        )

        self.assertEqual(second.block_id, ranking.hits[0].block.block_id)
        self.assertEqual(parent_text, ranking.hits[0].parent_context)
        self.assertEqual(
            [first.block_id, second.block_id],
            ranking.hits[0].context_block_ids,
        )

    def test_reparse_refuses_to_invalidate_existing_gold(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = Repository(Path(directory) / "test.sqlite3")
            original = block(1, "original evidence")
            repository.save_document(document(), [original], "2026-08-15T00:00:00Z")
            repository.save_gold(
                GoldEvidenceRecord(
                    gold_id="gold-1",
                    document_id=original.document_id,
                    field_name="site_name",
                    block_id=original.block_id,
                    status="verified",
                    note="",
                    created_at="2026-08-15T00:00:01Z",
                )
            )

            with self.assertRaisesRegex(ValueError, "invalidate verified evidence"):
                repository.save_document(
                    document(),
                    [block(2, "replacement evidence")],
                    "2026-08-15T00:00:02Z",
                )

            self.assertIsNotNone(repository.block(original.block_id))
            self.assertEqual(1, len(repository.list_gold()))


if __name__ == "__main__":
    unittest.main()
