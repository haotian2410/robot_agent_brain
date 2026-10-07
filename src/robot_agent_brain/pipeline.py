from __future__ import annotations

from collections.abc import Callable
from pydantic import BaseModel, ConfigDict, Field, model_validator

from .contracts.camera import CameraFrame
from .contracts.commands import CommandsFile
from .contracts.grounded_task import GroundedTask
from .contracts.scene import SceneConfig, ScenePatch
from .contracts.skill_plan import SkillPlan
from .contracts.task_intent import TaskIntent
from .contracts.turn import BrainTurn, SessionControlIntent, TurnKind, TurnStatus
from .scene.query import SceneQueryEngine, SceneQueryResult
from .scene.editor import SceneEditor
from .grounding.scene_grounder import SceneGrounder, GroundingAmbiguous
from .grounding.vision_fallback import VisionFallbackGrounder
from .models.vision_grounding import VisionEntity
from .models.task_understanding import TaskUnderstandingRequest, normalize_motion_language
from .planning.command_exporter import CommandExporter
from .planning.motion_scale import MotionScaleResolver
from .planning.recipe_planner import RecipePlanner
from .planning.task_expander import TaskExpander
from .semantics.task_domain_policy import TaskDomainPolicy

class BrainResult(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    status: TurnStatus = TurnStatus.ACCEPTED
    turn_kind: TurnKind = TurnKind.ROBOT_TASK
    task_intent: TaskIntent | None = Field(default=None, alias="intent")
    grounded_task: GroundedTask | None = None
    skill_plan: SkillPlan | None = None
    commands: CommandsFile | None = None
    scene_patch: ScenePatch | None = None
    scene_query_result: SceneQueryResult | None = None
    session_action: SessionControlIntent | None = None
    focus_object_ids: list[str] | None = None
    deleted_object_ids: list[str] = Field(default_factory=list)

    @property
    def intent(self):
        return self.task_intent

    @model_validator(mode="after")
    def turn_payload(self):
        groups = {
            TurnKind.ROBOT_TASK: (self.task_intent, self.grounded_task, self.skill_plan, self.commands),
            TurnKind.SCENE_EDIT: (self.scene_patch,),
            TurnKind.SCENE_QUERY: (self.scene_query_result,),
            TurnKind.SESSION_CONTROL: (self.session_action,),
        }
        if self.status != TurnStatus.ACCEPTED:
            if any(v is not None for values in groups.values() for v in values):
                raise ValueError("brain_result_rejected_payload")
            return self
        if self.turn_kind not in groups or any(v is None for v in groups[self.turn_kind]):
            raise ValueError("brain_result_payload_missing")
        if any(v is not None for kind, values in groups.items() if kind != self.turn_kind for v in values):
            raise ValueError("brain_result_payload_mismatch")
        return self

class BrainPipeline:
    def __init__(self, understanding, assets, scene_editor=None, vision_provider=None):
        self.understanding = understanding
        self.aliases = getattr(getattr(assets, "metadata", None), "aliases", {})
        self.category_aliases = getattr(getattr(assets, "metadata", None), "category_aliases", {})
        self.grounder = SceneGrounder(aliases=self.aliases, category_aliases=self.category_aliases)
        self.motion = MotionScaleResolver(assets)
        self.planner = RecipePlanner()
        self.expander = TaskExpander()
        self.scene_editor = scene_editor or SceneEditor(assets)
        self.exporter = CommandExporter()
        self.vision_provider = vision_provider
        self.vision_fallback = VisionFallbackGrounder()
        self.domain_policy = TaskDomainPolicy()

    def understand_turn(self, instruction: str, *, scene: SceneConfig | None = None,
                        dialogue=None) -> BrainTurn:
        """Call understanding once; keep injected context out of the user text."""
        deferred_reference_error = None
        try:
            provider_instruction = dialogue.contextualize(instruction, scene) if dialogue and scene is not None else instruction
        except ValueError as exc:
            if str(exc) not in {"dialogue_reference_missing", "dialogue_reference_ambiguous"}:
                raise
            # Only parsed lifecycle can establish whether 'it' is a new object
            # introduced in this turn. Do not reject it before understanding.
            deferred_reference_error = exc
            provider_instruction = instruction
        request = TaskUnderstandingRequest(instruction=provider_instruction)
        if hasattr(self.understanding, "understand_turn"):
            turn = self.understanding.understand_turn(request)
        else:
            intent = self.understanding.understand(request)
            turn = BrainTurn(status="accepted", turn_kind="robot_task", instruction=instruction, task_intent=intent)
        turn = turn.model_copy(update={"instruction": instruction})
        if deferred_reference_error is not None and turn.status == TurnStatus.ACCEPTED:
            from .contracts.turn import SceneEditPlan
            edits = turn.scene_edit
            introduced, reused = set(), set()
            valid_local = isinstance(edits, SceneEditPlan)
            if valid_local:
                by_id = {e.entity_id:e for e in edits.entities}
                for edit in edits.operations:
                    if edit.reference in by_id and (by_id[edit.reference].dialogue_ref or by_id[edit.reference].dialogue_ref_set):
                        valid_local &= edit.reference in introduced
                    if edit.operation == "add":
                        introduced.add(edit.target)
                    elif edit.target in introduced:
                        reused.add(edit.target)
                    elif edit.target in by_id and (by_id[edit.target].dialogue_ref or by_id[edit.target].dialogue_ref_set):
                        valid_local = False
            if not valid_local or not reused:
                raise deferred_reference_error
        if turn.task_intent is not None:
            turn = turn.model_copy(update={"task_intent": turn.task_intent.model_copy(update={"instruction": instruction})})
        turn = self.domain_policy.classify(turn, instruction)
        if turn.status == TurnStatus.ACCEPTED and turn.turn_kind == TurnKind.ROBOT_TASK:
            turn = turn.model_copy(update={"task_intent": normalize_motion_language(turn.task_intent)})
        return turn

    def process_turn(self, request_id: str, turn: BrainTurn, scene: SceneConfig | None, *,
                     dialogue=None, bindings_override=None, edit_defaults=None,
                     capture: Callable[[], CameraFrame] | None = None,
                     held_object: str | None = None) -> BrainResult:
        """Consume an understood turn without another provider call or normalization."""
        if turn.status != TurnStatus.ACCEPTED:
            return BrainResult(status=turn.status, turn_kind=turn.turn_kind)
        if turn.turn_kind == TurnKind.SESSION_CONTROL:
            return BrainResult(turn_kind=turn.turn_kind, session_action=turn.session_control)
        if scene is None:
            raise ValueError("scene_required")
        if turn.turn_kind == TurnKind.SCENE_EDIT:
            edited = self.scene_editor.edit_result(turn.scene_edit, scene, dialogue=dialogue, defaults=edit_defaults,
                                                  bindings_override=bindings_override)
            return BrainResult(turn_kind=turn.turn_kind, scene_patch=edited.patch,
                               focus_object_ids=edited.focus_object_ids or None,
                               deleted_object_ids=edited.deleted_object_ids)
        if turn.turn_kind == TurnKind.SCENE_QUERY:
            query = SceneQueryEngine(aliases=self.aliases, category_aliases=self.category_aliases).query(turn.scene_query, scene, dialogue)
            return BrainResult(turn_kind=turn.turn_kind, scene_query_result=query, focus_object_ids=query.object_ids)
        intent = turn.task_intent
        overrides = dialogue.bindings(intent, scene) if dialogue else {}
        for entity_id, ids in (bindings_override or {}).items():
            if entity_id in overrides and overrides[entity_id] != ids:
                raise ValueError("grounding_binding_conflict: " + entity_id)
            overrides[entity_id] = ids
        frame = None
        while True:
            try:
                grounded = self.grounder.ground(intent, scene, overrides)
                break
            except GroundingAmbiguous as exc:
                if self.vision_provider is None or capture is None or exc.entity.entity_id in overrides:
                    raise
                if frame is None:
                    frame = capture()
                ids = self.vision_fallback.resolve(exc.entity, exc.candidates, scene, frame, self.vision_provider)
                overrides[exc.entity.entity_id] = ids
        grounded = self.expander.expand(grounded, scene)
        grounded = self.motion.resolve(grounded)
        plan = self.planner.plan(grounded, held_object=held_object)
        commands = self.exporter.export(request_id, grounded, plan, scene, held_object=held_object)
        by_entity = {e.entity_id:e.scene_object_id for e in grounded.entities}
        focus = list(dict.fromkeys(by_entity[op.source or op.target] for op in grounded.operations))
        return BrainResult(task_intent=intent, grounded_task=grounded, skill_plan=plan, commands=commands, focus_object_ids=focus)

    def run(self, request_id: str, instruction: str, scene: SceneConfig, *,
            dialogue=None, capture: Callable[[], CameraFrame] | None = None,
            held_object: str | None = None, bindings_override=None) -> BrainResult:
        turn = self.understand_turn(instruction, scene=scene, dialogue=dialogue)
        return self.process_turn(request_id, turn, scene, dialogue=dialogue, capture=capture,
                                 held_object=held_object, bindings_override=bindings_override)

    def run_turn(self, request_id, instruction, scene, **kwargs):
        return self.run(request_id, instruction, scene, **kwargs)
