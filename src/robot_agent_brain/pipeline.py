from __future__ import annotations

from collections.abc import Callable
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator

from .contracts.camera import CameraFrame
from .contracts.commands import CommandsFile
from .contracts.commands_v3 import CommandsFileV3
from .contracts.robot_setup import RobotSetup
from .contracts.grounded_task import GroundedTask
from .contracts.scene import SceneConfig, ScenePatch, SceneId
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
from .planning.skill_planner_router import SkillPlannerRouter
from .skills.registry import REGISTRY
from .planning.task_expander import TaskExpander
from .semantics.task_domain_policy import TaskDomainPolicy

class BrainResult(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    status: TurnStatus = TurnStatus.ACCEPTED
    turn_kind: TurnKind = TurnKind.ROBOT_TASK
    task_intent: TaskIntent | None = Field(default=None, alias="intent")
    grounded_task: GroundedTask | None = None
    skill_plan: SkillPlan | None = None
    commands: CommandsFile | CommandsFileV3 | None = None
    scene_patch: ScenePatch | None = None
    scene_replacement: SceneConfig | None = None
    scene_source_snapshot: str | None = None
    scene_id_remap: dict[int, int] | None = None
    robot_setup_changed: RobotSetup | None = None
    robot_setup_was_changed: bool = False
    scene_query_result: SceneQueryResult | None = None
    session_action: SessionControlIntent | None = None
    focus_object_ids: list[SceneId] | None = None
    deleted_object_ids: list[SceneId] = Field(default_factory=list)
    planner_used: Literal["recipe", "qwen"] | None = None
    planner_trace: dict | None = Field(default=None, exclude=True)

    @property
    def intent(self):
        return self.task_intent

    @model_validator(mode="after")
    def turn_payload(self):
        groups = {
            TurnKind.ROBOT_CONFIG: (self.robot_setup_changed,),
            TurnKind.ROBOT_TASK: (self.task_intent, self.grounded_task, self.skill_plan, self.commands),
            TurnKind.SCENE_EDIT: (self.scene_patch,),
            TurnKind.SCENE_QUERY: (self.scene_query_result,),
            TurnKind.SESSION_CONTROL: (self.session_action,),
        }
        if isinstance(self.commands, CommandsFileV3):
            # A staged v3 plan is not a flattened v2 SkillPlan.
            groups[TurnKind.ROBOT_TASK] = (self.task_intent, self.grounded_task, self.commands)
        if self.turn_kind == TurnKind.ROBOT_TASK and self.robot_setup_changed is not None:
            groups[TurnKind.ROBOT_TASK] = (*groups[TurnKind.ROBOT_TASK], self.robot_setup_changed)
            groups[TurnKind.ROBOT_CONFIG] = ()
        if self.scene_replacement is not None:
            if self.scene_patch is not None:
                raise ValueError("brain_result_patch_and_replacement_exclusive")
            groups[TurnKind.SCENE_EDIT] = (self.scene_replacement,)
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
    def __init__(self, understanding, assets, scene_editor=None, vision_provider=None,
                 skill_planning_provider=None, planner_mode="recipe", robot="ur5e", aliases=None, query_near_distance_m=.2):
        self.understanding = understanding
        self.assets = assets
        self.query_near_distance_m = query_near_distance_m
        self.aliases = getattr(getattr(assets, "metadata", None), "aliases", {})
        if aliases is not None:
            self.aliases = aliases
        self.category_aliases = getattr(getattr(assets, "metadata", None), "category_aliases", {})
        self.grounder = SceneGrounder(aliases=self.aliases, category_aliases=self.category_aliases, assets=assets)
        self.motion = MotionScaleResolver(assets)
        self.planner = RecipePlanner()
        self.skill_planner = SkillPlannerRouter(mode=planner_mode, recipe_planner=self.planner,
                                               model_provider=skill_planning_provider, registry=REGISTRY)
        self.expander = TaskExpander()
        self.scene_editor = scene_editor or SceneEditor(assets, aliases=self.aliases, category_aliases=self.category_aliases)
        self.exporter = CommandExporter(robot=robot)
        self.vision_provider = vision_provider
        self.vision_fallback = VisionFallbackGrounder()
        self.domain_policy = TaskDomainPolicy()

    def understand_turn(self, instruction: str, *, scene: SceneConfig | None = None,
                        dialogue=None) -> BrainTurn:
        """Call understanding once; keep injected context out of the user text."""
        deferred_reference_error = None
        try:
            original_requested = any(token in instruction.casefold() for token in ("原始场景", "初始场景", "最开始的场景", "original scene", "initial scene"))
            provider_instruction = dialogue.contextualize(instruction, scene) if dialogue and scene is not None and not original_requested else instruction
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
        # The scene basis is a safety-sensitive routing decision, not a
        # semantic detail that Qwen may omit.  An explicit user request for
        # the original/initial scene must win over a model response that
        # leaves the default as ``current``; otherwise an apparently valid
        # edit silently mutates the latest scene instead of deriving from the
        # immutable import snapshot.
        if original_requested and turn.scene_edit is not None and turn.scene_edit.scene_basis != "original":
            turn = turn.model_copy(update={"scene_edit": turn.scene_edit.model_copy(update={"scene_basis": "original"})})
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
        if dialogue is not None and scene is not None and not (turn.scene_edit and turn.scene_edit.scene_basis == "original"):
            turn = dialogue.apply_exclusions(turn, scene, aliases=self.aliases)
        turn = self.domain_policy.classify(turn, instruction)
        if turn.scene_edit is not None and turn.scene_edit.scene_basis == "original" and not original_requested:
            raise ValueError("original_scene_requires_explicit_request")
        if turn.status == TurnStatus.ACCEPTED and turn.turn_kind == TurnKind.ROBOT_TASK:
            turn = turn.model_copy(update={"task_intent": normalize_motion_language(turn.task_intent)})
        return turn

    def process_turn(self, request_id: str, turn: BrainTurn, scene: SceneConfig | None, *,
                     dialogue=None, bindings_override=None, edit_defaults=None,
                     capture: Callable[[], CameraFrame] | None = None,
                     held_object: SceneId | None = None,
                     robot_profile=None, robot_setup_revision=0, arm_states=None,
                     seen_scene_object_ids=None, next_scene_object_id=None) -> BrainResult:
        """Consume an understood turn without another provider call or normalization."""
        self.skill_planner.last_trace = None
        if turn.status != TurnStatus.ACCEPTED:
            return BrainResult(status=turn.status, turn_kind=turn.turn_kind)
        dual = robot_profile is not None and robot_profile.setup.mode == "dual"
        if not dual:
            turn.require_legacy_execution()
        elif turn.robot_setup_request is not None:
            request = turn.robot_setup_request
            if request.mode != "dual" or request.profile_id not in {None, robot_profile.setup.profile_id}:
                raise ValueError("robot_setup_switch_required")
        if turn.turn_kind == TurnKind.SESSION_CONTROL:
            return BrainResult(turn_kind=turn.turn_kind, session_action=turn.session_control)
        if scene is None:
            raise ValueError("scene_required")
        if turn.turn_kind == TurnKind.SCENE_EDIT:
            edited = self.scene_editor.edit_result(turn.scene_edit, scene, dialogue=dialogue, defaults=edit_defaults,
                                                  bindings_override=bindings_override,
                                                  seen_scene_object_ids=seen_scene_object_ids,
                                                  next_scene_object_id=next_scene_object_id)
            return BrainResult(turn_kind=turn.turn_kind, scene_patch=edited.patch,
                               focus_object_ids=edited.focus_object_ids or None,
                               deleted_object_ids=edited.deleted_object_ids)
        if turn.turn_kind == TurnKind.SCENE_QUERY:
            visual = turn.scene_query.evidence_source == "image"
            if visual and (self.vision_provider is None or capture is None):
                raise ValueError("query_visual_evidence_required")
            query = SceneQueryEngine(aliases=self.aliases, category_aliases=self.category_aliases, assets=self.assets,
                                    near_distance_m=self.query_near_distance_m).query(
                                        turn.scene_query.model_copy(update={"evidence_source": "scene"}), scene, dialogue)
            if visual:
                from .scene.component_access import SceneIndex
                from .contracts.task_intent import TaskEntity
                index, frame = SceneIndex(scene), capture()
                identifiers = set(query.object_ids)
                if query.reference_object_id is not None:
                    identifiers.add(query.reference_object_id)
                if not identifiers:
                    raise ValueError("query_visual_evidence_required: 无候选不能证明画面中没有物体")
                for oid in sorted(identifiers):
                    semantic = index.semantic(oid)
                    entity = TaskEntity(entity_id=semantic.semantic_name, semantic_name=semantic.semantic_name,
                                        category=semantic.category)
                    self.vision_fallback.resolve(entity, [index.object(oid)], scene, frame, self.vision_provider)
                query.evidence_source = "image_and_scene_geometry"
                query.reply = "已通过当前真实图像核对候选物体；以下关系依据同一快照的场景几何。" + (query.reply or str(query.names))
            return BrainResult(turn_kind=turn.turn_kind, scene_query_result=query, focus_object_ids=query.object_ids)
        intent = turn.task_intent
        if robot_profile is not None and not dual:
            if arm_states is None or not arm_states.arms["single"].state_known:
                raise ValueError("robot_runtime_state_unknown")
            if robot_profile.v2_robot is None:
                raise ValueError("robot_profile_v2_robot_missing")
            held_object = arm_states.arms["single"].holding_object
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
        if dual:
            from .planning.dual_arm_recipe_planner import DualArmRecipePlanner
            from .planning.arm_assignment_resolver import resolve_arms
            if arm_states is None:
                raise ValueError("robot_runtime_state_unknown")
            grounded = resolve_arms(grounded, robot_profile, arm_usage=intent.arm_usage)
            operations = grounded.operations
            if any(op.parallel_required for op in operations) and not robot_profile.coordinated_execution:
                raise ValueError("dual_coordinated_execution_not_registered")
            from .planning.skill_planner_router import PlanningTrace
            mode = "qwen" if self.skill_planner.mode == "qwen" else "recipe"
            trace = self.skill_planner.last_trace = PlanningTrace(self.skill_planner.mode, used_planner=mode)
            if mode == "qwen":
                from .planning.dual_qwen_planner import DualQwenPlanner
                commands = DualQwenPlanner().plan(request_id, grounded, scene, robot_profile,
                    robot_setup_revision, arm_states, self.skill_planner.provider, REGISTRY, trace)
            else:
                commands = DualArmRecipePlanner().plan(request_id, grounded, scene, robot_profile.setup,
                                                      robot_setup_revision, arm_states)
            from .planning.dual_capability import validate_dual_capability
            validate_dual_capability(commands, robot_profile)
            by_entity = {e.entity_id: e.scene_object_id for e in grounded.entities}
            return BrainResult(task_intent=intent, grounded_task=grounded, commands=commands,
                focus_object_ids=list(dict.fromkeys(by_entity[op.source or op.target] for op in operations)),
                planner_used=mode, planner_trace=trace.debug_payload())
        planning = self.skill_planner.plan(grounded, held_object=held_object, scene=scene)
        plan = planning.plan
        exporter = CommandExporter(robot=robot_profile.v2_robot) if robot_profile is not None else self.exporter
        commands = exporter.export(request_id, grounded, plan, scene, held_object=held_object)
        by_entity = {e.entity_id:e.scene_object_id for e in grounded.entities}
        focus = list(dict.fromkeys(by_entity[op.source or op.target] for op in grounded.operations))
        return BrainResult(task_intent=intent, grounded_task=grounded, skill_plan=plan, commands=commands,
                           focus_object_ids=focus, planner_used=planning.trace.used_planner,
                           planner_trace=planning.trace.debug_payload())

    def run(self, request_id: str, instruction: str, scene: SceneConfig, *,
            dialogue=None, capture: Callable[[], CameraFrame] | None = None,
            held_object: SceneId | None = None, bindings_override=None) -> BrainResult:
        turn = self.understand_turn(instruction, scene=scene, dialogue=dialogue)
        return self.process_turn(request_id, turn, scene, dialogue=dialogue, capture=capture,
                                 held_object=held_object, bindings_override=bindings_override)

    def run_turn(self, request_id, instruction, scene, **kwargs):
        return self.run(request_id, instruction, scene, **kwargs)
