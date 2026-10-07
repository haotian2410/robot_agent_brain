"""Explicit semantic projection: never serialize GroundedTask to the planner."""
from pydantic import BaseModel, ConfigDict, Field
from ..contracts.task_intent import PlacementTarget


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PlannerEntity(StrictModel):
    id: str
    name: str
    category: str


class PlannerRoleBindings(StrictModel):
    source: str | None = None
    destination: str | None = None
    target: str | None = None
    reference: str | None = None


def operation_valid_roles(operation):
    return tuple(role for role in PlannerRoleBindings.model_fields if getattr(operation, role) is not None)


class PlannerOperation(StrictModel):
    id: str
    type: str
    semantic_intent: str
    role_bindings: PlannerRoleBindings
    valid_roles: tuple[str, ...]
    depends_on: list[str] = Field(default_factory=list)
    placement_target: PlacementTarget | None = None
    motion_direction: str | None = None


class PlannerGoal(StrictModel):
    relation: str
    subject: str
    reference: str | None = None


class PlannerInitialState(StrictModel):
    held_entity: str | None = None
    gripper_occupied: bool = False


class PlannerContext(StrictModel):
    instruction: str
    semantic_summary: str
    operations: list[PlannerOperation]
    entities: list[PlannerEntity]
    goals: list[PlannerGoal]
    initial_state: PlannerInitialState


def build_planner_context(task, held_object=None):
    operations = []
    relevant = set()
    for op in task.operations:
        roles = operation_valid_roles(op)
        bindings = {role: getattr(op, role) for role in roles}
        relevant.update(bindings.values())
        semantic = op.task_type.value + " " + " ".join(f"{k}={v}" for k, v in bindings.items())
        operations.append(PlannerOperation(id=op.operation_id, type=op.task_type.value,
            semantic_intent=semantic, role_bindings=PlannerRoleBindings(**bindings), valid_roles=roles,
            depends_on=list(op.depends_on), placement_target=op.placement_target,
            motion_direction=op.motion_direction.value if op.motion_direction else None))
    goals = [PlannerGoal(relation=r.relation.value, subject=r.subject, reference=r.reference)
             for r in task.spatial_relations if r.scope == "goal"]
    for goal in goals:
        relevant.add(goal.subject)
        if goal.reference:
            relevant.add(goal.reference)
    held_entity = next((e.entity_id for e in task.entities if e.scene_object_id == held_object), None)
    if held_entity:
        relevant.add(held_entity)
    summary = [f"{op.id}: {op.semantic_intent}" for op in operations]
    summary.extend(f"goal: {g.subject} {g.relation} {g.reference or ''}".strip() for g in goals)
    return PlannerContext(instruction=task.instruction, semantic_summary="\n".join(summary), operations=operations,
        entities=[PlannerEntity(id=e.entity_id, name=e.semantic_name, category=e.category) for e in task.entities if e.entity_id in relevant],
        goals=goals, initial_state=PlannerInitialState(held_entity=held_entity, gripper_occupied=held_object is not None))
