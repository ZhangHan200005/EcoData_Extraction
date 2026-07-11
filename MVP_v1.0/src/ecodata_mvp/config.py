"""Load and fingerprint editable project configuration."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import yaml


def load_yaml(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def load_configuration(project_path: Path, variables_path: Path) -> dict[str, Any]:
    project = load_yaml(project_path)
    variables = load_yaml(variables_path)
    payload = {"project": project, "variables": variables}
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    payload["config_sha256"] = hashlib.sha256(canonical).hexdigest()
    return payload


def variable_map(configuration: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        item["name"]: item
        for item in configuration["variables"].get("variables", [])
    }

