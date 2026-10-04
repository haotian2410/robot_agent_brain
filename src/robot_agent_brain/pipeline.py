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
        self.grounder = SceneGrounder()
        self.motion = MotionScaleResolver(assets)
        self.planner = RecipePlanner()
        self.expander = TaskExpander()
        self.scene_editor = scene_editor or SceneEditor(assets)
        self.exporter = CommandExporter()
        self.vision_provider = vision_provider
        self.vision_fallback = VisionFallbackGrounder()

    def run(self, request_id: str, instruction: str, scene: SceneConfig, *,
            dialogue=None, capture: Callable[[], CameraFrame] | None = None) -> BrainResult:
        provider_instruction = dialogue.contextualize(instruction, scene) if dialogue else instruction
        request = TaskUnderstandingRequest(instruction=provider_instruction)
        if hasattr(self.understanding, "understand_turn"):
            turn = self.understanding.understand_turn(request)
        else:
            intent = self.understanding.understand(request)
            turn = BrainTurn(status="accepted", turn_kind="robot_task", instruction=instruction, task_intent=intent)
        if turn.status != TurnStatus.ACCEPTED:
            return BrainResult(status=turn.status, turn_kind=turn.turn_kind)
        if turn.turn_kind == TurnKind.SCENE_EDIT:
            return BrainResult(turn_kind=turn.turn_kind, scene_patch=self.scene_editor.edit(turn.scene_edit, scene))
        if turn.turn_kind == TurnKind.SCENE_QUERY:
            return BrainResult(turn_kind=turn.turn_kind, scene_query_result=SceneQueryEngine().query(turn.scene_query, scene))
        if turn.turn_kind == TurnKind.SESSION_CONTROL:
            return BrainResult(turn_kind=turn.turn_kind, session_action=turn.session_control)
        intent = turn.task_intent.model_copy(update={"instruction": instruction})
        intent = normalize_motion_language(intent)
        overrides = dialogue.bindings(intent, scene) if dialogue else {}
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
        plan = self.planner.plan(grounded)
        commands = self.exporter.export(request_id, grounded, plan, scene)
        return BrainResult(task_intent=intent, grounded_task=grounded, skill_plan=plan, commands=commands)

    def run_turn(self, request_id, instruction, scene, **kwargs):
        return self.run(request_id, instruction, scene, **kwargs)
