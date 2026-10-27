"""Derived, opt-in geometry used by safe scene-layout edits.

The shared Scene contract intentionally contains no mesh-interior fields.  This
module keeps verified container/top-surface facts outside that contract and
refuses to infer them from an outer AABB.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ContainerInteriorGeometry:
    interior_aabb_min_m: tuple[float, float, float]
    interior_aabb_max_m: tuple[float, float, float]
    floor_z_m: float
    open_top: bool = True
    verified: bool = False
    supports_on_top: bool = False
    source: str = ""

    def __post_init__(self):
        values = (*self.interior_aabb_min_m, *self.interior_aabb_max_m, self.floor_z_m)
        if len(self.interior_aabb_min_m) != 3 or len(self.interior_aabb_max_m) != 3:
            raise ValueError("scene_layout_interior_bounds_invalid")
        if not all(math.isfinite(float(value)) for value in values):
            raise ValueError("scene_layout_interior_bounds_invalid")
        if any(low >= high for low, high in zip(self.interior_aabb_min_m, self.interior_aabb_max_m)):
            raise ValueError("scene_layout_interior_bounds_invalid")
        if not self.interior_aabb_min_m[2] <= self.floor_z_m <= self.interior_aabb_max_m[2]:
            raise ValueError("scene_layout_interior_floor_invalid")


class SceneLayoutGeometryRegistry:
    """Read-only registry keyed by ``model:<id>``/``robot:<id>`` metadata keys."""

    def __init__(self, entries=None):
        self._entries = {}
        for key, value in (entries or {}).items():
            if not isinstance(key, str) or not key.strip():
                raise ValueError("scene_layout_registry_key_invalid")
            if isinstance(value, ContainerInteriorGeometry):
                item = value
            else:
                item = ContainerInteriorGeometry(
                    interior_aabb_min_m=tuple(value["interior_aabb_min_m"]),
                    interior_aabb_max_m=tuple(value["interior_aabb_max_m"]),
                    floor_z_m=value["floor_z_m"],
                    open_top=value.get("open_top", True),
                    verified=value.get("verified", False),
                    supports_on_top=value.get("supports_on_top", False),
                    source=value.get("source", ""),
                )
            self._entries[key.strip()] = item

    @classmethod
    def from_path(cls, path):
        if path is None:
            return cls()
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("scene_layout_registry_invalid")
        return cls(payload)

    def get(self, metadata_ref, asset_type=None):
        if metadata_ref is None:
            return None
        key = metadata_ref
        if ":" not in key and asset_type:
            key = f"{asset_type}:{key}"
        value = self._entries.get(key)
        if value is not None:
            return value
        # Scene MetadataRef paths are usually "$LIBRARY_SERVER/<id>" while
        # the derived registry is deliberately namespace-qualified.
        if asset_type and isinstance(metadata_ref, str):
            tail = metadata_ref.rstrip("/").rsplit("/", 1)[-1]
            if tail.isdigit():
                return self._entries.get(f"{asset_type}:{tail}")
        if isinstance(metadata_ref, str):
            tail = metadata_ref.rstrip("/").rsplit("/", 1)[-1]
            if tail.isdigit():
                matches = [self._entries.get(f"{kind}:{tail}") for kind in ("model", "robot")]
                matches = [item for item in matches if item is not None]
                if len(matches) == 1:
                    return matches[0]
        return None

    def configuration_payload(self):
        return {
            key: {
                "interior_aabb_min_m": list(value.interior_aabb_min_m),
                "interior_aabb_max_m": list(value.interior_aabb_max_m),
                "floor_z_m": value.floor_z_m,
                "open_top": value.open_top,
                "verified": value.verified,
                "supports_on_top": value.supports_on_top,
                "source": value.source,
            }
            for key, value in sorted(self._entries.items())
        }
