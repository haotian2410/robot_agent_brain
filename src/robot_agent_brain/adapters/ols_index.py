"""Read the index files an OLS package publishes for models, robots and scenes.

Every current index is one object: ``by_id`` maps a stringified asset id to its
name and ``no_display`` marks the ids ``/list`` hides.  Scenes published a bare
array until OLS 1.0.8-7fa9c40, and both generations are still live on this
machine -- the 1.0.5-era ``model/final_models`` bundle beside the current
runtime package -- so the shape is normalized here once instead of at each of
the four call sites that need a scene's id, name or file.
"""
from __future__ import annotations

from typing import Any


def _entries(document: Any) -> list[tuple[int, str, Any]]:
    if isinstance(document, list):
        for item in document:
            if (not isinstance(item, dict) or type(item.get("id")) is not int
                    or not isinstance(item.get("name"), str) or not item["name"]):
                raise ValueError("ols_index_entry_invalid")
        return [(item["id"], item["name"], item.get("no_display", False)) for item in document]
    if isinstance(document, dict) and isinstance(document.get("by_id"), dict):
        hidden = document.get("no_display") or {}
        entries = []
        for key, name in document["by_id"].items():
            if not isinstance(name, str) or not name:
                raise ValueError("ols_index_entry_invalid")
            entries.append((int(key), name, hidden.get(key, False)))
        return entries
    raise ValueError("ols_index_shape_unsupported: 索引既不是旧版数组，也没有非空 by_id")


def index_by_id(document: Any) -> dict[int, str]:
    """Every asset the index names, as ``{asset_id: name}``."""
    return {identifier: name for identifier, name, _ in _entries(document)}


def hidden_ids(document: Any) -> set[int]:
    """The ids ``/list`` withholds -- present in the index, absent from the browser."""
    return {identifier for identifier, _, hidden in _entries(document) if hidden}
