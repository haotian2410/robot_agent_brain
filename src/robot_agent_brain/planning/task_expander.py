from itertools import product
from ..contracts.grounded_task import GroundedTask
from ..contracts.task_intent import Operation
from ..scene.component_access import SceneIndex
from ..scene.scene_graph import world_transform

class TaskExpander:
    """Keep set membership stable across phases; zip equally sized roles."""
    def expand(self, task: GroundedTask, scene=None) -> GroundedTask:
        objects = {o.object_id_in_scene: o for o in scene.objects} if scene else {}
        scene_index = SceneIndex(scene) if scene else None
        entities, members = [], {}
        for entity in task.entities:
            ids = entity.scene_object_ids
            members[entity.entity_id] = []
            for index, object_id in enumerate(ids, 1):
                concrete_id = entity.entity_id if len(ids) == 1 else f"{entity.entity_id}__{index:02d}"
                if any(e.entity_id == concrete_id for e in entities):
                    raise ValueError("task_expansion_entity_id_collision")
                members[entity.entity_id].append(concrete_id)
                data = dict(entity_id=concrete_id, scene_object_id=object_id, scene_object_ids=[object_id])
                if object_id in objects:
                    semantic = scene_index.semantic(object_id)
                    data.update(metadata_ref=scene_index.metadata_ref(object_id),
                                semantic_name=semantic.semantic_name,
                                category=semantic.category,
                                model_scale=world_transform(scene, object_id).scale)
                entities.append(entity.model_copy(update=data))
        operations, expanded_ids = [], {}
        pairwise_cursors = {}
        distributed_counts = {}
        for operation in task.operations:
            actor = operation.source or operation.target
            roles = {getattr(operation, name) for name in ("source", "target", "destination", "reference")} - {None}
            if operation.assignment_mode == "pairwise" and actor in members and len(members[actor]) > 1 and all(len(members[r]) == 1 for r in roles - {actor}):
                key = (actor, operation.task_type)
                distributed_counts[key] = distributed_counts.get(key, 0) + 1
        for (actor, _), count in distributed_counts.items():
            if count != len(members[actor]):
                raise ValueError("task_expansion_pairwise_coverage_mismatch")
        for operation_index, operation in enumerate(task.operations):
            actor = operation.source or operation.target
            if actor not in members:
                raise ValueError("task_semantic_invalid: operation has no bound actor")
            roles = [getattr(operation, name) for name in ("source", "target", "destination", "reference")]
            cardinalities = [len(members[value]) for value in roles if value is not None]
            size = max(cardinalities or [1])
            if any(value not in {1, size} for value in cardinalities):
                raise ValueError("task_expansion_assignment_cardinality_mismatch")
            role_ids = set(roles) - {None}
            distributed_pairwise = (operation.assignment_mode == "pairwise" and len(members[actor]) > 1
                                    and all(len(members[r]) == 1 for r in role_ids - {actor}))
            if distributed_pairwise:
                key = (actor, operation.task_type)
                pair_index = pairwise_cursors.get(key, 0)
                if pair_index >= size:
                    raise ValueError("task_expansion_pairwise_overassigned")
                size = 1
                pairwise_cursors[key] = pair_index + 1
            else:
                pair_index = 0
            def select(role, index):
                if role is None:
                    return None
                values = members[role]
                expected = max(cardinalities or [1]) if distributed_pairwise else size
                if len(values) not in {1, expected}:
                    raise ValueError("task_expansion_pairwise_cardinality_mismatch")
                return values[0] if len(values) == 1 else values[pair_index if distributed_pairwise else index]
            ids = []
            for index in range(size):
                data = operation.model_dump()
                data["operation_id"] = operation.operation_id if size == 1 else f"{operation.operation_id}__{index+1:02d}"
                for role in ("source", "target", "destination", "reference"):
                    role_value = getattr(operation, role)
                    if distributed_pairwise and role_value == actor:
                        data[role] = members[actor][pair_index]
                    else:
                        data[role] = select(role_value, index)
                if operation.placement_target:
                    data["placement_target"]["reference"] = select(operation.placement_target.reference, index)
                dependencies = [i for dep in operation.depends_on for i in expanded_ids[dep]]
                if operations:
                    dependencies.append(operations[-1].operation_id)
                data["depends_on"] = list(dict.fromkeys(dependencies))
                operations.append(Operation.model_validate(data))
                ids.append(data["operation_id"])
            expanded_ids[operation.operation_id] = ids
        relations = []
        for rel in task.spatial_relations:
            sources = members[rel.subject]
            references = members[rel.reference] if rel.reference else [None]
            pairs = zip(sources, references) if len(sources) == len(references) else product(sources, references)
            for subject, reference in pairs:
                relations.append(rel.model_copy(update={"subject": subject, "reference": reference}))
        return task.model_copy(update={"entities": entities, "operations": operations, "spatial_relations": relations})
