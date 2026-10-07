from dataclasses import dataclass
from pydantic import ValidationError
from ..errors import BrainError
from ..models.qwen_http import QwenProviderError
from ..models.skill_planning import SkillPlanningRequest, SkillPlanLLMOutput, enrich_skill_plan
from ..contracts.skill_plan import SkillPlan
from .context_builder import PlannerContext, build_planner_context
from .plan_validator import PlanValidator


@dataclass
class PlanningTrace:
    requested_mode: str
    used_planner: str | None = None
    context: PlannerContext | None = None
    skill_catalog: str | None = None
    raw_output: object = None
    normalized: SkillPlan | None = None
    validation: dict | None = None
    model_calls: int = 0

    def debug_payload(self):
        result = {}
        for key, value in (("planner_context", self.context), ("planner_skill_catalog", self.skill_catalog),
                           ("raw_skill_plan", self.raw_output), ("normalized_skill_plan", self.normalized),
                           ("skill_plan_validation", self.validation)):
            if value is not None:
                result[key] = value.model_dump(mode="json") if hasattr(value, "model_dump") else value
        return result


@dataclass
class SkillPlanningResult:
    plan: SkillPlan
    trace: PlanningTrace


class SkillPlannerRouter:
    def __init__(self, *, mode, recipe_planner, model_provider, registry):
        if mode not in {"recipe", "qwen", "auto"}:
            raise ValueError("planner_mode_invalid")
        self.mode, self.recipe, self.provider, self.registry = mode, recipe_planner, model_provider, registry
        self.last_trace = None

    def plan(self, task, *, held_object=None, scene=None):
        trace = self.last_trace = PlanningTrace(self.mode)
        try:
            # Search has no registered wire skill. Never ask a model to invent one.
            if any(op.task_type == "search" for op in task.operations):
                raise BrainError("capability_unsupported", "skill_planning", "Search wire is not registered")
            supported = self.recipe.supports(task)
            if self.mode == "recipe" or self.mode == "auto" and supported:
                trace.used_planner = "recipe"
                if not supported:
                    raise BrainError("capability_unsupported", "skill_planning", "No deterministic recipe for task")
                plan = self.recipe.plan(task, held_object=held_object)
            else:
                trace.used_planner = "qwen"
                if self.provider is None:
                    raise BrainError("skill_planning_provider_missing", "skill_planning", "Provider has no planning interface")
                trace.context = build_planner_context(task, held_object)
                trace.skill_catalog = self.registry.prompt_catalog()
                trace.model_calls = 1
                raw = self.provider.plan(SkillPlanningRequest(context=trace.context, skill_catalog=trace.skill_catalog))
                trace.raw_output = getattr(self.provider, "last_raw_values", {}).get("skill_planning", raw)
                raw = SkillPlanLLMOutput.model_validate(raw.model_dump() if hasattr(raw, "model_dump") else raw)
                plan = enrich_skill_plan(raw, task, self.registry)
            trace.normalized = plan
            PlanValidator().validate(task, plan, scene, held_object=held_object)
            trace.validation = {"valid": True}
            return SkillPlanningResult(plan, trace)
        except Exception as exc:
            trace.validation = {"valid": False, "error": str(exc)}
            if isinstance(exc, BrainError):
                raise
            if isinstance(exc, QwenProviderError):
                code = exc.code if exc.code != "provider_error" else "skill_planning_failed"
            elif isinstance(exc, ValidationError):
                code = "planner_unknown_skill" if any(e["loc"][-1:] == ("skill",) and e["type"] == "enum" for e in exc.errors()) else "skill_plan_output_invalid"
            elif isinstance(exc, ValueError):
                code = str(exc).split(":", 1)[0]
            else:
                code = "skill_planning_failed"
            raise BrainError(code, "skill_planning", str(exc)) from exc
