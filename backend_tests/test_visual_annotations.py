from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from backend.database import Repository
from backend.schemas import (
    VisualAssetRecord,
    VisualEvidenceAnnotationInput,
)
from backend.services import EcoEvidenceService
from backend_tests.helpers import block, document


def visual_asset(
    asset_id: str = "doc-test-figure-1",
    *,
    document_id: str = "doc-test",
    kind: str = "figure",
) -> VisualAssetRecord:
    return VisualAssetRecord(
        asset_id=asset_id,
        document_id=document_id,
        page=2,
        kind=kind,
        caption="Figure 1 Stem respiration by month",
        bbox=[50.0, 120.0, 500.0, 420.0],
        detection_method="caption+pdf-image-object",
        confidence=0.88,
        summary="Figure 1 Stem respiration by month",
        has_structured_content=False,
        digitization_status="candidate",
        parser_backend="pdfplumber",
        parser_version="test-parser-v1",
    )


class VisualEvidenceAnnotationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.repository = Repository(
            Path(self.temporary_directory.name) / "visual.sqlite3"
        )
        self.block = block(1, "Stem respiration was measured monthly.")
        self.asset = visual_asset()
        self.repository.save_document(
            document(),
            [self.block],
            "2026-08-16T00:00:00Z",
            assets=[self.asset],
        )
        self.service = EcoEvidenceService(self.repository)

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def test_visual_relevance_is_versioned_separately_from_text_gold(
        self,
    ) -> None:
        saved = self.service.add_visual_annotation(
            VisualEvidenceAnnotationInput(
                document_id=self.asset.document_id,
                field_name="stem_respiration_rate",
                asset_id=self.asset.asset_id,
                relevance="relevant",
                status="verified",
                note="contains the target series",
            )
        )

        self.assertTrue(saved.annotation_id.startswith("visual-gold-"))
        self.assertEqual([], self.repository.list_gold())
        self.assertEqual(
            [saved],
            self.repository.list_visual_annotations(
                document_id=self.asset.document_id,
                field_name="stem_respiration_rate",
                relevance="relevant",
            ),
        )

        updated = self.service.add_visual_annotation(
            VisualEvidenceAnnotationInput(
                document_id=self.asset.document_id,
                field_name="stem_respiration_rate",
                asset_id=self.asset.asset_id,
                relevance="not_relevant",
                status="verified",
                note="caption mention only",
            )
        )

        self.assertEqual(saved.annotation_id, updated.annotation_id)
        self.assertEqual("not_relevant", updated.relevance)
        self.assertEqual(1, len(self.repository.list_visual_annotations()))

    def test_visual_annotation_rejects_an_asset_from_another_document(
        self,
    ) -> None:
        with self.assertRaisesRegex(KeyError, "Unknown visual asset"):
            self.service.add_visual_annotation(
                VisualEvidenceAnnotationInput(
                    document_id=self.asset.document_id,
                    field_name="stem_respiration_rate",
                    asset_id="other-document-figure",
                    relevance="relevant",
                )
            )

    def test_reparse_refuses_to_invalidate_annotated_visual_asset(self) -> None:
        saved = self.service.add_visual_annotation(
            VisualEvidenceAnnotationInput(
                document_id=self.asset.document_id,
                field_name="stem_respiration_rate",
                asset_id=self.asset.asset_id,
                relevance="uncertain",
                status="draft",
            )
        )

        with self.assertRaisesRegex(
            ValueError, "invalidate visual evidence annotations"
        ):
            self.repository.save_document(
                document(),
                [self.block],
                "2026-08-16T00:00:01Z",
                assets=[],
            )

        self.assertIsNotNone(self.repository.visual_asset(self.asset.asset_id))
        self.assertEqual(
            [saved], self.repository.list_visual_annotations()
        )


if __name__ == "__main__":
    unittest.main()
