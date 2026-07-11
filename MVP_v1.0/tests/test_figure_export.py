import csv
import tempfile
import unittest
from pathlib import Path

from ecodata_mvp.server import _bundle_figure_outputs, _save_figure_output


class FigureExportTests(unittest.TestCase):
    def test_wpd_output_is_saved_with_provenance_and_bundled(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fields = ["task_id", "study_id", "page", "figure_label", "caption", "image_path", "source_pdf", "status"]
            with (root / "figure_tasks.csv").open("w", encoding="utf-8-sig", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=fields)
                writer.writeheader()
                writer.writerow({"task_id": "fig-2-a", "study_id": "study-1", "page": 5, "figure_label": "Figure 2a", "source_pdf": "paper.pdf", "status": "pending"})
            review = _save_figure_output(root, {"task_id": "fig-2-a", "x_label": "temperature", "x_unit": "°C", "y_label": "respiration", "y_unit": "µmol m-2 s-1", "datasets": [{"name": "stems", "fields": ["x", "y"], "rows": [[10, 0.2], [20, 0.4]]}]})
            self.assertEqual(review["point_count"], 2)
            csv_path = root / review["saved_files"][0]
            self.assertTrue(csv_path.exists())
            self.assertIn("study-1", csv_path.read_text(encoding="utf-8-sig"))
            self.assertTrue(_bundle_figure_outputs(root).exists())


if __name__ == "__main__":
    unittest.main()
