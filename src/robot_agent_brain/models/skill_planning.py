from typing import Literal, Protocol
from pydantic import BaseModel, ConfigDict, Field, model_validator
from ..contracts.grounded_task import GroundedTask
from ..contracts.skill_plan import SkillName, SkillPlan, SkillStep
from ..planning.context_builder import PlannerContext, operation_valid_roles
from ..errors import BrainError


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class LLMPlanStep(StrictModel):
    skill: SkillName
    target_role: Literal["source", "destination", "target", "reference"] | None = None
    reference_role: Literal["source", "destination", "target", "reference"] | None = None
    region: str | None = None


class LLMOperationPlan(StrictModel):
    id: str
    intent: str = Field(min_length=1, max_length=300)
    steps: list[LLMPlanStep] = Field(min_length=1)


class SkillPlanLLMOutput(StrictModel):
    operations: list[LLMOperationPlan]

    @model_validator(mode="after")
    def unique_operations(self):
        ids = [op.id for op in self.operations]
        if len(set(ids)) != len(ids):
            raise ValueError("duplicate operation id")
        return self


class SkillPlanningRequest(StrictModel):
    context: PlannerContext
    skill_catalog: str


class SkillPlanningProvider(Protocol):
    def plan(self, request: SkillPlanningRequest) -> SkillPlanLLMOutput: ...


def enrich_skill_plan(raw: SkillPlanLLMOutput, task: GroundedTask, registry) -> SkillPlan:
    if [op.id for op in raw.operations] != [op.operation_id for op in task.operations]:
        raise BrainError("planner_operation_order_mismatch", "skill_planning", "Operation IDs/order must match exactly")
    steps = []
    for output, operation in zip(raw.operations, task.operations):
        valid = operation_valid_roles(operation)
        for step in output.steps:
            definition = registry.require(step.skill)
            if not definition.planner_visible:
                raise BrainError("planner_unknown_skill", "skill_planning", str(step.skill))
            if (definition.requires_target and step.target_role is None) or any(role is not None and role not in valid for role in (step.target_role, step.reference_role)):
                raise BrainError("planner_role_invalid", "skill_planning", f"{operation.operation_id}: valid_roles={valid}")
            if step.region is not None and step.region not in definition.allowed_regions:
                raise BrainError("planner_region_invalid", "skill_planning", str(step.region))
            steps.append(SkillStep(step_id=f"step-{len(steps)+1}", operation_id=operation.operation_id,
                skill_name=step.skill, target_entity=getattr(operation, step.target_role) if step.target_role else None,
                reference_entity=getattr(operation, step.reference_role) if step.reference_role else None, region=step.region))
    return SkillPlan(steps=steps)
