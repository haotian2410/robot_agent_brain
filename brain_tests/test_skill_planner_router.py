import pytest

from robot_agent_brain.contracts.task_intent import Operation
from robot_agent_brain.errors import BrainError
from robot_agent_brain.models.skill_planning import SkillPlanLLMOutput
from robot_agent_brain.planning.plan_validator import PlanValidator
from robot_agent_brain.planning.recipe_planner import RecipePlanner
from robot_agent_brain.planning.skill_planner_router import SkillPlannerRouter
from robot_agent_brain.skills.registry import REGISTRY
from test_recipe_state import task
from test_skill_planning_context import placement_task
from test_skill_planning_qwen import raw_plan


class MockSkillPlanningProvider:
    def __init__(self, raw=None):
        self.raw = raw if raw is not None else raw_plan()
        self.requests = []

    def plan(self, request):
        self.requests.append(request)
        return SkillPlanLLMOutput.model_validate(self.raw)


def router(mode="qwen", provider=None):
    return SkillPlannerRouter(mode=mode, recipe_planner=RecipePlanner(),
                              model_provider=provider, registry=REGISTRY)


@pytest.mark.parametrize("mode,used,calls", [("recipe", "recipe", 0), ("auto", "recipe", 0), ("qwen", "qwen", 1)])
def test_router_modes(mode, used, calls):
    provider = MockSkillPlanningProvider()
    result = router(mode, provider).plan(placement_task())
    assert result.trace.used_planner == used and result.trace.model_calls == calls
    assert len(provider.requests) == calls
    assert result.trace.validation == {"valid": True}


def test_auto_unsupported_routes_only_by_supports(monkeypatch):
    provider = MockSkillPlanningProvider()
    planner = router("auto", provider)
    monkeypatch.setattr(planner.recipe, "supports", lambda task: False)
    assert planner.plan(placement_task()).trace.used_planner == "qwen"
    assert len(provider.requests) == 1


def test_auto_holding_conflict_never_calls_qwen():
    provider = MockSkillPlanningProvider()
    planner = router("auto", provider)
    with pytest.raises(BrainError) as error:
        planner.plan(placement_task(), held_object="b_01")
    assert error.value.issue.code == "holding_conflict"
    assert provider.requests == [] and planner.last_trace.model_calls == 0


@pytest.mark.parametrize("mode", ["recipe", "qwen", "auto"])
def test_search_cannot_invent_wire(mode):
    provider = MockSkillPlanningProvider()
    value = task([Operation(operation_id="op-1", task_type="search", target="a")])
    assert RecipePlanner.supports(value) is False
    with pytest.raises(BrainError) as error:
        router(mode, provider).plan(value)
    assert error.value.issue.code == "capability_unsupported" and not provider.requests


def test_missing_provider():
    with pytest.raises(BrainError) as error:
        router().plan(placement_task())
    assert error.value.issue.code == "skill_planning_provider_missing"


def test_repeated_locate_and_approach_are_valid():
    raw = raw_plan()
    steps = raw["operations"][0]["steps"]
    steps.insert(0, dict(steps[0]))
    steps.insert(3, dict(steps[2]))
    result = router(provider=MockSkillPlanningProvider(raw)).plan(placement_task())
    assert len(result.plan.steps) == 8
    assert [s.step_id for s in result.plan.steps] == [f"step-{i}" for i in range(1, 9)]


@pytest.mark.parametrize("mutation", ["no_approach", "release_unheld", "placement_swap", "extra_grasp", "external_entity"])
def test_state_transition_failures(mutation):
    value = placement_task()
    plan = RecipePlanner().plan(value)
    if mutation == "no_approach":
        plan.steps.pop(1)
    elif mutation == "release_unheld":
        plan.steps = [plan.steps[-1]]
    elif mutation == "placement_swap":
        plan.steps[-2].target_entity, plan.steps[-2].reference_entity = "a", "b"
    elif mutation == "extra_grasp":
        plan.steps.insert(3, plan.steps[2].model_copy(update={"step_id": "extra"}))
    else:
        plan.steps[0].target_entity = "external"
    with pytest.raises(ValueError):
        PlanValidator().validate(value, plan)


@pytest.mark.parametrize("kind,removed", [("press", "move"), ("open", "grasp")])
def test_press_and_pull_require_contact(kind, removed):
    value = task([Operation(operation_id="op-1", task_type=kind, target="a",
                            reference="b" if kind == "open" else None)])
    plan = RecipePlanner().plan(value)
    plan.steps = [s for s in plan.steps if s.skill_name != removed]
    with pytest.raises(ValueError):
        PlanValidator().validate(value, plan)


def test_initially_held_source_can_skip_pickup():
    raw = raw_plan()
    raw["operations"][0]["steps"] = raw["operations"][0]["steps"][3:]
    provider = MockSkillPlanningProvider(raw)
    result = router(provider=provider).plan(placement_task(), held_object="a_01")
    assert len(result.plan.steps) == 3
    assert provider.requests[0].context.initial_state.held_entity == "a"


def test_unrelated_holding_blocks_qwen_output_no_fallback():
    planner = router(provider=MockSkillPlanningProvider())
    with pytest.raises(BrainError) as error:
        planner.plan(placement_task(), held_object="b_01")
    assert error.value.issue.code == "holding_conflict"
    assert error.value.issue.stage == "skill_planning"
    assert planner.last_trace.used_planner == "qwen"
    assert planner.last_trace.validation["valid"] is False


def test_auto_qwen_failure_never_tries_recipe(monkeypatch):
    raw = raw_plan()
    raw["operations"][0]["steps"].pop(1)
    planner = router("auto", MockSkillPlanningProvider(raw))
    monkeypatch.setattr(planner.recipe, "supports", lambda task: False)
    def forbidden(*args, **kwargs):
        pytest.fail("No recipe fallback is allowed after Qwen failure")
    monkeypatch.setattr(planner.recipe, "plan", forbidden)
    with pytest.raises(BrainError) as error:
        planner.plan(placement_task())
    assert error.value.issue.code == "plan_precondition_failed"
    assert planner.last_trace.used_planner == "qwen"


@pytest.mark.parametrize("kind", ["locate", "move", "grasp", "release", "pick_and_place", "press", "open", "close"])
def test_supports_all_existing_executable_operations(kind):
    if kind == "pick_and_place":
        value = placement_task()
    else:
        from test_recipe_state import move
        op = move() if kind == "move" else Operation(operation_id="op-1", task_type=kind, target="a",
            reference="b" if kind in {"open", "close"} else None)
        value = task([op])
    assert RecipePlanner.supports(value) is True
