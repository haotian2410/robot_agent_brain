"""Semantic-only second-stage model boundary for coordinated skills."""
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator
from .skill_planning import LLMPlanStep


class DualLLMAction(LLMPlanStep):
    operation_id: str
    skill: Literal["locate", "move", "grasp", "release"]


class DualLLMStage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    left: DualLLMAction | None
    right: DualLLMAction | None

    @model_validator(mode="after")
    def nonempty(self):
        if self.left is None and self.right is None:
            raise ValueError("dual_stage_empty")
        return self


class DualSkillPlanOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    stages: list[DualLLMStage] = Field(min_length=1, max_length=200)


class DualSkillPlanningRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    context: dict
    skill_catalog: str


def dual_context(task, runtime):
    from ..planning.context_builder import build_planner_context
    context = build_planner_context(task).model_dump(mode="json")
    context.pop("initial_state")
    context["hold_constraints"] = [hold.model_dump(mode="json", exclude_none=True) for hold in task.hold_constraints]
    by_object = {e.scene_object_id: e.entity_id for e in task.entities}
    context["arms"] = {side: {"state_known": a.state_known,
                               "gripper_occupied": a.holding_object is not None,
                               "held_entity": by_object.get(a.holding_object)} for side, a in runtime.arms.items()}
    held = {side: arm.holding_object for side, arm in runtime.arms.items()}
    bindings = {e.entity_id: e.scene_object_id for e in task.entities}
    for row, op in zip(context["operations"], task.operations):
        row.update(arm=op.arm, parallel_group=op.parallel_group, parallel_required=op.parallel_required)
        actor = op.source or op.target
        initial = held[op.arm]
        row["initially_holds_actor"] = initial is not None and initial == bindings[actor]
        if op.task_type == "grasp":
            held[op.arm] = bindings[actor]
            row["required_final_gripper"] = "holding_actor"
        elif op.task_type in {"release", "pick_and_place"} or op.task_type == "move" and initial is None:
            held[op.arm] = None
            row["required_final_gripper"] = "empty"
        else:
            row["required_final_gripper"] = "unchanged"
    return context
