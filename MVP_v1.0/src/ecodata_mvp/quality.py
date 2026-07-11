"""Transparent validation rules and summary metrics."""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any

from .models import Candidate, Study


def validate_candidates(candidates: list[Candidate], variables: list[dict[str, Any]]) -> list[dict[str, Any]]:
    definitions = {item["name"]: item for item in variables}
    issues: list[dict[str, Any]] = []
    signatures: Counter[tuple[Any, ...]] = Counter()
    for candidate in candidates:
        signatures[(candidate.study_id, candidate.variable_name, candidate.value_normalized, candidate.page)] += 1
        definition = definitions[candidate.variable_name]
        base = {"study_id": candidate.study_id, "record_id": candidate.candidate_id, "page": candidate.page, "status": "open"}
        if not candidate.evidence_text or not candidate.source_locator:
            issues.append({**base, "severity": "error", "issue_type": "missing_provenance", "message": "Candidate lacks evidence text or source locator"})
        if definition.get("kind") == "numeric":
            if not candidate.unit_raw:
                issues.append({**base, "severity": "warning", "issue_type": "missing_unit", "message": f"{candidate.variable_name} has no captured unit"})
            valid_range = definition.get("valid_range")
            if valid_range and candidate.value_normalized is not None and not (valid_range[0] <= candidate.value_normalized <= valid_range[1]):
                issues.append({**base, "severity": "error", "issue_type": "out_of_range", "message": f"normalized value {candidate.value_normalized} outside {valid_range}"})
        if candidate.confidence < 0.6:
            issues.append({**base, "severity": "info", "issue_type": "low_confidence", "message": f"extraction confidence={candidate.confidence:.2f}"})
    for signature, count in signatures.items():
        if count > 1:
            study_id, variable, value, page = signature
            issues.append({"study_id": study_id, "record_id": "", "page": page, "status": "open", "severity": "info", "issue_type": "possible_duplicate", "message": f"{count} candidates share {variable}={value} on this page"})
    return issues


def quality_summary(studies: list[Study], candidates: list[Candidate], issues: list[dict[str, Any]], variables: list[dict[str, Any]]) -> dict[str, Any]:
    by_variable = Counter(candidate.variable_name for candidate in candidates)
    by_review = Counter(candidate.review_status for candidate in candidates)
    by_source = Counter(candidate.source_type for candidate in candidates)
    coverage: dict[str, int] = defaultdict(int)
    for study_id in {study.study_id for study in studies}:
        names = {candidate.variable_name for candidate in candidates if candidate.study_id == study_id}
        for name in names:
            coverage[name] += 1
    return {
        "study_count": len(studies),
        "included_count": sum(study.screening_status == "include" for study in studies),
        "candidate_count": len(candidates),
        "traceable_candidate_rate": round(sum(bool(c.evidence_text and c.page and c.source_locator) for c in candidates) / len(candidates), 4) if candidates else 0,
        "review_status": dict(by_review),
        "source_type": dict(by_source),
        "issue_count": len(issues),
        "open_error_count": sum(issue.get("severity") == "error" and issue.get("status") == "open" for issue in issues),
        "variables": [
            {
                "name": variable["name"],
                "candidate_count": by_variable[variable["name"]],
                "study_coverage_count": coverage[variable["name"]],
                "study_coverage_rate": round(coverage[variable["name"]] / len(studies), 4) if studies else 0,
            }
            for variable in variables
        ],
    }
