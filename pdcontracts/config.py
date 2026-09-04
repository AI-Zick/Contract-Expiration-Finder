"""Configuration loading.

Two files, both optional:

    config/settings.yml   scoring focus, database path, API tokens
    config/sources.yml    which portals to collect from
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List

DEFAULT_SETTINGS: Dict[str, Any] = {
    "database": "pdcontracts.sqlite",
    # The product segments this sales team competes in. Everything else is
    # still collected -- it tells you who the incumbent is across the agency --
    # but targeting and reports focus here by default.
    "focus_categories": ["rms", "cad", "dispatch_mobile"],
    # RMS, CAD and MDT are almost always bought from one vendor as a suite, so
    # group them into a single opportunity per agency+vendor rather than
    # showing three separate rows to a rep.
    "group_suite_opportunities": True,
    "socrata_app_token": "",
    "min_classification_confidence": 0.3,
}


def _load_yaml(path: Path) -> Any:
    if not path.exists():
        return None
    try:
        import yaml
    except ImportError as exc:  # pragma: no cover - dependency guard
        raise RuntimeError("PyYAML is required to read config files") from exc
    with path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def load_settings(path: str = "config/settings.yml") -> Dict[str, Any]:
    settings = dict(DEFAULT_SETTINGS)
    data = _load_yaml(Path(path))
    if isinstance(data, dict):
        settings.update(data)
    # Environment wins, so tokens stay out of version control.
    token = os.environ.get("SOCRATA_APP_TOKEN")
    if token:
        settings["socrata_app_token"] = token
    db = os.environ.get("PDCONTRACTS_DB")
    if db:
        settings["database"] = db
    return settings


def load_sources(path: str = "config/sources.yml") -> List[Dict[str, Any]]:
    data = _load_yaml(Path(path))
    if not data:
        return []
    if isinstance(data, dict):
        data = data.get("sources", [])
    return [s for s in data if isinstance(s, dict) and s.get("enabled", True)]
