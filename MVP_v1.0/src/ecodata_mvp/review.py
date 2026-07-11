"""Persist human decisions while keeping an append-only audit log."""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

from .utils import stable_id, utc_now


ALLOWED_ACTIONS = {"accepted", "modified", "rejected", "uncertain"}


def apply_review(run_dir: Path, payload: dict[str, Any]) -> dict[str, Any]:
    candidate_id = str(payload.get("candidate_id", ""))
    action = str(payload.get("action", ""))
    reason = str(payload.get("reason", "")).strip()
    reviewer = str(payload.get("reviewer", "local-reviewer")).strip() or "local-reviewer"
    if action not in ALLOWED_ACTIONS:
        raise ValueError(f"Invalid review action: {action}")
    if action in {"modified", "rejected", "uncertain"} and not reason:
        raise ValueError("A reason is required for modified/rejected/uncertain decisions")

    data_path = run_dir / "data.csv"
    with data_path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        rows = list(reader)
        fields = reader.fieldnames or []
    target = next((row for row in rows if row.get("candidate_id") == candidate_id), None)
    if target is None:
        raise KeyError(f"Unknown candidate_id: {candidate_id}")
    old_value = target.get("value_normalized") or target.get("value_text") or target.get("value_raw", "")
    new_value = str(payload.get("new_value", "")).strip()
    if action == "modified":
        if not new_value:
            raise ValueError("A new value is required for modified decisions")
        target["value_normalized"] = new_value if target.get("value_numeric") else ""
        target["value_text"] = new_value if not target.get("value_numeric") else target.get("value_text", "")
    target["review_status"] = action
    target["notes"] = (target.get("notes", "") + f"; human_review={reason}").strip("; ")
    with data_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)

    review = {
        "review_id": stable_id("review", candidate_id, utc_now(), reviewer),
        "candidate_id": candidate_id,
        "action": action,
        "old_value": old_value,
        "new_value": new_value,
        "reason": reason,
        "reviewer": reviewer,
        "reviewed_at": utc_now(),
    }
    reviews_path = run_dir / "reviews.csv"
    fields = list(review)
    write_header = not reviews_path.exists() or reviews_path.stat().st_size == 0
    with reviews_path.open("a", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        if write_header:
            writer.writeheader()
        writer.writerow(review)
    return review

