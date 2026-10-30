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
from ..semantics.scene_references import CanonicalReference, RefScope, SceneReferenceCatalog


def task_understanding_wire_schema():
    """Compatibility alias for the single live v3 wire schema."""
    return task_understanding_v3_wire_schema()


def _require_schema_fields(schema: dict[str, Any], *names: str) -> None:
    """Make optional Pydantic fields explicit for a constrained JSON decoder."""
    properties = schema.get("properties", {})
    required = list(schema.get("required", []))
    required.extend(name for name in names if name in properties and name not in required)
    schema["required"] = required


def task_understanding_v3_wire_schema():
    """Return the complete v3 provider contract.

    The old adapter exposed only ``turn_kind`` as required.  That let a
    constrained decoder finish a response before it selected the route
    payload, and the Python side then had to guess which legacy envelope was
    intended.  v3 is deliberately explicit: every top-level payload/array is
    present (or ``null``/empty), and the two scene routes have typed schemas.
    """
    schema = TaskParseWireOutput.model_json_schema()
    _require_schema_fields(schema, *schema.get("properties", {}))
    defs = schema.get("$defs", {})
    for name in ("SceneEditWire", "SceneQueryWire"):
        if name in defs:
            _require_schema_fields(defs[name], *defs[name].get("properties", {}))
    # The operation fields which are semantically optional must still be
    # emitted as explicit nulls.  This is important for JSON-schema decoding:
    # relation/reference pairing is checked by Python, not guessed by Qwen.
    edit = defs.get("SceneEditIntent")
    if edit is not None:
        _require_schema_fields(edit, "relation", "reference", "direction", "distance_m",
                               "motion_scale", "coordinate_frame", "axis", "angle_deg",
                               "placement_hint", "placement_region")
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


class TaskEntityWire(TaskEntity):
    """Canonical entity shape accepted by the v3 scene wire.

    A few recorded v2 responses used ``id``/``name``.  They are normalized at
    the wire boundary only; the canonical parser and every downstream stage
    see ``entity_id``/``semantic_name``.  No other legacy fields are accepted.
    """

    @model_validator(mode="before")
    @classmethod
    def normalize_legacy_names(cls, value):
        if not isinstance(value, dict):
            return value
        value = dict(value)
        if "entity_id" not in value and "id" in value:
            value["entity_id"] = value.pop("id")
        if "semantic_name" not in value and "name" in value:
            value["semantic_name"] = value.pop("name")
        return value


class RobotOperationWire(BaseModel):
    """Canonical v3 operation emitted for ``robot_task`` turns.

    The public wire name is ``operation``.  ``type`` is accepted only at this
    parser boundary for recorded v2/replay responses; it is deliberately not
    present in the generated JSON schema.  Keeping that compatibility here
    prevents old fixtures from changing the live protocol again.
    """

    model_config = ConfigDict(extra="forbid")
    operation: TaskType
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

    @model_validator(mode="before")
    @classmethod
    def normalize_legacy_operation(cls, value):
        if not isinstance(value, dict):
            return value
        value = dict(value)
        if "operation" not in value and "type" in value:
            value["operation"] = value.pop("type")
        return value

    def to_operation(self, operation_id: str) -> Operation:
        values = self.model_dump(mode="python", exclude={"operation"})
        return Operation(operation_id=operation_id, task_type=self.operation, **values)


class SceneEditWire(BaseModel):
    """Typed scene-edit payload before scene-reference binding.

    ``reference`` intentionally remains a string here.  It can name an entity
    declared in this payload or a registered environment reference such as
    ``table``.  SceneReferenceResolver performs the latter binding after the
    wire has been normalized; this model only enforces the operation shape and
    that target/replacement roles are declared entities.
    """

    model_config = ConfigDict(extra="forbid")
    scene_basis: Literal["current", "original"] = "current"
    entities: list[TaskEntityWire] = Field(min_length=1)
    relations: list[SpatialRelation] = Field(default_factory=list)
    operations: list[SceneEditIntent] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_entity_roles(self):
        entity_ids = {entity.entity_id for entity in self.entities}
        if len(entity_ids) != len(self.entities):
            raise ValueError("scene_edit_duplicate_entity_id")
        for relation in self.relations:
            if relation.subject not in entity_ids:
                raise ValueError("scene_edit_unknown_selector: " + relation.subject)
        for operation in self.operations:
            if operation.target not in entity_ids:
                raise ValueError("scene_edit_unknown_selector: " + operation.target)
            if operation.replacement_entity is not None and operation.replacement_entity not in entity_ids:
                raise ValueError("scene_replace_unknown_entity: " + operation.replacement_entity)
        return self


class SceneQueryWire(BaseModel):
    """Typed scene-query payload before canonical query validation."""

    model_config = ConfigDict(extra="forbid")
    query_type: Literal["count", "existence", "position", "state", "neighbors", "relation", "selection"]
    entities: list[TaskEntityWire] = Field(min_length=1)
    relations: list[SpatialRelation] = Field(default_factory=list)
    target: str = Field(min_length=1)
    reference: str | None = None
    predicate: Literal["left_of", "right_of", "front_of", "behind", "above", "below", "on"] | None = None
    evidence_source: Literal["scene", "image"] = "scene"

    @model_validator(mode="after")
    def validate_entity_roles(self):
        entity_ids = {entity.entity_id for entity in self.entities}
        if self.target not in entity_ids:
            raise ValueError("query_target_missing")
        for relation in self.relations:
            if relation.subject not in entity_ids:
                raise ValueError("query_unknown_selector: " + relation.subject)
            # A reference can be an environment object (notably table), and
            # is resolved by SceneReferenceResolver in the scene-aware stage.
        return self


class TaskParseOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    # Responses emitted by the historical envelope are v2 unless the model
    # explicitly opts into the canonical v3 envelope.  Keeping this marker on
    # the adapter output makes migration metrics truthful for non-scene turns.
    protocol_version: Literal["task_understanding.v2", "task_understanding.v3"] = "task_understanding.v2"
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
        return BrainTurn(protocol_version=self.protocol_version, status=status, turn_kind=self.turn_kind, instruction=instruction,
                         clarification_question=self.clarification_question,
                         task_intent=task, scene_edit=self.scene_edit, scene_query=self.scene_query,
                         session_control=self.session_control, robot_setup_request=self.robot_setup_request)


class TaskParseWireOutput(BaseModel):
    """Strict v3 provider envelope used before semantic normalization.

    ``TaskParseOutput`` remains available for legacy replay/direct callers.
    Live Qwen responses use this model so scene-edit and scene-query payloads
    are typed at the wire boundary instead of being accepted as arbitrary
    dictionaries.  Environment references are intentionally resolved later;
    this is why a scene edit may reference ``table`` without declaring a
    synthetic table entity.
    """
    model_config = ConfigDict(extra="forbid")
    protocol_version: Literal["task_understanding.v2", "task_understanding.v3"] = "task_understanding.v3"
    arm_usage: Literal["unspecified", "both_required"] = "unspecified"
    hold_constraints: list[TaskHoldConstraint] = Field(default_factory=list)
    status: TurnStatus = TurnStatus.ACCEPTED
    turn_kind: TurnKind = TurnKind.ROBOT_TASK
    clarification_question: str | None = None
    scene_edit: SceneEditWire | None = None
    scene_query: SceneQueryWire | None = None
    session_control: SessionControlIntent | None = None
    robot_setup_request: RobotSetupRequest | None = None
    # All live v3 routes use the same canonical entity/operation vocabulary.
    # ``TaskParseOutput`` above remains the explicit legacy replay adapter.
    entities: list[TaskEntityWire] = Field(default_factory=list)
    operations: list[RobotOperationWire] = Field(default_factory=list)
    relations: list[ParseRelation] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_envelope(self):
        if self.status == TurnStatus.ACCEPTED and self.clarification_question is not None:
            raise ValueError("task_semantic_invalid: accepted turn cannot contain clarification_question")
        if self.hold_constraints and (self.status != TurnStatus.ACCEPTED or self.turn_kind != TurnKind.ROBOT_TASK):
            raise ValueError("task_semantic_invalid: hold constraints require accepted robot task")
        if self.arm_usage != "unspecified" and (self.status != TurnStatus.ACCEPTED or self.turn_kind != TurnKind.ROBOT_TASK):
            raise ValueError("task_semantic_invalid: arm usage requires accepted robot task")
        payloads = {
            TurnKind.SCENE_EDIT: self.scene_edit,
            TurnKind.SCENE_QUERY: self.scene_query,
            TurnKind.SESSION_CONTROL: self.session_control,
        }
        if self.status != TurnStatus.ACCEPTED:
            if (self.robot_setup_request is not None or self.entities or self.operations or self.relations
                    or any(value is not None for value in payloads.values())):
                raise ValueError("task_semantic_invalid: rejected turn has payload")
            return self
        if self.robot_setup_request is not None and self.turn_kind not in {TurnKind.ROBOT_CONFIG, TurnKind.ROBOT_TASK}:
            raise ValueError("task_semantic_invalid: robot setup requires robot turn")
        if self.turn_kind == TurnKind.ROBOT_TASK:
            if not self.entities or not self.operations or any(value is not None for value in payloads.values()):
                raise ValueError("task_semantic_invalid: robot task needs only entities and operations")
        elif self.turn_kind == TurnKind.ROBOT_CONFIG:
            if (self.robot_setup_request is None or self.entities or self.operations or self.relations
                    or any(value is not None for value in payloads.values())):
                raise ValueError("task_semantic_invalid: robot config payload mismatch")
        elif self.turn_kind in payloads:
            if (self.entities or self.operations or self.relations or payloads[self.turn_kind] is None
                    or sum(value is not None for value in payloads.values()) != 1):
                raise ValueError("task_semantic_invalid: turn payload mismatch")
        elif self.turn_kind == TurnKind.UNSUPPORTED_TASK:
            raise ValueError("task_semantic_invalid: unsupported turn cannot be accepted")
        else:
            raise ValueError("task_semantic_invalid: unknown turn kind")
        entity_ids = {entity.entity_id for entity in self.entities}
        catalog = SceneReferenceCatalog()
        if any(relation.subject not in entity_ids or
               (relation.reference and relation.reference not in entity_ids and catalog.lookup(relation.reference) is None)
               for relation in self.relations):
            raise ValueError("task_semantic_invalid: relation references unknown entities")
        return self

    def to_task_intent(self, instruction: str) -> TaskIntent:
        if self.status != TurnStatus.ACCEPTED or self.turn_kind != TurnKind.ROBOT_TASK:
            raise ValueError("task_semantic_invalid: no robot task payload")
        text = instruction.casefold()
        both = any(token in text for token in ("两只手各", "两臂分别", "用双臂分别", "both hands", "both arms must"))
        if both and self.arm_usage != "both_required" and {op.arm for op in self.operations} != {"left", "right"}:
            raise ValueError("task_semantic_invalid: arm_usage_required")
        stable = (any(token in instruction for token in ("左臂保持", "右臂保持", "先不要松手", "hold position"))
                  and any(token in instruction for token in ("左臂", "右臂", "left arm", "right arm")))
        if stable and not self.hold_constraints:
            raise ValueError("task_semantic_invalid: hold_constraint_required")
        moves = [o for o in self.operations if o.operation == TaskType.MOVE]
        spans = resolve_motion_evidence(instruction, len(moves)) if moves else []
        operation_values = []
        span_index = 0
        entity_counts = {entity.entity_id: entity.count for entity in self.entities}
        pairwise_clause = ("分别" in instruction or "一一对应" in instruction)
        for item in self.operations:
            values = item.model_dump(mode="python", exclude={"operation"})
            role_counts = [entity_counts.get(role, 1) for role in
                           (item.source, item.target, item.destination, item.reference) if role]
            if values.get("assignment_mode") == "broadcast" and pairwise_clause and sum(count > 1 for count in role_counts) >= 2:
                values["assignment_mode"] = "pairwise"
            if item.operation == TaskType.MOVE and spans:
                span = spans[span_index]
                span_index += 1
                values.update(motion_direction=span.direction, distance_m=span.distance_m,
                              motion_scale=span.motion_scale)
            operation_index = len(operation_values)
            try:
                operation_values.append(Operation(operation_id=f"op-{operation_index+1}",
                                                  task_type=item.operation, **values))
            except ValidationError as exc:
                message = str(exc.errors()[0].get("msg", "operation is invalid"))
                raise ValueError(f"task_semantic_invalid: operations.{operation_index}: {message}") from exc
        entities = [TaskEntity.model_validate(item.model_dump(mode="json")) for item in self.entities]
        relations = [SpatialRelation(scope=item.scope, subject=item.subject,
                                     relation=item.relation, reference=item.reference)
                     for item in self.relations]
        return TaskIntent(instruction=instruction, arm_usage=self.arm_usage,
                          hold_constraints=self.hold_constraints, entities=entities,
                          operations=operation_values, spatial_relations=relations)

    def to_brain_turn(self, instruction: str) -> BrainTurn:
        task = self.to_task_intent(instruction) if self.status == TurnStatus.ACCEPTED and self.turn_kind == TurnKind.ROBOT_TASK else None
        return BrainTurn(protocol_version=self.protocol_version, status=self.status,
                         turn_kind=self.turn_kind, instruction=instruction,
                         clarification_question=self.clarification_question,
                         task_intent=task, scene_edit=None, scene_query=None,
                         session_control=self.session_control,
                         robot_setup_request=self.robot_setup_request)


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
        return TaskEntityWire.model_validate(value)
    except ValidationError as exc:
        raise BrainError("provider_output_schema_invalid", "wire_parse",
                         "scene entity does not match the task entity shape",
                         category="provider_schema", path="scene_edit.entities",
                         details={"errors": exc.errors()}) from exc


def _error_path(errors, prefix=()):
    """Return a stable dotted path from the first Pydantic error."""
    if not errors:
        return ".".join(str(part) for part in prefix) or None
    loc = tuple(prefix) + tuple(errors[0].get("loc", ()))
    return ".".join(str(part) for part in loc) or None


def _is_semantic_validation(errors):
    semantic_tokens = (
        "task_semantic_invalid", "scene_edit_", "scene_replace_", "query_",
        "scene_relation_", "dual_", "motion_", "requires reference",
    )
    return any(any(token in str(error.get("msg", "")) for token in semantic_tokens)
               or error.get("type") == "value_error" for error in errors)


def _parse_robot_task_wire(value: dict[str, Any], instruction: str) -> BrainTurn:
    try:
        wire = TaskParseWireOutput.model_validate(value)
        if wire.turn_kind != TurnKind.ROBOT_TASK:
            raise ValueError("task_semantic_invalid: robot wire route mismatch")
        return wire.to_brain_turn(instruction)
    except ValidationError as exc:
        errors = exc.errors()
        semantic = _is_semantic_validation(errors)
        missing = any(error.get("type") == "missing" for error in errors)
        legacy_payload = isinstance(value, dict) and any(
            isinstance(item, dict) and "type" in item and "operation" not in item
            for item in (value.get("operations") or [])
        )
        # Keep recorded v2 malformed payloads in the historical provider
        # bucket.  Real v3 payloads (which use ``operation``) are classified
        # as semantic protocol failures, so the migration cannot hide live
        # contract errors behind provider_error.
        if legacy_payload and semantic and not any(
                isinstance(item, dict) and item.get("type") in {TaskType.OPEN.value, TaskType.CLOSE.value}
                for item in (value.get("operations") or [])):
            semantic = False
            missing = False
        if legacy_payload:
            code = "provider_error"
            category = "provider_schema"
        elif semantic:
            code = "semantic_protocol_error"
            category = "semantic_protocol"
        elif missing:
            code = "qwen_json_incomplete"
            category = "provider_schema"
        else:
            code = "provider_output_schema_invalid"
            category = "provider_schema"
        raise BrainError(code, "wire_parse",
                         "robot_task payload is incomplete or violates the v3 semantic contract",
                         category=category, path=_error_path(errors),
                         details={"errors": errors}) from exc
    except (ValueError, TypeError) as exc:
        text = str(exc)
        if text.startswith(("task_semantic_invalid", "scene_", "query_", "dual_", "motion_")):
            import re
            match = re.search(r"operations\.\d+", text)
            legacy_payload = isinstance(value, dict) and any(
                isinstance(item, dict) and "type" in item and "operation" not in item
                for item in (value.get("operations") or []))
            if legacy_payload and not text.startswith("motion_"):
                raise BrainError("provider_error", "wire_parse", text,
                                 category="provider_schema", path=match.group(0) if match else None) from exc
            code = text.split(":", 1)[0] if text.startswith("motion_") else "semantic_protocol_error"
            raise BrainError(code, "semantic_validation", text,
                             category="semantic_protocol", path=match.group(0) if match else None) from exc
        raise


def _wire_scene_edit(value: SceneEditWire | dict[str, Any]) -> SceneEditPlan:
    if isinstance(value, dict):
        try:
            wire = SceneEditWire.model_validate(value)
        except ValidationError as exc:
            raise BrainError("provider_output_schema_invalid", "wire_parse",
                             "scene_edit payload has invalid field types",
                             category="provider_schema", path=_error_path(exc.errors(), ("scene_edit",)),
                             details={"errors": exc.errors()}) from exc
    elif isinstance(value, SceneEditWire):
        wire = value
    else:
        raise BrainError("provider_output_schema_invalid", "wire_parse", "scene_edit must be an object",
                         category="provider_schema", path="scene_edit")
    entities = [TaskEntity.model_validate(item.model_dump(mode="json")) for item in wire.entities]
    relations = list(wire.relations)
    # operation_id is internal canonical metadata.  The clean v3 prompt does
    # not ask Qwen to emit it, so assign deterministic IDs after wire parsing.
    operations = []
    for index, item in enumerate(wire.operations, 1):
        values = item.model_dump(mode="json")
        values["operation_id"] = item.operation_id or f"op-{index}"
        operations.append(SceneEditIntent.model_validate(values))
    # The formal SceneEditPlan validator now understands registered
    # environment references, so the live wire path no longer needs
    # ``model_construct`` to bypass entity-only checks.
    entity_ids = {entity.entity_id for entity in entities}
    catalog = SceneReferenceCatalog()
    scene_refs = []
    raw_references = [operation.reference for operation in operations]
    raw_references.extend(relation.reference for relation in relations)
    for raw_reference in raw_references:
        if raw_reference and raw_reference not in entity_ids:
            spec = catalog.lookup(raw_reference)
            if all(ref.raw_value != raw_reference for ref in scene_refs):
                scene_refs.append(CanonicalReference(
                    raw_value=raw_reference,
                    canonical_value=spec.canonical_id if spec is not None else raw_reference.strip().casefold(),
                    scope=RefScope.SCENE_REF,
                    kind=spec.kind if spec is not None else None))
    try:
        plan = SceneEditPlan.model_validate({
            "scene_basis": wire.scene_basis, "entities": entities,
            "relations": relations, "operations": operations, "scene_refs": scene_refs,
        })
    except ValidationError as exc:
        errors = exc.errors()
        raise BrainError("semantic_protocol_error", "semantic_validation",
                         str(errors[0].get("msg", "scene edit semantic validation failed")),
                         category="semantic_protocol", path=_error_path(errors, ("scene_edit",)),
                         details={"errors": errors}) from exc
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
        # ``scene_basis`` is a semantic choice, not a transport type error.
        # Keep the diagnostic category stable for callers and logs even though
        # Pydantic enforces the enum at the wire boundary.
        errors = exc.errors()
        semantic_error = any(
            error.get("type") == "value_error"
            and any(token in str(error.get("msg", "")) for token in (
                "scene_edit_", "scene_replace_", "query_", "task_semantic_invalid",
            ))
            for error in errors
        )
        if semantic_error or any(error.get("loc", ())[-2:] == ("scene_edit", "scene_basis")
                                 for error in errors):
            raw_basis = ((value.get("scene_edit") or {}).get("scene_basis")
                         if isinstance(value, dict) else None)
            raise BrainError("semantic_protocol_error", "semantic_validation",
                             str(errors[0].get("msg", "scene edit semantic validation failed")),
                             category="semantic_protocol", path=_error_path(errors),
                             value=raw_basis, details={"errors": errors}) from exc
        raise BrainError("provider_output_schema_invalid", "wire_parse",
                         "task output envelope has invalid field types",
                         category="provider_schema", details={"errors": exc.errors()}) from exc
    plan = _wire_scene_edit(wire.scene_edit) if wire.scene_edit is not None else None
    if plan is None:
        raise BrainError("semantic_protocol_error", "semantic_validation",
                         "scene_edit payload is required", category="semantic_protocol")
    # BrainTurn's historical nested validation delegates back to the strict
    # SceneEditPlan model.  The wire path has already run the staged semantic
    # checks above, so construct the canonical turn without re-running the
    # legacy entity-only reference rule.
    return BrainTurn.model_construct(protocol_version=wire.protocol_version,
                                     status=TurnStatus.ACCEPTED, turn_kind=TurnKind.SCENE_EDIT,
                                     instruction=instruction, scene_edit=plan)


def _parse_scene_query_wire(value: dict[str, Any], instruction: str) -> BrainTurn:
    try:
        wire = TaskParseWireOutput.model_validate(value)
    except ValidationError as exc:
        errors = exc.errors()
        if any(error.get("type") == "value_error" for error in errors):
            raise BrainError("semantic_protocol_error", "semantic_validation",
                             str(errors[0].get("msg", "scene query semantic validation failed")),
                             category="semantic_protocol", path=_error_path(errors),
                             details={"errors": errors}) from exc
        raise BrainError("provider_output_schema_invalid", "wire_parse",
                         "task output envelope has invalid field types",
                         category="provider_schema", details={"errors": exc.errors()}) from exc
    if wire.scene_query is None:
        raise BrainError("semantic_protocol_error", "semantic_validation",
                         "scene_query payload is required", category="semantic_protocol")
    values = wire.scene_query.model_dump(mode="json")
    try:
        query = SceneQueryIntent.model_validate(values)
    except ValidationError as exc:
        errors = exc.errors()
        raise BrainError("semantic_protocol_error", "semantic_validation",
                         str(errors[0].get("msg", "scene_query payload violates canonical query rules")),
                         category="semantic_protocol", path=_error_path(errors, ("scene_query",)),
                         details={"errors": errors}) from exc
    return BrainTurn.model_construct(protocol_version=wire.protocol_version,
                                     status=TurnStatus.ACCEPTED, turn_kind=TurnKind.SCENE_QUERY,
                                     instruction=instruction, scene_query=query)


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
    # A selector relation such as nearest/near needs a reference object.  The
    # wire model deliberately rejects that malformed relation, but for live
    # Qwen responses it is a recoverable clarification rather than a raw
    # provider/schema error.  Do this before model validation so the original
    # missing reference is not hidden by Pydantic's nested error.
    if isinstance(value, dict) and value.get("status", TurnStatus.ACCEPTED.value) == TurnStatus.ACCEPTED.value \
            and value.get("turn_kind") == TurnKind.SCENE_QUERY.value:
        query_payload = value.get("scene_query")
        relation_values = []
        if isinstance(query_payload, dict):
            relation_values.extend(query_payload.get("relations") or [])
        relation_values.extend(value.get("relations") or [])
        binary_query_relations = {"near", "nearest", "farthest", "inside", "on", "left_of", "right_of",
                                  "front_of", "behind", "above", "below"}
        if any(isinstance(item, dict)
               and item.get("relation") in binary_query_relations
               and not item.get("reference") for item in relation_values):
            return BrainTurn(status=TurnStatus.CLARIFICATION_REQUIRED,
                             turn_kind=TurnKind.SCENE_QUERY,
                             instruction=instruction,
                             clarification_question="请明确参照物名称，才能判断哪个对象在它旁边、最近或最远。")

    # Robot tasks use the canonical v3 wire -> normalize path.  In particular,
    # entity_id/semantic_name and operation are the live vocabulary; legacy
    # id/name/type are accepted only by RobotOperationWire's narrow adapter.
    if isinstance(value, dict) and value.get("status", TurnStatus.ACCEPTED.value) == TurnStatus.ACCEPTED.value \
            and value.get("turn_kind") == TurnKind.ROBOT_TASK.value:
        # This is a deliberately narrow Qwen recovery: an open/close action
        # without the user's explicitly named handle/reference is a
        # clarification, never an inferred door or handle.  Replay/direct
        # TaskParseOutput callers retain strict validation.
        operations = value.get("operations")
        if isinstance(operations, list) and any(
                isinstance(item, dict)
                and item.get("operation", item.get("type")) in {TaskType.OPEN.value, TaskType.CLOSE.value}
                and not item.get("reference") for item in operations):
            return BrainTurn(status=TurnStatus.CLARIFICATION_REQUIRED,
                             turn_kind=TurnKind.ROBOT_TASK, instruction=instruction,
                             clarification_question="请说明对应的门/抽屉把手或明确参照物，不能仅指定要打开的门。")
        return _parse_robot_task_wire(value, instruction)

    # Scene edits use the staged wire -> normalize path.  In particular,
    # references such as ``table`` are allowed to remain unresolved here and
    # are bound against the current/original scene by SceneReferenceResolver.
    if isinstance(value, dict) and value.get("status", TurnStatus.ACCEPTED.value) == TurnStatus.ACCEPTED.value \
            and value.get("turn_kind") == TurnKind.SCENE_EDIT.value:
        return _parse_scene_edit_wire(value, instruction)
    if isinstance(value, dict) and value.get("status", TurnStatus.ACCEPTED.value) == TurnStatus.ACCEPTED.value \
            and value.get("turn_kind") == TurnKind.SCENE_QUERY.value:
        return _parse_scene_query_wire(value, instruction)
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
