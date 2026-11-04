"""Immutable asset-catalog snapshots used by task-understanding turns.

The snapshot is deliberately separate from Scene v1.  It is a request-scoped
enumeration of library identities, not a list of scene instances and not a
permission to execute a robot task.
"""
from __future__ import annotations

import hashlib
import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class CatalogAsset(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    asset_key: str = Field(pattern=r"^(model|robot):[0-9]+$")
    name: str = Field(min_length=1)
    display_name: str | None = None
    aliases: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()
    category: str | None = None
    asset_type: Literal["model", "robot"] = "model"
    metadata_ref: str | None = None
    selectable_for_add: bool = False
    availability_reason: str | None = None
    scalable: bool | None = None
    scale_range: tuple[float, float] | None = None


class CatalogScene(BaseModel):
    """A scene template in the OLS directory, separate from addable models."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    scene_key: str = Field(pattern=r"^scene:[0-9]+$")
    name: str = Field(min_length=1)
    display_name: str | None = None
    availability_reason: str | None = None


class AssetCatalogSnapshot(BaseModel):
    """A deterministic, bounded catalog sent with every understanding turn."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    protocol_version: Literal["task_understanding.v3.1"] = "task_understanding.v3.1"
    revision: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    models: tuple[CatalogAsset, ...] = ()
    robots: tuple[CatalogAsset, ...] = ()
    scenes: tuple[CatalogScene, ...] = ()
    registered_profiles: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_namespaces(self):
        all_items = (*self.models, *self.robots)
        keys = [item.asset_key for item in all_items]
        if len(keys) != len(set(keys)):
            raise ValueError("asset_catalog_duplicate_key")
        if any(item.asset_type != "model" for item in self.models):
            raise ValueError("asset_catalog_model_namespace_invalid")
        if any(item.asset_type != "robot" for item in self.robots):
            raise ValueError("asset_catalog_robot_namespace_invalid")
        scene_keys = [item.scene_key for item in self.scenes]
        if len(scene_keys) != len(set(scene_keys)):
            raise ValueError("asset_catalog_duplicate_scene_key")
        return self

    def model_keys(self) -> set[str]:
        return {item.asset_key for item in self.models}

    def contains_model(self, key: str) -> bool:
        return key in self.model_keys()

    def canonical_payload(self) -> dict:
        return {
            "protocol_version": self.protocol_version,
            "revision": self.revision,
            "models": [item.model_dump(mode="json") for item in self.models],
            "robots": [item.model_dump(mode="json") for item in self.robots],
            "scenes": [item.model_dump(mode="json") for item in self.scenes],
            "registered_profiles": list(self.registered_profiles),
        }

    @classmethod
    def from_items(cls, models: list[CatalogAsset], robots: list[CatalogAsset], *,
                   scenes: list[CatalogScene] | tuple[CatalogScene, ...] = (),
                   registered_profiles: list[str] | tuple[str, ...] = ()) -> "AssetCatalogSnapshot":
        payload = {
            "models": [item.model_dump(mode="json") for item in sorted(models, key=lambda x: x.asset_key)],
            "robots": [item.model_dump(mode="json") for item in sorted(robots, key=lambda x: x.asset_key)],
            "scenes": [item.model_dump(mode="json") for item in sorted(scenes, key=lambda x: x.scene_key)],
            "registered_profiles": sorted(set(registered_profiles)),
        }
        digest = hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True,
                                          separators=(",", ":")).encode("utf-8")).hexdigest()
        return cls(revision=f"sha256:{digest}", models=tuple(sorted(models, key=lambda x: x.asset_key)),
                   robots=tuple(sorted(robots, key=lambda x: x.asset_key)),
                   scenes=tuple(sorted(scenes, key=lambda x: x.scene_key)),
                   registered_profiles=tuple(sorted(set(registered_profiles))))
