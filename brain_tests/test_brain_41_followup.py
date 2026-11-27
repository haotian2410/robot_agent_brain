"""B1–B6 regression matrix. Fixture profiles never authorize production Control."""
import copy
import math
import pytest
from robot_agent_brain.contracts.turn import BrainTurn
from robot_agent_brain.contracts.robot_setup import RobotSetupRequest
from robot_agent_brain.contracts.robot_profile import RobotProfileRegistry
from robot_agent_brain.contracts.commands_sequence_v41 import CommandsFileV41, canonical_commands_v41
from robot_agent_brain.session.store import SessionStore, SessionState
from robot_agent_brain.session.brain_session import BrainSession
from robot_agent_brain.adapters.local_scene_platform import LocalScenePlatform
from robot_agent_brain.web.protocol import digest
from test_dual_v4_pipeline import setup
from test_dual_session_pipeline import task
from test_robot_setup_manager import single_profile
from test_commands_sequence_v41 import payload


def query():
    return BrainTurn(status="accepted", turn_kind="scene_query", instruction="几个苹果", scene_query={
        "query_type": "count", "target": "apple", "entities": [
            {"entity_id": "apple", "semantic_name": "apple", "category": "fruit"}]})


def selectable():
    current = setup()
    from robot_agent_brain.contracts.robot_setup import RobotRuntimeState
    single = single_profile().model_copy(update={"v2_robot": "fixture_single_control", "initial_state": RobotRuntimeState.model_validate({
        "arms": {"single": {"state_known": True}}})})
    # Validate the fixture declaration rather than forge its runtime state.
    from robot_agent_brain.contracts.robot_profile import RobotProfile
    single = RobotProfile.model_validate(single.model_dump())
    values = current.robot_profiles.model_dump()
    values["profiles"][single.setup.profile_id] = single.model_dump()
    values["default_single"] = single.setup.profile_id
    current.robot_profiles = RobotProfileRegistry.model_validate(values)
    current.switch_robot_setup(single, platform_bindings={})
    return current


def restore(tmp_path, current):
    store = SessionStore(tmp_path)
    with store.lock("matrix"):
        store.save("matrix", current, revision=1)
        state = store.load("matrix")
    return store.restore(state, BrainSession(None, current.pipeline, LocalScenePlatform(), robot_profiles=current.robot_profiles))


def test_M01_query_save_restore_does_not_select_mode(tmp_path):
    current = setup()
    current.process_turn("query", query())
    assert current.robot_mode_lock is not None and not current.robot_mode_lock.locked
    assert current.first_robot_mode_turn_id is None
    resumed = restore(tmp_path, current)
    assert not resumed.robot_mode_lock.locked
    assert resumed.first_accepted_turn_id == "query"
    assert not resumed.exported_commands and not resumed.dispatched_requests


def test_M02_M03_layout_then_explicit_dual_setup_preserves_objects():
    from test_dual_layout_composite_sequence import prepared
    current, composite = prepared()
    current = selectable_with_scene(current)
    current.process_turn("layout", composite.phases[0])
    members = copy.deepcopy(current.arrangement_index.snapshot())
    before = {obj.object_id_in_scene: obj for obj in current.scene.objects
              if obj.object_id_in_scene not in current.platform_object_ids}
    assert not current.robot_mode_lock.locked
    result = current.process_turn("setup", BrainTurn(status="accepted", turn_kind="robot_config",
        instruction="选择双臂", robot_setup_request={"mode": "dual"}))
    assert result.robot_setup_changed.mode == "dual"
    assert current.robot_mode_lock.locked and current.first_robot_mode_turn_id == "setup"
    assert members == current.arrangement_index.snapshot()
    assert all(next(o for o in current.scene.objects if o.object_id_in_scene == key) == obj for key, obj in before.items())
    assert not current.exported_commands and not current.dispatched_requests


def selectable_with_scene(current):
    reference = selectable()
    current.robot_profiles = reference.robot_profiles
    current.switch_robot_setup(reference.robot_profiles.resolve(RobotSetupRequest(mode="single")), platform_bindings={})
    return current


def test_M04_M05_nonrobot_prefix_then_robot_decides_actual_mode():
    current = selectable()
    current.process_turn("query", query())
    turn = task("left").model_copy(update={"robot_setup_request": RobotSetupRequest(mode="dual")})
    result = current.process_turn("dual-plan", turn)
    assert result.commands.schema_version == "4.1"
    assert current.first_robot_mode_turn_id == "dual-plan"
    assert current.robot_mode_lock.locked_at_turn == 2
    assert not current.dispatched_requests
    single = selectable()
    single.process_turn("query", query())
    result = single.process_turn("single-plan", task(None))
    assert result.commands.schema_version == "2.0"
    assert single.robot_mode_lock.mode == "single" and single.robot_mode_lock.locked


def test_M07_first_robot_failure_keeps_candidate_unlocked():
    current = selectable()
    current.process_turn("query", query())
    before = digest(current.scene)
    turn = task("left").model_copy(deep=True)
    turn.task_intent.entities[0].semantic_name = "absent"
    turn.robot_setup_request = RobotSetupRequest(mode="dual")
    with pytest.raises(ValueError):
        current.process_turn("failed", turn)
    assert digest(current.scene) == before and not current.robot_mode_lock.locked
    assert current.first_robot_mode_turn_id is None and not current.exported_commands


def test_M08_M15_locked_rebind_and_direct_import_are_fenced():
    current = setup()
    current.process_turn("robot", task("left"))
    before = digest(current.scene)
    with pytest.raises(ValueError, match="robot_mode_locked"):
        current.accept_browser_scene(current.scene, platform_object_ids=current.platform_object_ids, change_kind="platform_rebind")
    with pytest.raises(ValueError, match="robot_mode_locked"):
        current.initialize_scene(current.scene)
    assert digest(current.scene) == before


def test_M13_old_mislock_only_removed_with_complete_nonrobot_history(tmp_path):
    from robot_agent_brain.session.conversation_memory import ConversationTurn
    current = setup()
    current.process_turn("query", query())
    current.conversation_memory.recent_turns.append(ConversationTurn(turn_id="query", session_id="matrix",
        sequence=1, raw_user_text="几个苹果", final_outcome="answered"))
    store = SessionStore(tmp_path)
    store.save("matrix", current, revision=1)
    raw = store.load("matrix").model_dump(mode="python")
    raw.pop("mode_lifecycle_version")
    raw["robot_mode_lock"].update(locked=True, locked_at_turn=1)
    migrated = SessionState.model_validate(raw)
    assert not migrated.robot_mode_lock.locked
    assert "mode_migration_nonrobot_mislock_removed" in migrated.mode_migration_diagnostics
    assert SessionState.model_validate(migrated.model_dump()) == migrated
    raw["conversation_memory"]["archived_turn_ids"] = ["missing-history"]
    conservative = SessionState.model_validate(raw)
    assert conservative.robot_mode_lock.locked
    assert "mode_migration_history_incomplete_lock_preserved" in conservative.mode_migration_diagnostics


def test_M14_original_with_different_assembly_rejected_before_write(tmp_path):
    from robot_agent_brain.session.original_scene_store import OriginalSceneStore
    current = selectable()
    store = OriginalSceneStore(tmp_path)
    current.original_scene_manifest = store.capture_once(current.scene, platform_object_ids=current.platform_object_ids,
        request_id="original", source="uploaded", robot_setup=current.robot_setup, profile_object_map=current.profile_object_map)
    current.process_turn("dual", task("left").model_copy(update={"robot_setup_request": RobotSetupRequest(mode="dual")}))
    before = digest(current.scene)
    with pytest.raises(ValueError, match="assembly_merge_unsupported"):
        current.derive_original_scene(store, lambda scene: scene, reset_allowed=True)
    assert digest(current.scene) == before and current.robot_mode_lock.mode == "dual"


@pytest.mark.parametrize("field,value", [("scene_id", True), ("scene_version", 1.0), ("robot_setup_revision", False),
    ("scene_digest", "not-a-digest"), ("scene_digest", "A"*64), ("schema_version", None)])
def test_C01_strict_identity_and_required_version(field, value):
    data = payload()
    if value is None:
        data.pop(field)
    else:
        data[field] = value
    with pytest.raises(ValueError):
        CommandsFileV41.model_validate(data)


@pytest.mark.parametrize("bad", [math.nan, math.inf, -math.inf, {1: "bad-key"}, (1, 2), {1, 2}])
def test_C01_parameters_are_lossless_standard_json(bad):
    data = payload()
    data["commands"][0]["parameters"] = {"nested": [bad]}
    with pytest.raises(ValueError):
        CommandsFileV41.model_validate(data)


def test_C01_canonicalization_does_not_hide_mutated_nan():
    value = CommandsFileV41.model_validate(payload())
    value.commands[0].parameters["x"] = math.nan
    with pytest.raises(ValueError):
        canonical_commands_v41(value)


def test_C05_registered_but_unrelated_skill_is_not_a_valid_grasp():
    current = setup()
    contract = copy.deepcopy(current.pipeline.control_skill_contract)
    contract["skills"]["unrelated"] = {"expansion_level": "task", "parameters_schema": {"type": "object"}, "object_parameters": {}}
    current.pipeline.control_skill_contract = contract
    current.pipeline.dual_skill_recipe = lambda request: {"operations": [{"operation_id": op.operation_id,
        "steps": [{"skill_name": "unrelated", "parameters": {}}]} for op in request.operations]}
    with pytest.raises(ValueError, match="skill_semantics_lost"):
        current.process_turn("bad-skill", task("left"))
    assert not current.exported_commands and not current.robot_mode_lock.locked


def test_W01_contract_is_planning_permission_only(tmp_path):
    from robot_agent_brain.web.service import AgentService
    from robot_agent_brain.config import BrainConfig
    service = AgentService(BrainConfig(model="test-no-network", scene_id_bits=32, output_dir=str(tmp_path)))
    try:
        assert not service.planning_capabilities()["dual_planning_ready"]
        service.app.pipeline.control_skill_contract = setup().pipeline.control_skill_contract
        capability = service.planning_capabilities()
        assert capability["dual_planning_ready"] and not capability["dual_execution_ready"]
        assert "4.1" not in capability["execution_protocols"]
    finally:
        service.tasks.close()


def test_E01_dispatch_rejection_preserves_plan_and_no_pending():
    current = setup()
    result = current.process_turn("plan", task("left"))
    with pytest.raises(ValueError, match="live_adapter_unavailable"):
        current.mark_dispatched(result.commands)
    assert current.exported_commands and current.pending_execution_request is None
    assert not current.dispatched_requests


def test_M10_remapped_declared_scene_preserves_live_profile_ids():
    from robot_agent_brain.scene.id_remapper import remap_scene
    from robot_agent_brain.contracts.scene import parse_scene_document
    current = setup()
    remapped = remap_scene(current.scene, new_scene_id=9, next_object_id=40,
                          robot_setup=current.robot_setup)
    document = remapped.scene.raw_document()
    document["robot_setup"] = remapped.robot_setup.model_dump(mode="json")
    scene = parse_scene_document(document, uint32=False).view
    profile = current.robot_profiles.resolve_scene(scene)
    session = BrainSession(scene, current.pipeline, LocalScenePlatform(), robot_profiles=current.robot_profiles)
    session.bind_imported_profile(profile)
    assert session.robot_setup == remapped.robot_setup and not session.robot_mode_lock.locked
    assert set(session.profile_object_map.values()) == {remapped.id_map[i] for i in current.platform_object_ids}
    result = session.process_turn("remapped-plan", task("right"))
    assert result.commands.schema_version == "4.1" and result.commands.scene_digest == digest(scene)


def test_M17_ack_rejection_keeps_scene_lock_and_exports_unchanged():
    from robot_agent_brain.errors import SceneCommitRejected
    current = selectable()
    before = digest(current.scene)
    class Reject(LocalScenePlatform):
        def load_scene(self, scene):
            raise SceneCommitRejected("fixture_ack_refused")
    current.platform = Reject()
    turn = task("left").model_copy(update={"robot_setup_request": RobotSetupRequest(mode="dual")})
    with pytest.raises(SceneCommitRejected):
        current.process_turn("rejected", turn)
    assert digest(current.scene) == before and not current.robot_mode_lock.locked
    assert not current.exported_commands and current.first_robot_mode_turn_id is None


def envelope():
    from robot_agent_brain.contracts.execution_v41 import ExecutionEnvelopeV41
    current = setup()
    result = current.process_turn("plan", task("left"))
    return ExecutionEnvelopeV41(boundary_version="brain.execution.v41.proposal.1", session_id="fixture-session",
        commands=result.commands, scene=current.scene, setup=current.robot_setup,
        setup_revision=current.robot_setup_revision, skill_contract_revision=result.commands.skill_contract_revision,
        runtime=current.arm_states)


@pytest.mark.parametrize("fault", ["stale", "duplicate", "arm", "partial", "unknown_runtime"])
def test_E02_proposed_feedback_cannot_claim_unverified_success(fault):
    from robot_agent_brain.contracts.execution_v41 import ExecutionFeedbackV41
    value = envelope()
    commands = value.commands
    data = dict(boundary_version=value.boundary_version, session_id=value.session_id, request_id=commands.request_id,
        input_scene_digest=commands.scene_digest, setup_revision=commands.robot_setup_revision,
        skill_contract_revision=commands.skill_contract_revision, status="success",
        commands=[dict(command_id=c.command_id, arm=c.arm, status="success") for c in commands.commands],
        runtime=value.runtime.model_dump(), final_scene=value.scene.model_dump(), effect_evidence="verified_final_state")
    if fault == "stale":
        data["request_id"] = "older-request"
    elif fault == "duplicate":
        data["commands"].append(copy.deepcopy(data["commands"][0]))
    elif fault == "arm":
        data["commands"][0]["arm"] = "right"
    elif fault == "partial":
        data["commands"][0]["status"] = "failed"
    else:
        data["runtime"]["arms"]["right"]["state_known"] = False
    with pytest.raises(ValueError):
        ExecutionFeedbackV41.model_validate(data).validate_against(value)


def test_W02_v41_dispatch_keeps_planning_result_and_artifacts(tmp_path):
    from types import SimpleNamespace
    from robot_agent_brain.web.service import AgentService
    from robot_agent_brain.config import BrainConfig
    service = AgentService(BrainConfig(model="offline", scene_id_bits=32, output_dir=str(tmp_path),
        execution_enabled=True, execution_python="/bin/false", execution_control_root="/tmp", execution_library="/tmp/no-library"))
    current = setup()
    plan = current.process_turn("plan-only", task("left"))
    path = tmp_path / "commands.json"
    path.write_text(__import__('json').dumps(canonical_commands_v41(plan.commands)))
    result = {"outcome": "plan_ready", "executed": False, "artifacts": [str(path)]}
    try:
        trajectories = service.dispatch(current, current.platform, SimpleNamespace(artifacts={"commands":str(path)}), "id", result)
        assert trajectories == [] and result["outcome"] == "plan_ready"
        assert result["artifacts"] == [str(path)] and not result["executed"]
        assert current.pending_execution_request is None and not current.dispatched_requests
    finally:
        service.tasks.close()


def test_M16_layout_then_mode_configuration_robot_failure_keeps_only_prefix():
    from test_dual_layout_composite_sequence import prepared
    current, composite = prepared("absent")
    current = selectable_with_scene(current)
    composite.phases[1].robot_setup_request = RobotSetupRequest(mode="dual")
    before = current.scene.scene_version
    with pytest.raises(ValueError):
        current.process_composite_turn("composite-failure", composite)
    assert current.scene.scene_version == before + 1
    assert not current.robot_mode_lock.locked and current.robot_setup.mode == "single"
    assert not current.exported_commands and not current.dispatched_requests
    assert len(current.arrangement_index.snapshot()) == 1


def test_M17_checkpoint_failure_prevents_external_dispatch(tmp_path, monkeypatch):
    from test_web_execution import world, rows, ExecutionOutcome, dispatch
    service, browser, current, commands, record, _ = world(tmp_path, ExecutionOutcome(ok=True, steps=rows()))
    def fail(*args, **kwargs):
        raise OSError("fixture_checkpoint_failed")
    monkeypatch.setattr(service.app, "_save_session", fail)
    with pytest.raises(OSError, match="checkpoint_failed"):
        dispatch(service, tmp_path, current, commands, record['id'])
    assert not service.execution_port.calls
    assert current.pending_execution_request is None and not current.dispatched_requests
    assert not browser.receipt


def test_W02_cli_plan_ready_and_setup_are_not_failure_chains(tmp_path):
    from test_web_service import configured
    from robot_agent_brain.web.protocol import SessionRequest
    from robot_agent_brain.contracts.run_report import BrainRunReport
    service, _ = configured(tmp_path)
    session_id = service.activate(SessionRequest(browserID="b"))["sessionID"]
    current = service.app.get_session(session_id)
    for name, delivery in (("plan", "commands_exported"), ("setup", "robot_configured")):
        report = BrainRunReport(session_id=session_id, request_id=name, provider="replay",
            run_status="success", delivery_status=delivery, executed=False)
        service.app._record_cli_turn(session_id, name, report)
        assert current.conversation_memory.active_failure_chain is None
    assert [turn.final_outcome for turn in current.conversation_memory.recent_turns] == ['plan_ready','robot_configured']


def test_W01_operator_contract_snapshot_injection_and_revision_change(tmp_path):
    import json
    from robot_agent_brain.application import BrainApplication
    from robot_agent_brain.config import BrainConfig
    value = setup().pipeline.control_skill_contract
    path = tmp_path / 'trusted-contract.json'
    path.write_text(json.dumps(value))
    app = BrainApplication(BrainConfig(model='offline', output_dir=str(tmp_path/'app'), control_skill_contract_path=str(path)))
    assert app.pipeline.control_skill_contract.revision == value['revision']
    changed = copy.deepcopy(value)
    changed['revision'] = 'fixture-reviewed-v2'
    path.write_text(json.dumps(changed))
    app.refresh_control_contract()
    assert app.pipeline.control_skill_contract.revision == 'fixture-reviewed-v2'
    changed['skills']['pick']['parameters_schema']['description'] = 'different content without a new revision'
    path.write_text(json.dumps(changed))
    with pytest.raises(ValueError, match='revision_reused'):
        app.refresh_control_contract()


def test_E02_success_cannot_skip_explicit_predecessor():
    from robot_agent_brain.contracts.execution_v41 import ExecutionEnvelopeV41, ExecutionFeedbackV41
    value = envelope()
    raw = value.model_dump()
    first = raw['commands']['commands'][0]
    second = {**copy.deepcopy(first), 'command_id': 'R-second', 'operation_id': 'second', 'arm':'right', 'depends_on':[first['command_id']]}
    raw['commands']['commands'].append(second)
    value = ExecutionEnvelopeV41.model_validate(raw)
    feedback = ExecutionFeedbackV41(boundary_version=value.boundary_version, session_id=value.session_id,
        request_id=value.commands.request_id, input_scene_digest=value.commands.scene_digest,
        setup_revision=value.setup_revision, skill_contract_revision=value.skill_contract_revision,
        status='partial', effect_evidence='unknown', commands=[
            {'command_id':first['command_id'], 'arm':'left', 'status':'failed'},
            {'command_id':'R-second','arm':'right','status':'success'}])
    with pytest.raises(ValueError, match='dependency_failed'):
        feedback.validate_against(value)


def test_E03_retry_requires_explicit_execution_evidence():
    from robot_agent_brain.web.service import AgentService
    assert not AgentService._retry_allowed({'outcome':'failed'})
    assert not AgentService._retry_allowed({'execution': {'retry_safe':True,'observed_effect':'unknown','steps':[]}})
    assert AgentService._retry_allowed({'execution': {'retry_safe':True,'observed_effect':'none','steps':[]}})
    assert not AgentService._retry_allowed({'execution': {'retry_safe':True,'observed_effect':'none','steps':[{'status':'success'}]}})


def test_E01_prepared_envelope_is_scene_and_contract_bound_without_dispatch():
    current = setup()
    result = current.process_turn('plan', task('left'))
    value = current.prepare_sequence_execution_envelope(result.commands, current.pipeline.control_skill_contract,
                                                       session_id='fixture-session')
    assert value.scene.raw_document() == current.scene.raw_document()
    assert current.pending_execution_request is None and not current.dispatched_requests
    changed = copy.deepcopy(current.pipeline.control_skill_contract)
    changed['revision'] = 'changed'
    with pytest.raises(ValueError, match='revision_mismatch'):
        current.prepare_sequence_execution_envelope(result.commands, changed, session_id='fixture-session')
    current.sync_state = 'unknown'
    with pytest.raises(ValueError, match='state_unknown'):
        current.prepare_sequence_execution_envelope(result.commands, current.pipeline.control_skill_contract, session_id='fixture-session')


def test_B2_auto_uses_registered_recipe_or_capable_qwen_without_failure_fallback():
    current = setup('auto')
    current.pipeline.dual_skill_recipe = None
    calls = []
    class Provider:
        def plan_dual_operations(self, request):
            calls.append(request)
            return {'operations': [{'operation_id': op.operation_id, 'steps': [
                {'skill_name':'pick','parameters':{'source':op.source_object_id}}]} for op in request.operations]}
    current.pipeline.skill_planner.provider = Provider()
    result = current.process_turn('auto', task('left'))
    assert result.planner_used == 'qwen' and len(calls) == 1
    explicit = setup('recipe')
    explicit.pipeline.dual_skill_recipe = None
    with pytest.raises(ValueError, match='recipe_not_registered'):
        explicit.process_turn('recipe', task('left'))
    assert not explicit.exported_commands


def test_M01_truly_empty_scene_query_has_no_profile_or_lock(tmp_path):
    from robot_agent_brain.contracts.scene import SceneConfig
    current = BrainSession(SceneConfig(scene_schema_version=1, scene_id=1, scene_version=0, objects=[]), setup().pipeline, LocalScenePlatform())
    current.process_turn('empty-query', query())
    assert current.robot_setup is None and current.robot_mode_lock is None
    resumed = restore(tmp_path, current)
    assert resumed.robot_mode_lock is None and resumed.robot_setup is None
    assert not resumed.exported_commands and not resumed.dispatched_requests


def test_M02_six_object_layout_edit_sequence_never_locks_mode():
    from test_dual_layout_composite_sequence import prepared
    current, composite = prepared()
    spec = composite.phases[0].arrangement_spec
    spec = spec.model_copy(update={'pattern':spec.pattern.model_copy(update={'rows':2,'cols':3}),
        'items':spec.items.model_copy(update={'requested_count':6})})
    layout = composite.phases[0].model_copy(update={'arrangement_spec':spec})
    current.process_turn('six-apples', layout)
    # A second semantic layout edits the existing arrangement, rather than
    # stacking another grid on the same occupied cells.
    changed = spec.model_copy(update={'operation':'rearrange'})
    current.process_turn('layout-again', layout.model_copy(update={'arrangement_spec':changed}))
    color = BrainTurn(status='accepted', turn_kind='scene_edit', instruction='所有苹果改蓝',scene_edit={
        'entities':[{'entity_id':'a','semantic_name':'apple','category':'fruit','quantity_mode':'all','all_available':True}],
        'operations':[{'operation':'update_properties','target':'a','properties':{'color':'blue'}}]})
    current.process_turn('color',color)
    assert not current.robot_mode_lock.locked and current.first_robot_mode_turn_id is None
    assert not current.exported_commands and not current.dispatched_requests
    assert len(current.arrangement_index.snapshot()[0]['slot_bindings']) == 6


@pytest.mark.parametrize('entry',['browser','cli'])
def test_M10_real_application_import_binds_same_candidate_before_robot(entry,tmp_path):
    from robot_agent_brain.application import BrainApplication
    from robot_agent_brain.config import BrainConfig
    from test_application_artifacts import Provider
    configured = setup()
    class ImportPlatform(LocalScenePlatform):
        def adopt(self, scene):
            self.next_object_id = max((obj.object_id_in_scene for obj in scene.objects), default=-1) + 1
            return self.load_scene(scene)
    app = BrainApplication(BrainConfig(provider='replay', planner='recipe', scene_id_bits=32,
        output_dir=str(tmp_path), robot_profiles=configured.robot_profiles), provider=Provider(query()),
        control_skill_contract=configured.pipeline.control_skill_contract, platform_factory=ImportPlatform)
    scene = configured.scene
    if entry == 'browser':
        app.accept_browser_scene('import',scene,platform_object_ids=configured.platform_object_ids)
    else:
        app._load_scene_object('import',scene)
    current = app.get_session('import')
    assert current.robot_setup.mode == 'dual' and not current.robot_mode_lock.locked
    current.process_turn('query',query())
    assert not current.robot_mode_lock.locked
    # A registered fixture recipe, not production Control support.
    current.pipeline.dual_skill_recipe = configured.pipeline.dual_skill_recipe
    result = current.process_turn('robot',task('left'))
    assert result.commands.schema_version == '4.1' and current.robot_mode_lock.locked
    assert not current.dispatched_requests


def test_M17_lost_ack_preserves_unknown_without_publishing_plan():
    current = selectable()
    before = digest(current.scene)
    class Lost(LocalScenePlatform):
        def load_scene(self,scene):
            raise TimeoutError('fixture_lost_ack')
    current.platform = Lost()
    with pytest.raises(TimeoutError):
        current.process_turn('unknown',task('left').model_copy(update={'robot_setup_request':RobotSetupRequest(mode='dual')}))
    assert current.sync_state == 'unknown' and digest(current.scene) == before
    assert not current.robot_mode_lock.locked and not current.exported_commands


def test_M17_layout_receipt_replay_does_not_increment_or_lock():
    from test_dual_layout_composite_sequence import prepared
    current, composite = prepared()
    first = current.process_turn('layout',composite.phases[0])
    version,count = current.scene.scene_version,current.session_turn_index
    second = current.process_turn('layout',composite.phases[0])
    assert first == second and current.session_turn_index == count
    assert current.scene.scene_version == version and not current.robot_mode_lock.locked


def test_M13_missing_accepted_history_never_unlocks_old_decision(tmp_path):
    from robot_agent_brain.session.conversation_memory import ConversationTurn
    current=setup()
    current.process_turn('first',query())
    current.conversation_memory.recent_turns.append(ConversationTurn(turn_id='first',session_id='matrix',sequence=1,
        raw_user_text='几个苹果',final_outcome='answered'))
    store=SessionStore(tmp_path)
    store.save('matrix',current,revision=1)
    raw=store.load('matrix').model_dump(mode='python')
    raw.pop('mode_lifecycle_version')
    raw['session_turn_index']=4  # Three accepted stages have no evidence here.
    raw['robot_mode_lock'].update(locked=True,locked_at_turn=1)
    value=SessionState.model_validate(raw)
    assert value.robot_mode_lock.locked
    assert 'mode_migration_history_incomplete_lock_preserved' in value.mode_migration_diagnostics


def test_W02_sessions_list_keeps_checkpoint_mode_without_scene_adoption(tmp_path):
    import asyncio
    from aiohttp.test_utils import TestClient,TestServer
    from test_web_service import configured
    from robot_agent_brain.web.protocol import SessionRequest
    from robot_agent_brain.web.service import create_http_app
    async def run():
        service,browser=configured(tmp_path)
        sid=service.activate(SessionRequest(browserID='b'))['sessionID']
        current=setup()
        current.platform=service.app.get_session(sid).platform
        service.app.sessions[sid]=current
        service.app._save_session(sid)
        service.app.sessions.pop(sid)
        before=list(browser.calls)
        async with TestClient(TestServer(create_http_app(service))) as client:
            response=await client.get('/sessions?browser_id=b')
            assert response.status==200
            row=(await response.json())['sessions'][0]
            assert row['deployment_candidate']['mode']=='dual'
            assert row['robot_mode_lock']['locked'] is False
            assert row['first_robot_mode_turn_id'] is None and row['prompt_route'] is None
            assert list(browser.calls)==before
    asyncio.run(run())


def test_M11_declared_profile_cannot_override_planning_interfaces():
    from robot_agent_brain.contracts.scene import parse_scene_document
    current=setup()
    document=current.scene.raw_document()
    document['robot_setup']=current.robot_setup.model_dump(mode='json')
    document['robot_setup']['arms']['left']['planning_group']='unregistered-group'
    with pytest.raises(ValueError,match='interface_mapping_mismatch'):
        current.robot_profiles.resolve_scene(parse_scene_document(document,uint32=False).view)


def test_C05_object_role_parameter_cannot_be_omitted_even_if_schema_optional():
    current=setup()
    contract=copy.deepcopy(current.pipeline.control_skill_contract)
    contract['skills']['pick']['parameters_schema']['required']=[]
    current.pipeline.control_skill_contract=contract
    current.pipeline.dual_skill_recipe=lambda request:{'operations':[{'operation_id':op.operation_id,
        'steps':[{'skill_name':'pick','parameters':{}}]} for op in request.operations]}
    with pytest.raises(ValueError,match='object_parameter_missing'):
        current.process_turn('missing-source',task('left'))
    assert not current.exported_commands and not current.robot_mode_lock.locked
