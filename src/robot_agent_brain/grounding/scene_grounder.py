from __future__ import annotations

from ..contracts.grounded_task import GroundedEntity, GroundedTask
from ..contracts.scene import SceneConfig
from ..contracts.task_intent import TaskIntent


class SceneGrounder:
    """Bind semantic entities to public SceneConfig objects, without poses."""

    def ground(self, intent: TaskIntent, scene: SceneConfig) -> GroundedTask:
        available = list(scene.objects)
        bindings: list[GroundedEntity] = []
        used: set[str] = set()
        for entity in intent.entities:
            candidates = [item for item in available if item.scene_object_id not in used and (
                item.semantic_name.casefold() == entity.semantic_name.casefold()
                or item.category.casefold() == entity.category.casefold()
                or item.semantic_name.casefold() in {alias.casefold() for alias in entity.aliases}
            )]
            required = entity.count if entity.quantity_mode.value == "all" else 1
            if len(candidates) < required:
                raise ValueError(
                    f"scene_grounding_ambiguous: entity={entity.entity_id} candidates="
                    f"{[item.scene_object_id for item in candidates]}"
                )
            members = candidates[:required]
            item = members[0]
            used.update(member.scene_object_id for member in members)
            bindings.append(GroundedEntity(
                entity_id=entity.entity_id,
                semantic_name=entity.semantic_name,
                scene_object_id=item.scene_object_id,
                scene_object_ids=[member.scene_object_id for member in members],
                asset_id=item.asset_id,
                category=item.category,
            ))
        return GroundedTask(
            instruction=intent.instruction,
            entities=bindings,
            operations=intent.operations,
            scene_id=scene.scene_id,
            scene_version=scene.scene_version,
        )
