from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from .contracts.commands import CommandsFile
from .contracts.grounded_task import GroundedTask
from .contracts.scene import SceneConfig
from .contracts.skill_plan import SkillPlan
from .contracts.task_intent import TaskIntent
from .grounding.scene_grounder import SceneGrounder
from .models.task_understanding import TaskUnderstandingProvider, TaskUnderstandingRequest, normalize_motion_language
from .planning.command_exporter import CommandExporter
from .planning.motion_scale import MotionScaleResolver
from .planning.recipe_planner import RecipePlanner
from .ports.asset_catalog import AssetCatalogPort


class BrainResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    intent: TaskIntent
    grounded_task: GroundedTask
    skill_plan: SkillPlan
    commands: CommandsFile


class BrainPipeline:
    def __init__(self, understanding: TaskUnderstandingProvider, assets: AssetCatalogPort):
        self.understanding = understanding
        self.grounder = SceneGrounder()
        self.motion = MotionScaleResolver(assets)
        self.planner = RecipePlanner()
        self.exporter = CommandExporter()

    def run(self, request_id: str, instruction: str, scene: SceneConfig) -> BrainResult:
        intent = self.understanding.understand(TaskUnderstandingRequest(instruction=instruction))
        if intent.instruction != instruction:
            intent = intent.model_copy(update={"instruction": instruction})
        intent = normalize_motion_language(intent)
        grounded = self.grounder.ground(intent, scene)
        grounded = self.motion.resolve(grounded)
        plan = self.planner.plan(grounded)
        commands = self.exporter.export(request_id, grounded, plan, scene)
        return BrainResult(intent=intent, grounded_task=grounded, skill_plan=plan, commands=commands)

