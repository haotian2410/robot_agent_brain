from __future__ import annotations

from ..semantics.motion_evidence import _extract_motion_spans, resolve_motion_evidence
from typing import Any, Protocol, Literal
from ..contracts.robot_setup import RobotSetupRequest
from ..contracts.task_intent import TaskHoldConstraint
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator
from ..contracts.turn import BrainTurn, SceneEditIntent, SceneEditPlan, SceneQueryIntent, SessionControlIntent, TurnKind, TurnStatus

from ..contracts.spatial import RelationScope, SpatialRelation, SpatialRelationType
from ..contracts.task_intent import Direction, MotionScale, Operation, PlacementTarget, QuantityMode, TaskEntity, TaskIntent, TaskType
from ..errors import BrainError


def task_understanding_wire_schema():
    """Require explicit new semantic choices from live models, not old Replay."""
    schema = TaskParseOutput.model_json_schema()
    # A live constrained decoder must explicitly choose each payload/null. If
    # optional, it can finish a scene_query without ever emitting scene_query.
    # Replay/Python defaults remain backward compatible; runtime validation stays strict.
    schema["required"] = list(schema["properties"])
    # Optional fields can be skipped permanently by ordered JSON-grammar decoders
    # once they emit coordinate_frame/reference. Require explicit values or null
    # for editing semantics; Python still validates per-operation combinations.
    edit = schema["$defs"]["SceneEditIntent"]
    edit["required"] = list(dict.fromkeys(edit.get("required", []) + [
        "relation", "reference", "direction", "distance_m", "motion_scale",
        "coordinate_frame", "axis", "angle_deg", "placement_hint", "placement_region",
    ]))
    return schema


class TaskUnderstandingRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    instruction: str = Field(min_length=1)


class TaskUnderstandingProvider(Protocol):
    def understand(self, request: TaskUnderstandingRequest) -> TaskIntent: ...


class ParseEntity(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    name: str
    category: str
    color: str | None = None
    tags: list[str] = Field(default_factory=list)
    count: int = Field(default=1, ge=1)
    quantity_mode: QuantityMode = QuantityMode.SINGLE
    aliases: list[str] = Field(default_factory=list)
    dialogue_ref: bool = False
    dialogue_ref_set: bool = False
    all_available: bool = False
    category_only: bool = False


class ParseOperation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: TaskType
    source: str | None = None
    destination: str | None = None
    target: str | None = None
    reference: str | None = None
    motion_direction: Direction | None = None
    distance_m: float | None = Field(default=None, gt=0, le=2)
    motion_scale: MotionScale | None = None
    placement_target: PlacementTarget | None = None
    depends_on: list[str] = Field(default_factory=list)
    arm: Literal["left", "right", "single"] | None = None
    parallel_group: str | None = Field(default=None, min_length=1)
    parallel_required: bool = False
    assignment_mode: str = Field(default="broadcast", pattern=r"^(broadcast|pairwise|repeat_all|relation_matched)$")


class ParseRelation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scope: RelationScope = RelationScope.SELECTION
    subject: str
    relation: SpatialRelationType
    reference: str | None = None


class TaskParseOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    arm_usage: Literal["unspecified", "both_required"] = "unspecified"
    hold_constraints: list[TaskHoldConstraint] = Field(default_factory=list)
    status: TurnStatus = TurnStatus.ACCEPTED
    turn_kind: TurnKind = TurnKind.ROBOT_TASK
    clarification_question: str | None = None
    scene_edit: SceneEditPlan | None = None
    scene_query: SceneQueryIntent | None = None
    session_control: SessionControlIntent | None = None
    robot_setup_request: RobotSetupRequest | None = None
    entities: list[ParseEntity] = Field(default_factory=list)
    operations: list[ParseOperation] = Field(default_factory=list)
    relations: list[ParseRelation] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_turn(self):
        if self.status == TurnStatus.ACCEPTED and self.clarification_question is not None:
            raise ValueError("task_semantic_invalid: accepted turn cannot contain clarification_question")
        if self.hold_constraints and (self.status != TurnStatus.ACCEPTED or self.turn_kind != TurnKind.ROBOT_TASK):
            raise ValueError("task_semantic_invalid: hold constraints require accepted robot task")
        if self.arm_usage != "unspecified" and (self.status != TurnStatus.ACCEPTED or self.turn_kind != TurnKind.ROBOT_TASK):
            raise ValueError("task_semantic_invalid: arm usage requires accepted robot task")
        payloads = {TurnKind.SCENE_EDIT: self.scene_edit, TurnKind.SCENE_QUERY: self.scene_query, TurnKind.SESSION_CONTROL: self.session_control}
        if self.status != TurnStatus.ACCEPTED:
            if self.robot_setup_request is not None or self.entities or self.operations or self.relations or any(v is not None for v in payloads.values()):
                raise ValueError("task_semantic_invalid: rejected turn has payload")
            return self
        if self.robot_setup_request is not None and self.turn_kind not in {TurnKind.ROBOT_CONFIG, TurnKind.ROBOT_TASK}:
            raise ValueError("task_semantic_invalid: robot setup requires robot turn")
        if self.turn_kind == TurnKind.ROBOT_TASK:
            if not self.entities or not self.operations or any(v is not None for v in payloads.values()):
                raise ValueError("task_semantic_invalid: robot task needs only entities and operations")
        elif self.turn_kind == TurnKind.ROBOT_CONFIG:
            if self.robot_setup_request is None or self.entities or self.operations or self.relations or any(v is not None for v in payloads.values()):
                raise ValueError("task_semantic_invalid: robot config payload mismatch")
        elif self.turn_kind in payloads:
            if self.entities or self.operations or self.relations or payloads[self.turn_kind] is None or sum(v is not None for v in payloads.values()) != 1:
                raise ValueError("task_semantic_invalid: turn payload mismatch")
        else:
            raise ValueError("task_semantic_invalid: unsupported turn cannot be accepted")
        ids = {e.id for e in self.entities}
        if any(r.subject not in ids or (r.reference and r.reference not in ids) for r in self.relations):
            raise ValueError("task_semantic_invalid: relation references unknown entities")
        return self

    def to_task_intent(self, instruction: str) -> TaskIntent:
        if self.status != TurnStatus.ACCEPTED or self.turn_kind != TurnKind.ROBOT_TASK:
            raise ValueError("task_semantic_invalid: no robot task payload")
        # Narrow evidence gates catch omitted explicit constraints. They do not
        # invent roles, repair model output, or infer physical feasibility.
        text = instruction.casefold()
        both = any(token in text for token in ("两只手各", "两臂分别", "用双臂分别", "both hands", "both arms must"))
        if both and self.arm_usage != "both_required" and {op.arm for op in self.operations} != {"left", "right"}:
            raise ValueError("task_semantic_invalid: arm_usage_required")
        stable = (any(token in text for token in ("左臂保持", "右臂保持", "先不要松手", "hold position"))
                  and any(token in text for token in ("左臂", "右臂", "left arm", "right arm")))
        if stable and not self.hold_constraints:
            raise ValueError("task_semantic_invalid: hold_constraint_required")
        moves = [o for o in self.operations if o.type == TaskType.MOVE]
        spans = resolve_motion_evidence(instruction, len(moves)) if moves else []
        operation_values = []
        span_index = 0
        for item in self.operations:
            values = item.model_dump(exclude={"type"})
            entity_counts = {entity.id: entity.count for entity in self.entities}
            pairwise_clause = ("分别" in instruction or "一一对应" in instruction)
            role_counts = [entity_counts.get(role, 1) for role in (item.source, item.target, item.destination, item.reference) if role]
            if values.get("assignment_mode") == "broadcast" and pairwise_clause and sum(count > 1 for count in role_counts) >= 2:
                values["assignment_mode"] = "pairwise"
            if item.type == TaskType.MOVE and spans:
                span = spans[span_index]
                span_index += 1
                values.update(motion_direction=span.direction, distance_m=span.distance_m, motion_scale=span.motion_scale)
            operation_values.append(Operation(operation_id=f"op-{len(operation_values)+1}", task_type=item.type, **values))
        entity_ids = {item.id for item in self.entities}
        relations = [SpatialRelation(
            scope=item.scope, subject=item.subject, relation=item.relation, reference=item.reference,
        ) for item in self.relations]
        if any(item.subject not in entity_ids or (item.reference and item.reference not in entity_ids) for item in relations):
            raise ValueError("task_semantic_invalid: relation references unknown entities")
        return TaskIntent(
            instruction=instruction,
            arm_usage=self.arm_usage,
            hold_constraints=self.hold_constraints,
            entities=[TaskEntity(
                entity_id=item.id,
                semantic_name=item.name,
                category=item.category,
                color=item.color,
                tags=item.tags,
                count=item.count,
                quantity_mode=item.quantity_mode,
                aliases=item.aliases, dialogue_ref=item.dialogue_ref, dialogue_ref_set=item.dialogue_ref_set, all_available=item.all_available,
                category_only=item.category_only,
            ) for item in self.entities],
            operations=operation_values,
            spatial_relations=relations,
        )

    def to_brain_turn(self, instruction: str) -> BrainTurn:
        task = self.to_task_intent(instruction) if self.status == TurnStatus.ACCEPTED and self.turn_kind == TurnKind.ROBOT_TASK else None
        status = self.status
        return BrainTurn(status=status, turn_kind=self.turn_kind, instruction=instruction,
                         clarification_question=self.clarification_question,
                         task_intent=task, scene_edit=self.scene_edit, scene_query=self.scene_query,
                         session_control=self.session_control, robot_setup_request=self.robot_setup_request)


class TaskParseWireOutput(BaseModel):
    """Lightweight provider envelope used before semantic normalization.

    The legacy ``TaskParseOutput`` intentionally remains strict for replay and
    direct callers.  Live Qwen scene edits use this wire model because
    ``reference`` may name an existing environment object (for example
    ``table``) that is not a task entity.
    """
    model_config = ConfigDict(extra="ignore")
    protocol_version: str = "task_understanding.v2"
    arm_usage: Literal["unspecified", "both_required"] = "unspecified"
    hold_constraints: list[dict[str, Any]] = Field(default_factory=list)
    status: TurnStatus = TurnStatus.ACCEPTED
    turn_kind: TurnKind = TurnKind.ROBOT_TASK
    clarification_question: str | None = None
    scene_edit: dict[str, Any] | None = None
    scene_query: dict[str, Any] | None = None
    session_control: dict[str, Any] | None = None
    robot_setup_request: dict[str, Any] | None = None
    entities: list[dict[str, Any]] = Field(default_factory=list)
    operations: list[dict[str, Any]] = Field(default_factory=list)
    relations: list[dict[str, Any]] = Field(default_factory=list)


def _wire_entity(value: dict[str, Any]) -> TaskEntity:
    if not isinstance(value, dict):
        raise BrainError("provider_output_schema_invalid", "wire_parse", "scene entity must be an object",
                         category="provider_schema", path="scene_edit.entities")
    value = dict(value)
    if "entity_id" not in value and "id" in value:
        value["entity_id"] = value.pop("id")
    if "semantic_name" not in value and "name" in value:
        value["semantic_name"] = value.pop("name")
    try:
        return TaskEntity.model_validate(value)
    except ValidationError as exc:
        raise BrainError("provider_output_schema_invalid", "wire_parse",
                         "scene entity does not match the task entity shape",
                         category="provider_schema", path="scene_edit.entities",
                         details={"errors": exc.errors()}) from exc


def _wire_scene_edit(value: dict[str, Any]) -> SceneEditPlan:
    if not isinstance(value, dict):
        raise BrainError("provider_output_schema_invalid", "wire_parse", "scene_edit must be an object",
                         category="provider_schema", path="scene_edit")
    try:
        entities = [_wire_entity(item) for item in value.get("entities", [])]
        relations = [SpatialRelation.model_validate(item) for item in value.get("relations", [])]
        operations = [SceneEditIntent.model_validate(item) for item in value.get("operations", [])]
    except BrainError:
        raise
    except ValidationError as exc:
        raise BrainError("provider_output_schema_invalid", "wire_parse",
                         "scene_edit payload has invalid field types",
                         category="provider_schema", path="scene_edit",
                         details={"errors": exc.errors()}) from exc
    if not entities or not operations:
        raise BrainError("semantic_protocol_error", "semantic_validation",
                         "scene_edit requires entities and operations", category="semantic_protocol")
    # Bypass only SceneEditPlan's historical entity/reference cross-field check;
    # operation/field validators have already run and are retained.
    plan = SceneEditPlan.model_construct(
        scene_basis=value.get("scene_basis", "current"), entities=entities,
        relations=relations, operations=operations,
    )
    try:
        plan.validate_semantics(allow_unresolved_references=True)
    except ValueError as exc:
        raise BrainError("semantic_protocol_error", "semantic_validation", str(exc),
                         category="semantic_protocol") from exc
    return plan


def _parse_scene_edit_wire(value: dict[str, Any], instruction: str) -> BrainTurn:
    try:
        wire = TaskParseWireOutput.model_validate(value)
    except ValidationError as exc:
        raise BrainError("provider_output_schema_invalid", "wire_parse",
                         "task output envelope has invalid field types",
                         category="provider_schema", details={"errors": exc.errors()}) from exc
    plan = _wire_scene_edit(wire.scene_edit or {})
    # BrainTurn's historical nested validation delegates back to the strict
    # SceneEditPlan model.  The wire path has already run the staged semantic
    # checks above, so construct the canonical turn without re-running the
    # legacy entity-only reference rule.
    return BrainTurn.model_construct(status=TurnStatus.ACCEPTED, turn_kind=TurnKind.SCENE_EDIT,
                                     instruction=instruction, scene_edit=plan)


def _open_close_reference_missing(value, error):
    """Only classify this narrow Qwen omission as clarification.

    Internal/replay callers still get the original validation error.  This
    helper is used exclusively by the live Qwen adapter before returning a
    BrainTurn, and never invents a door/handle/reference.
    """
    if not isinstance(value, dict) or value.get("status") != TurnStatus.ACCEPTED.value:
        return False
    operations = value.get("operations")
    if not isinstance(operations, list):
        return False
    missing = [item for item in operations if isinstance(item, dict)
               and item.get("type") in {TaskType.OPEN.value, TaskType.CLOSE.value}
               and not item.get("reference")]
    return bool(missing) and "reference" in str(error)


def parse_qwen_turn(value, instruction: str) -> BrainTurn:
    """Parse live model output with narrow, fail-closed clarification recovery."""
    # Some constrained decoders put a query's explicit selector in the robot root
    # relations slot. Move it only when there is exactly one unambiguous owner;
    # never invent a reference, predicate, entity, or operation.
    if (isinstance(value, dict) and value.get("status") == "accepted"
            and value.get("turn_kind") == "scene_query" and not value.get("entities")
            and not value.get("operations") and isinstance(value.get("scene_query"), dict)
            and value.get("relations") and not value["scene_query"].get("relations")
            and value["scene_query"].get("query_type") == "selection"):
        value = {**value, "scene_query": {**value["scene_query"], "relations": value["relations"]}, "relations": []}
    if isinstance(value, dict) and value.get("status") in {
        TurnStatus.CLARIFICATION_REQUIRED.value, TurnStatus.UNSUPPORTED_TASK.value,
    }:
        status = TurnStatus(value["status"])
        turn_kind = TurnKind.UNSUPPORTED_TASK if status == TurnStatus.UNSUPPORTED_TASK else TurnKind.ROBOT_TASK
        question = value.get("clarification_question")
        if not isinstance(question, str) or not question.strip():
            question = ("当前 Piper 双臂任务需要明确两只机械臂的对象分配和执行能力。"
                        if value.get("arm_usage") == "both_required"
                        else ("本期只支持对象局部轴缩放，不支持沿世界轴缩放。" if status == TurnStatus.UNSUPPORTED_TASK and "世界" in instruction
                              else "该请求超出当前已注册能力，不能生成可执行计划。" if status == TurnStatus.UNSUPPORTED_TASK
                              else "请补充任务所需的对象、数量、参照物或执行条件。"))
        return BrainTurn(status=status, turn_kind=turn_kind, instruction=instruction,
                         clarification_question=question.strip())
    # Scene edits use the staged wire -> normalize path.  In particular,
    # references such as ``table`` are allowed to remain unresolved here and
    # are bound against the current/original scene by SceneReferenceResolver.
    if isinstance(value, dict) and value.get("status", TurnStatus.ACCEPTED.value) == TurnStatus.ACCEPTED.value \
            and value.get("turn_kind") == TurnKind.SCENE_EDIT.value:
        return _parse_scene_edit_wire(value, instruction)
    try:
        parsed = TaskParseOutput.model_validate(value)
        return parsed.to_brain_turn(instruction)
    except (ValidationError, ValueError) as exc:
        if (isinstance(value, dict) and value.get("turn_kind") == "scene_query"
                and isinstance(value.get("scene_query"), dict)
                and (value["scene_query"].get("query_type") == "selection" or
                     any(isinstance(r, dict) and r.get("relation") == "near" and r.get("reference") is None
                         for r in (value["scene_query"].get("relations") or []) + (value.get("relations") or [])))):
            return BrainTurn(status=TurnStatus.CLARIFICATION_REQUIRED, turn_kind=TurnKind.SCENE_QUERY,
                             instruction=instruction, clarification_question="你想查询哪个参照物旁边的物体？请明确参照物名称；不会猜测缺失的参照关系。")
        if _open_close_reference_missing(value, exc):
            return BrainTurn(
                status=TurnStatus.CLARIFICATION_REQUIRED,
                turn_kind=TurnKind.ROBOT_TASK,
                instruction=instruction,
                clarification_question="请说明对应的门/抽屉把手或明确参照物，不能仅指定要打开的门。",
            )
        raise




def normalize_motion_language(intent: TaskIntent) -> TaskIntent:
    """Make the user's explicit distance authoritative over model scale output."""
    operations = []
    move_count = sum(operation.task_type.value == "move" for operation in intent.operations)
    spans = resolve_motion_evidence(intent.instruction, move_count) if move_count else []
    if not spans:
        return intent
    span_index = 0
    for operation in intent.operations:
        if operation.task_type.value != "move":
            operations.append(operation)
            continue
        span = spans[span_index]
        span_index += 1
        if span.distance_m is None and span.motion_scale is None and operation.distance_m is None and operation.motion_scale is None:
            raise ValueError("motion_distance_evidence_missing")
        values = operation.model_dump()
        values["motion_direction"] = span.direction
        if span.distance_m is not None or span.motion_scale is not None:
            values.update(distance_m=span.distance_m, motion_scale=span.motion_scale)
        operations.append(Operation.model_validate(values))
    return intent.model_copy(update={"operations": operations})
