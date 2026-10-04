from __future__ import annotations

from pydantic import BaseModel, ConfigDict, model_validator

from .contracts.commands import CommandsFile
from .contracts.grounded_task import GroundedTask
from .contracts.scene import SceneConfig
from .contracts.skill_plan import SkillPlan
from .contracts.task_intent import TaskIntent
from .contracts.turn import BrainTurn, TurnKind
from .scene.query import SceneQueryEngine, SceneQueryResult
from .scene.editor import SceneEditor
from .grounding.scene_grounder import SceneGrounder
from .models.task_understanding import TaskUnderstandingProvider, TaskUnderstandingRequest, normalize_motion_language
from .planning.command_exporter import CommandExporter
from .planning.motion_scale import MotionScaleResolver
from .planning.recipe_planner import RecipePlanner
from .planning.task_expander import TaskExpander
from .ports.asset_catalog import AssetCatalogPort


class BrainResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    turn_kind: TurnKind = TurnKind.ROBOT_TASK
    intent: TaskIntent | None = None
    grounded_task: GroundedTask | None = None
    skill_plan: SkillPlan | None = None
    commands: CommandsFile | None = None
    scene_patch: object | None = None
    scene_query_result: SceneQueryResult | None = None
    session_action: object | None = None

    @model_validator(mode="after")
    def turn_payload(self):
        expected = {
            TurnKind.ROBOT_TASK: (self.intent, self.grounded_task, self.skill_plan, self.commands),
            TurnKind.SCENE_EDIT: (self.scene_patch,),
            TurnKind.SCENE_QUERY: (self.scene_query_result,),
            TurnKind.SESSION_CONTROL: (self.session_action,),
        }
        if self.turn_kind in expected and not all(item is not None for item in expected[self.turn_kind]):
            raise ValueError("brain_result_payload_missing")
        return self


class BrainPipeline:
    def __init__(self, understanding: TaskUnderstandingProvider, assets: AssetCatalogPort, scene_editor: SceneEditor | None = None):
        self.understanding = understanding
        self.grounder = SceneGrounder()
        self.motion = MotionScaleResolver(assets)
        self.planner = RecipePlanner()
        self.expander = TaskExpander()
        self.scene_editor = scene_editor or SceneEditor(assets)
        self.exporter = CommandExporter()

    def run(self, request_id: str, instruction: str, scene: SceneConfig) -> BrainResult:
        intent = self.understanding.understand(TaskUnderstandingRequest(instruction=instruction))
        return self._execute_intent(request_id, instruction, scene, intent)

    def _execute_intent(self, request_id: str, instruction: str, scene: SceneConfig, intent: TaskIntent) -> BrainResult:
        if intent.instruction != instruction:
            intent = intent.model_copy(update={"instruction": instruction})
        intent = normalize_motion_language(intent)
        grounded = self.grounder.ground(intent, scene)
        grounded = self.expander.expand(grounded, scene)
        grounded = self.motion.resolve(grounded)
        plan = self.planner.plan(grounded)
        commands = self.exporter.export(request_id, grounded, plan, scene)
        return BrainResult(intent=intent, grounded_task=grounded, skill_plan=plan, commands=commands)

    def run_turn(self, request_id: str, instruction: str, scene: SceneConfig) -> BrainResult:
        provider = self.understanding
        if not hasattr(provider, "understand_turn"):
            return self.run(request_id, instruction, scene)
        turn: BrainTurn = provider.understand_turn(TaskUnderstandingRequest(instruction=instruction))
        if turn.turn_kind == TurnKind.ROBOT_TASK:
            return self._execute_intent(request_id, instruction, scene, turn.task_intent)
        if turn.turn_kind == TurnKind.SCENE_QUERY:
            return BrainResult(turn_kind=turn.turn_kind, scene_query_result=SceneQueryEngine().query(turn.scene_query, scene))
        if turn.turn_kind == TurnKind.SESSION_CONTROL:
            return BrainResult(turn_kind=turn.turn_kind, session_action=turn.session_control)
        if turn.turn_kind == TurnKind.SCENE_EDIT:
            reference = None
            if turn.scene_edit.reference:
                reference = next((item for item in scene.objects if item.scene_object_id == turn.scene_edit.reference or item.semantic_name.casefold() == turn.scene_edit.reference.casefold()), None)
                if reference is None:
                    raise ValueError("scene_edit_reference_missing")
            from .contracts.task_intent import PlacementTarget
            relation = PlacementTarget(kind="relative_object", reference=turn.scene_edit.reference, relation=turn.scene_edit.relation) if turn.scene_edit.reference and turn.scene_edit.relation else None
            from .contracts.scene import PatchAction, ScenePatch, ScenePatchOperation
            if turn.scene_edit.operation == "add":
                patch_ops = []
                for index in range(1, turn.scene_edit.count + 1):
                    object_id = f"{turn.scene_edit.semantic_name}_{index:02d}"
                    patch_ops.extend(self.scene_editor.add_object(scene, object_id, turn.scene_edit.semantic_name, turn.scene_edit.semantic_name, turn.scene_edit.category, relation=relation, reference_object=reference).operations)
                patch = ScenePatch(scene_id=scene.scene_id, base_scene_version=scene.scene_version, operations=patch_ops)
            else:
                matches = [item for item in scene.objects if item.semantic_name.casefold() == turn.scene_edit.semantic_name.casefold()]
                if not matches:
                    raise ValueError("scene_edit_object_missing")
                if turn.scene_edit.operation == "remove":
                    patch = ScenePatch(scene_id=scene.scene_id, base_scene_version=scene.scene_version, operations=[ScenePatchOperation(action=PatchAction.REMOVE, scene_object_id=item.scene_object_id) for item in matches[:turn.scene_edit.count]])
                else:
                    if relation is None or reference is None:
                        raise ValueError("scene_edit_relation_missing")
                    model = self.scene_editor.assets.get_model_property(matches[0].asset_id)
                    ref_model = self.scene_editor.assets.get_model_property(reference.asset_id)
                    transform = self.scene_editor.layout.relative_transform(relation.relation, reference.transform, ref_model, model)
                    patch = ScenePatch(scene_id=scene.scene_id, base_scene_version=scene.scene_version, operations=[ScenePatchOperation(action=PatchAction.UPDATE_TRANSFORM, scene_object_id=item.scene_object_id, transform=transform) for item in matches[:turn.scene_edit.count]])
            return BrainResult(turn_kind=turn.turn_kind, scene_patch=patch)
        raise ValueError("scene_edit requires BrainSession and SceneEditor")
