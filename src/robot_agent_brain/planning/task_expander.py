from itertools import product
from ..contracts.grounded_task import GroundedTask
from ..contracts.task_intent import Operation

class TaskExpander:
    """Keep set membership stable across phases; zip equally sized roles."""
    def expand(self, task: GroundedTask, scene=None) -> GroundedTask:
        objects = {o.scene_object_id: o for o in scene.objects} if scene else {}
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
                    data.update(asset_id=objects[object_id].asset_id, category=objects[object_id].category)
                entities.append(entity.model_copy(update=data))
        operations, expanded_ids = [], {}
        for operation_index, operation in enumerate(task.operations):
            actor = operation.source or operation.target
            if actor not in members:
                raise ValueError("task_semantic_invalid: operation has no bound actor")
            size = len(members[actor])
            pair_index = sum(1 for prior in task.operations[:operation_index] if prior.source == operation.source and prior.assignment_mode == "pairwise")
            if operation.assignment_mode == "pairwise":
                size = 1
            def select(role, index):
                if role is None:
                    return None
                values = members[role]
                if len(values) not in {1, size}:
                    raise ValueError("task_expansion_pairwise_cardinality_mismatch")
                return values[0] if len(values) == 1 else values[index]
            ids = []
            for index in range(size):
                data = operation.model_dump()
                data["operation_id"] = operation.operation_id if size == 1 else f"{operation.operation_id}__{index+1:02d}"
                for role in ("source", "target", "destination", "reference"):
                    role_value = getattr(operation, role)
                    if operation.assignment_mode == "pairwise" and role_value == actor:
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
