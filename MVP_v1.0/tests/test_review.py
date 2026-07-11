import csv
import tempfile
import unittest
from pathlib import Path

from ecodata_mvp.exports import DATA_FIELDS
from ecodata_mvp.review import apply_review


class ReviewTests(unittest.TestCase):
    def test_review_updates_data_and_writes_audit(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            row = {field: "" for field in DATA_FIELDS}
            row.update({"candidate_id": "cand-1", "value_numeric": "1.0", "value_normalized": "1.0", "review_status": "pending", "notes": "baseline"})
            with (root / "data.csv").open("w", encoding="utf-8-sig", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=DATA_FIELDS)
                writer.writeheader()
                writer.writerow(row)
            (root / "reviews.csv").write_text("", encoding="utf-8")
            result = apply_review(root, {"candidate_id": "cand-1", "action": "modified", "new_value": "1.2", "reason": "checked source", "reviewer": "tester"})
            self.assertEqual(result["action"], "modified")
            with (root / "data.csv").open(encoding="utf-8-sig") as handle:
                updated = next(csv.DictReader(handle))
            self.assertEqual(updated["value_normalized"], "1.2")
            self.assertEqual(updated["review_status"], "modified")
            self.assertIn("checked source", (root / "reviews.csv").read_text(encoding="utf-8-sig"))


if __name__ == "__main__":
    unittest.main()
