"""Canonical names for scene objects and OLS assets.

Scene files are browser data and are never rewritten.  This deterministic
layer is used only for matching and diagnostics.
"""
from __future__ import annotations

import re


DEFAULT_ALIASES = {
    "熊猫": "toy_panda", "玩偶熊猫": "toy_panda", "熊猫玩偶": "toy_panda",
    "熊猫玩具": "toy_panda", "玩具熊猫": "toy_panda",
    "toy panda": "toy_panda", "toy-panda": "toy_panda", "toypanda": "toy_panda",
    "杯子": "mug", "马克杯": "mug", "cup": "mug", "coffee cup": "mug",
}


def canonical_name(value, aliases=None):
    if value is None:
        return ""
    raw = str(value).strip()
    raw = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", raw)
    key = re.sub(r"[\s\-]+", "_", raw.casefold()).strip("_")
    # Runtime/catalog aliases override the conservative built-ins.  This is
    # important when a later OLS really introduces a distinct ``cup`` asset:
    # the live catalog can then map cup to itself instead of forcing mug.
    merged = {k.replace(" ", "_"): v for k, v in DEFAULT_ALIASES.items()}
    merged.update({str(k).strip().casefold().replace("-", "_"): str(v).strip().casefold()
                   for k, v in (aliases or {}).items()})
    return merged.get(key, key)


def asset_name_for_object(obj, index, assets=None, aliases=None):
    """Resolve an object's canonical OLS semantic name with safe fallbacks."""
    ident = obj.object_id_in_scene
    ref = index.metadata_ref(ident)
    kind = index.metadata_type(ident)
    if assets is not None and ref:
        try:
            view = assets.resolve(ref, kind)
            if view is not None and getattr(view, "semantic_name", None):
                return canonical_name(view.semantic_name, aliases)
        except (LookupError, ValueError, AttributeError):
            pass
    semantic = index.semantic(ident)
    if semantic is not None and semantic.semantic_name:
        return canonical_name(semantic.semantic_name, aliases)
    return canonical_name(obj.object_name_in_scene, aliases)
