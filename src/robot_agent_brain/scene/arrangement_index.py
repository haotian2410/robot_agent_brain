"""Small durable index for arrangement metadata on a Scene session."""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class ArrangementRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")
    arrangement_id: str
    scene_id: int
    scene_version: int
    slot_bindings: dict[str, int] = Field(default_factory=dict)
    slot_assets: dict[str, str] = Field(default_factory=dict)
    world_positions: dict[str, tuple[float, float]] = Field(default_factory=dict)
    planner_revision: str | None = None
    effective_seed: int | None = None


class ArrangementIndex:
    def __init__(self):
        self._records: dict[str, ArrangementRecord] = {}

    def put(self, record: ArrangementRecord) -> None:
        self._records[record.arrangement_id] = record

    def get(self, arrangement_id: str) -> ArrangementRecord | None:
        return self._records.get(arrangement_id)

    def snapshot(self) -> list[dict]:
        return [item.model_dump(mode="json") for item in self._records.values()]

    def understanding_context(self, scene) -> list[dict]:
        """Read-only membership, scoped to the current scene, without poses.

        Keep missing members visible as invalid rather than pretending a deleted
        object still exists. Exact membership is revalidated before execution.
        """
        if scene is None:
            return []
        current = {obj.object_id_in_scene for obj in scene.objects}
        return [{"arrangement_id": record.arrangement_id,
                 "scene_version_created_or_updated": record.scene_version,
                 "slots": [{"slot_id": slot, "object_id": identifier,
                            "asset_alias": record.slot_assets.get(slot),
                            "exists": identifier in current}
                           for slot, identifier in record.slot_bindings.items()],
                 "members_complete": bool(record.slot_bindings) and set(record.slot_bindings.values()) <= current}
                for record in sorted(self._records.values(), key=lambda value: value.arrangement_id)
                if record.scene_id == scene.scene_id]

    def validate_operation(self, spec, scene):
        """Resolve membership in this scene branch, never by display name."""
        record = self.get(spec.arrangement_id)
        if spec.operation == "create":
            if record is not None and record.scene_id == scene.scene_id:
                raise ValueError("scene_layout_arrangement_exists")
            return None
        if record is None or record.scene_id != scene.scene_id:
            raise ValueError("scene_layout_arrangement_missing")
        identifiers = {obj.object_id_in_scene for obj in scene.objects}
        if not record.slot_bindings or not set(record.slot_bindings.values()) <= identifiers:
            raise ValueError("scene_layout_arrangement_members_missing")
        return record.model_copy(deep=True)
