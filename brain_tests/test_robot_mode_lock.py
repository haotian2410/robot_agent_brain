import pytest
from robot_agent_brain.contracts.robot_mode_lock import RobotModeLock
from robot_agent_brain.contracts.robot_setup import RobotSetupRequest


def lock(mode="single"):
    return RobotModeLock(mode=mode, profile_id="fixture", source="scene", setup_revision=1)


@pytest.mark.parametrize("mode,route", [("single", "single_atomic"), ("dual", "dual_atomic")])
def test_first_acceptance_locks_and_roundtrips(mode, route):
    initial = lock(mode)
    accepted = initial.accept(1)
    assert not initial.locked
    assert accepted.prompt_route == route
    assert accepted.accept(2).locked_at_turn == 1
    assert RobotModeLock.model_validate_json(accepted.model_dump_json()) == accepted
    accepted.check_request(RobotSetupRequest(mode=mode, profile_id="fixture"))
    accepted.check_request(RobotSetupRequest(mode=mode))


@pytest.mark.parametrize("mode,other", [("single", "dual"), ("dual", "single")])
def test_later_mode_and_profile_changes_have_distinct_errors(mode, other):
    accepted = lock(mode).accept(1)
    with pytest.raises(ValueError, match="robot_mode_locked"):
        accepted.check_request(RobotSetupRequest(mode=other))
    with pytest.raises(ValueError, match="robot_setup_change_after_first_turn_unsupported"):
        accepted.check_request(RobotSetupRequest(mode=mode, profile_id="different"))


@pytest.mark.parametrize("updates", [
    {"locked": True}, {"locked_at_turn": 1}, {"profile_id": " "},
    {"locked": "false"}, {"setup_revision": -1},
])
def test_invalid_persisted_lock_is_rejected(updates):
    with pytest.raises(ValueError):
        RobotModeLock.model_validate({**lock().model_dump(), **updates})


def test_session_acceptance_locks_before_next_request():
    from test_dual_v4_pipeline import setup
    from test_dual_session_pipeline import task
    session = setup()
    assert session.robot_mode_lock is not None and not session.robot_mode_lock.locked
    result = session.process_turn("first", task("left"))
    assert result.commands.schema_version == "4.1"
    assert session.robot_mode_lock.locked
    assert session.robot_mode_lock.prompt_route == "dual_atomic"
    assert session.first_accepted_turn_id == "first"
    assert session.session_turn_index == 1
    assert result.planner_trace["robot_mode"] == {
        "mode": "dual", "profile_id": "fixture_only", "robot_setup_revision": 1,
        "prompt_route": "dual_atomic", "locked_at_turn": 1, "locked": True, "first_robot_mode_turn_id": "first"}


def test_session_lock_survives_store_and_next_left_only_task(tmp_path):
    from test_dual_v4_pipeline import setup
    from test_dual_session_pipeline import task
    from robot_agent_brain.session.store import SessionStore
    from robot_agent_brain.session.brain_session import BrainSession
    from robot_agent_brain.adapters.local_scene_platform import LocalScenePlatform
    session = setup()
    session.process_turn("first", task("left"))
    store = SessionStore(tmp_path)
    with store.lock("mode-test"):
        store.save("mode-test", session, revision=1)
        state = store.load("mode-test")
    restored = store.restore(state, BrainSession(None, session.pipeline, LocalScenePlatform(),
                                                robot_profiles=session.robot_profiles))
    assert restored.robot_mode_lock == session.robot_mode_lock
    result = restored.process_turn("second", task("left"))
    assert result.commands.schema_version == "4.1"
    assert {command.arm for command in result.commands.commands} == {"left"}
    assert restored.session_turn_index == 2
    assert restored.robot_mode_lock.locked_at_turn == 1
    assert restored.first_accepted_turn_id == "first"


@pytest.mark.parametrize("fault", ["profile", "revision", "turn", "first_id"])
def test_inconsistent_saved_mode_is_rejected(tmp_path, fault):
    from test_dual_v4_pipeline import setup
    from test_dual_session_pipeline import task
    from robot_agent_brain.session.store import SessionStore, SessionState
    session = setup()
    session.process_turn("first", task("left"))
    store = SessionStore(tmp_path)
    with store.lock("mode-test"):
        store.save("mode-test", session, revision=1)
        raw = store.load("mode-test").model_dump(mode="python")
    if fault == "profile":
        raw["robot_mode_lock"]["profile_id"] = "wrong"
    elif fault == "revision":
        raw["robot_mode_lock"]["setup_revision"] += 1
    elif fault == "turn":
        raw["session_turn_index"] = 0
    else:
        raw["first_robot_mode_turn_id"] = None
    with pytest.raises(ValueError, match="mode_lock"):
        SessionState.model_validate(raw)


def test_same_profile_setup_is_accepted_and_locks_without_resetting_runtime():
    from test_dual_v4_pipeline import setup
    from robot_agent_brain.contracts.turn import BrainTurn
    session = setup()
    before_scene = session.scene.raw_document()
    before_runtime = session.arm_states.model_dump()
    turn = BrainTurn(status="accepted", turn_kind="robot_config", instruction="使用当前双臂",
                     robot_setup_request={"mode": "dual", "profile_id": "fixture_only"})
    session.process_turn("setup-first", turn)
    assert session.robot_mode_lock.locked
    assert session.first_accepted_turn_id == "setup-first"
    assert session.robot_setup_revision == 1
    assert session.scene.raw_document() == before_scene
    assert session.arm_states.model_dump() == before_runtime
    session.process_turn("same-again", turn)
    assert session.robot_setup_revision == 1
    assert session.robot_mode_lock.locked_at_turn == 1
    turn.robot_setup_request = RobotSetupRequest(mode="single", profile_id="other")
    with pytest.raises(ValueError, match="robot_mode_locked"):
        session.check_turn(turn)
    assert session.session_turn_index == 2


def test_single_profile_left_wording_does_not_require_dual_contract():
    from test_robot_config_turns import session
    from robot_agent_brain.contracts.turn import BrainTurn
    from robot_agent_brain.models.task_understanding import TaskParseOutput
    current = session()
    current.process_turn("first", BrainTurn(status="accepted", turn_kind="robot_config",
        instruction="使用单臂", robot_setup_request={"mode": "single"}))
    turn = TaskParseOutput.model_validate({"entities": [{"id": "a", "name": "apple", "category": "fruit"}],
        "operations": [{"type": "grasp", "target": "a", "arm": "left"}]}).to_brain_turn("左臂抓苹果")
    result = current.process_turn("left-wording", turn)
    assert result.commands.schema_version == "2.0"
    assert result.planner_trace["robot_mode"]["prompt_route"] == "single_atomic"


def test_historical_exported_plan_restores_locked_mode(tmp_path):
    from test_dual_v4_pipeline import setup
    from test_dual_session_pipeline import task
    from robot_agent_brain.session.store import SessionStore, SessionState
    from robot_agent_brain.session.brain_session import BrainSession
    from robot_agent_brain.adapters.local_scene_platform import LocalScenePlatform
    session = setup()
    session.process_turn("historical-plan", task("left"))
    store = SessionStore(tmp_path)
    with store.lock("history"):
        store.save("history", session, revision=1)
        raw = store.load("history").model_dump(mode="python")
    for field in ("robot_mode_lock", "session_turn_index", "first_accepted_turn_id", "first_robot_mode_turn_id", "mode_lifecycle_version"):
        raw.pop(field)
    restored = store.restore(SessionState.model_validate(raw),
        BrainSession(None, session.pipeline, LocalScenePlatform(), robot_profiles=session.robot_profiles))
    assert restored.robot_mode_lock.locked
    assert restored.first_accepted_turn_id == "historical-plan"
    with pytest.raises(ValueError, match="robot_mode_locked"):
        restored.robot_mode_lock.check_request(RobotSetupRequest(mode="single"))


def test_historical_committed_edit_does_not_create_lock_without_robot_history(tmp_path):
    from test_dual_v4_pipeline import setup
    from robot_agent_brain.session.store import SessionStore, SessionState
    from robot_agent_brain.session.conversation_memory import ConversationTurn
    from robot_agent_brain.session.brain_session import BrainSession
    from robot_agent_brain.adapters.local_scene_platform import LocalScenePlatform
    current = setup()
    current.conversation_memory.recent_turns.append(ConversationTurn(
        turn_id="old-edit", session_id="history", sequence=1,
        raw_user_text="新增苹果", final_outcome="scene_updated", scene_commit_status="committed"))
    store = SessionStore(tmp_path)
    with store.lock("history"):
        store.save("history", current, revision=1)
        raw = store.load("history").model_dump(mode="python")
    for field in ("robot_mode_lock", "session_turn_index", "first_accepted_turn_id", "first_robot_mode_turn_id", "mode_lifecycle_version"):
        raw.pop(field)
    restored = store.restore(SessionState.model_validate(raw),
        BrainSession(None, current.pipeline, LocalScenePlatform(), robot_profiles=current.robot_profiles))
    assert restored.robot_mode_lock is None
    assert restored.first_robot_mode_turn_id is None
    assert not restored.exported_commands


def test_first_setup_uses_mode_boundary_under_published_policy():
    from test_robot_config_turns import session
    from robot_agent_brain.contracts.release_policy import ReleasePolicy
    from robot_agent_brain.contracts.turn import BrainTurn
    current = session()
    current.release_policy = ReleasePolicy()
    turn = BrainTurn(status="accepted", turn_kind="robot_config", instruction="首轮使用单臂",
                     robot_setup_request={"mode": "single"})
    current.process_turn("first-config", turn)
    assert current.robot_mode_lock.locked and current.robot_mode_lock.mode == "single"
    turn.robot_setup_request = RobotSetupRequest(mode="dual")
    with pytest.raises(ValueError, match="robot_mode_locked"):
        current.process_turn("later-switch", turn)


def test_empty_session_explicit_dual_initialization_records_first_turn_source():
    from test_dual_v4_pipeline import setup
    from test_dual_session_pipeline import task
    from robot_agent_brain.session.brain_session import BrainSession
    from robot_agent_brain.adapters.local_scene_platform import LocalScenePlatform
    template = setup()
    fresh = BrainSession(None, template.pipeline, LocalScenePlatform(), robot_profiles=template.robot_profiles)
    turn = task("left")
    turn.robot_setup_request = RobotSetupRequest(mode="dual", profile_id="fixture_only")
    result = fresh.process_initial_robot_turn("initial-dual", turn, template.scene,
        bindings_override={}, profile=template.robot_profiles.profiles["fixture_only"])
    assert result.commands.schema_version == "4.1"
    assert fresh.robot_mode_lock.source == "first_turn"
    assert fresh.robot_mode_lock.locked
    assert fresh.first_accepted_turn_id == "initial-dual"


def test_initial_planning_failure_keeps_mode_selection_available():
    from test_dual_v4_pipeline import setup
    from test_dual_session_pipeline import task
    from robot_agent_brain.session.brain_session import BrainSession
    from robot_agent_brain.adapters.local_scene_platform import LocalScenePlatform
    template = setup()
    fresh = BrainSession(None, template.pipeline, LocalScenePlatform(), robot_profiles=template.robot_profiles)
    turn = task("left")
    turn.robot_setup_request = RobotSetupRequest(mode="dual", profile_id="fixture_only")
    recipe = template.pipeline.dual_skill_recipe
    template.pipeline.dual_skill_recipe = lambda request: {"operations": []}
    with pytest.raises(ValueError):
        fresh.process_initial_robot_turn("failed-init", turn, template.scene,
            bindings_override={}, profile=template.robot_profiles.profiles["fixture_only"])
    assert fresh.scene is None
    assert fresh.robot_mode_lock is None
    assert fresh.first_accepted_turn_id is None
    assert fresh.session_turn_index == 0
    assert not fresh.exported_commands
    template.pipeline.dual_skill_recipe = recipe
    result = fresh.process_initial_robot_turn("retry-init", turn, template.scene,
        bindings_override={}, profile=template.robot_profiles.profiles["fixture_only"])
    assert result.commands.schema_version == "4.1"
    assert fresh.first_accepted_turn_id == "retry-init"


def test_profile_rejects_conflicting_scene_setup_mode_before_object_lookup():
    from test_dual_v4_pipeline import setup
    from robot_agent_brain.contracts.robot_setup import RobotSetup
    current = setup()
    profile = current.robot_profiles.profiles["fixture_only"]
    single = RobotSetup(mode="single", profile_id="other",
        arms={"single": profile.setup.arms["left"]})
    with pytest.raises(ValueError, match="robot_profile_scene_mode_mismatch"):
        profile.validate_scene(current.scene, single)


def test_empty_session_explicit_single_initialization_uses_atomic_prompt():
    from test_robot_config_turns import session
    from robot_agent_brain.session.brain_session import BrainSession
    from robot_agent_brain.adapters.local_scene_platform import LocalScenePlatform
    from robot_agent_brain.models.task_understanding import TaskParseOutput
    configured = session()
    profile = configured.robot_profiles.resolve(RobotSetupRequest(mode="single"))
    fresh = BrainSession(None, configured.pipeline, LocalScenePlatform(),
                         robot_profiles=configured.robot_profiles)
    turn = TaskParseOutput.model_validate({"robot_setup_request": {"mode": "single", "profile_id": profile.setup.profile_id},
        "entities": [{"id": "apple", "name": "apple", "category": "fruit"}],
        "operations": [{"type": "grasp", "target": "apple"}]}).to_brain_turn("首轮使用单臂抓苹果")
    result = fresh.process_initial_robot_turn("single-init", turn, profile.template,
        bindings_override={}, profile=profile)
    assert result.commands.schema_version == "2.0"
    assert fresh.robot_mode_lock.mode == "single"
    assert fresh.robot_mode_lock.source == "first_turn"
    assert result.planner_trace["robot_mode"]["prompt_route"] == "single_atomic"


def test_initial_profile_cannot_override_explicit_requested_mode():
    from test_robot_config_turns import session
    from test_dual_session_pipeline import task
    from robot_agent_brain.session.brain_session import BrainSession
    from robot_agent_brain.adapters.local_scene_platform import LocalScenePlatform
    configured = session()
    fresh = BrainSession(None, configured.pipeline, LocalScenePlatform(), robot_profiles=configured.robot_profiles)
    turn = task()
    turn.robot_setup_request = RobotSetupRequest(mode="single")
    wrong = configured.robot_profiles.profiles["fixture_only"]
    with pytest.raises(ValueError, match="robot_setup_profile_mode_mismatch"):
        fresh.process_initial_robot_turn("wrong", turn, configured.scene,
            bindings_override={}, profile=wrong)
    assert fresh.scene is None and fresh.robot_mode_lock is None


def test_default_single_without_profile_locks_and_persists(tmp_path):
    from test_composite_scene_robot import session_and_task
    from robot_agent_brain.session.store import SessionStore
    from robot_agent_brain.session.brain_session import BrainSession
    from robot_agent_brain.adapters.local_scene_platform import LocalScenePlatform
    current, task = session_and_task()
    current.process_composite_turn("default", task)
    assert current.robot_setup is None
    assert current.robot_mode_lock.mode == "single"
    assert current.robot_mode_lock.profile_id == "default_single"
    assert current.robot_mode_lock.locked
    store = SessionStore(tmp_path)
    with store.lock("default"):
        store.save("default", current, revision=1)
        restored = store.restore(store.load("default"), BrainSession(None, current.pipeline, LocalScenePlatform()))
    restored.robot_mode_lock.check_setup(None, restored.robot_setup_revision)
    turn = task.phases[-1].model_copy(update={"robot_setup_request": RobotSetupRequest(mode="dual")})
    with pytest.raises(ValueError, match="robot_mode_locked"):
        restored.check_turn(turn)
    from robot_agent_brain.session.store import SessionState
    raw = store.load("default").model_dump(mode="python")
    for field in ("robot_mode_lock", "session_turn_index", "first_accepted_turn_id", "first_robot_mode_turn_id", "mode_lifecycle_version"):
        raw.pop(field)
    historical = store.restore(SessionState.model_validate(raw),
        BrainSession(None, current.pipeline, LocalScenePlatform()))
    assert historical.robot_setup is None
    assert historical.robot_mode_lock.locked
    assert historical.robot_mode_lock.mode == "single"
    left_turn = task.phases[-1].model_copy(deep=True)
    left_turn.task_intent.operations[0].arm = "left"
    planned = restored.process_turn("left-default", left_turn)
    assert planned.commands.schema_version == "2.0"
    assert planned.planner_trace["robot_mode"]["prompt_route"] == "single_atomic"
