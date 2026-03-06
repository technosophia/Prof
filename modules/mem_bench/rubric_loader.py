"""Rubric discovery and loading for mem_bench."""

from __future__ import annotations

import os
from typing import Dict, Optional

import yaml

from shared.common import _get_service


def find_rubrics(material_base_dir: Optional[str] = None) -> Dict[str, str]:
    if material_base_dir is None:
        config = _get_service("config")
        material_base_dir = (config.get("scenarios_dir") if config else None) or "material/mem_bench"

    found: Dict[str, str] = {}
    if not os.path.isdir(material_base_dir):
        return found

    for root, _, files in os.walk(material_base_dir):
        if "rubrics.yaml" in files:
            path = os.path.abspath(os.path.join(root, "rubrics.yaml"))
            display_name = os.path.basename(root)
            found[display_name] = path
    return dict(sorted(found.items()))


def load_rubric(path: str) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = yaml.safe_load(handle) or {}
            return data if isinstance(data, dict) else {}
    except Exception:
        return {}
