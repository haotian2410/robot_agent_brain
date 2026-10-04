from typing import Protocol
from ..contracts.grounded_task import GroundedTask
from ..contracts.skill_plan import SkillPlan


class SkillPlanningProvider(Protocol):
    def plan(self, task: GroundedTask) -> SkillPlan: ...

