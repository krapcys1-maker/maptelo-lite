from __future__ import annotations

from copy import deepcopy
from typing import Any

_MINIMAL: dict[str, Any] = {
    "schema_version": "0.1",
    "id": "demo",
    "version": 1,
    "title": "Demo",
    "application": {"name": "App"},
    "inputs": {"cpn": {"type": "string"}},
    "steps": [
        {"id": "open", "intent": "Open the app", "action": "navigate", "value": "/start"},
        {
            "id": "type_cpn",
            "intent": "Type the CPN",
            "action": "fill",
            "target": {"label": "CPN"},
            "value": "$inputs.cpn",
        },
    ],
}


def minimal_model(**overrides: Any) -> dict[str, Any]:
    """A small valid model as plain data; top-level keys can be replaced."""
    data = deepcopy(_MINIMAL)
    data.update(deepcopy(overrides))
    return data


def with_steps(*extra_steps: dict[str, Any], **overrides: Any) -> dict[str, Any]:
    data = minimal_model(**overrides)
    data["steps"] = data["steps"] + list(extra_steps)
    return data
