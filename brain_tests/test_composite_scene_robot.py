import pytest
from robot_agent_brain.contracts.composite_turn import CompositeTask
from robot_agent_brain.contracts.turn import BrainTurn
from robot_agent_brain.contracts.task_intent import TaskIntent
from robot_agent_brain.pipeline import BrainPipeline
from robot_agent_brain.session.brain_session import BrainSession
from robot_agent_brain.adapters.local_scene_platform import LocalScenePlatform
from test_layout_transaction import setup


def session_and_task(spacing=.12, target="apple"):
    scene, spec, editor = setup(spacing)
    data = spec.model_dump()
    data["pattern"] = {"kind": "grid", "rows": 1, "cols": 1}
    data["items"]["requested_count"] = 1
    # An unavailable understanding provider proves parsed phases are reused.
    pipeline = BrainPipeline(None, editor.assets, scene_editor=editor)
    session = BrainSession(scene, pipeline, LocalScenePlatform())
    layout = BrainTurn(status="accepted", turn_kind="scene_layout", instruction="新增苹果",
                       arrangement_spec=type(spec).model_validate(data))
    robot = BrainTurn(status="accepted", turn_kind="robot_task", instruction="抓起" + target,
        task_intent=TaskIntent(instruction="抓起" + target,
            entities=[{"entity_id": "source", "semantic_name": target, "category": "fruit"}],
            operations=[{"operation_id": "op-1", "task_type": "grasp", "target": "source"}]))
    return session, CompositeTask(instruction="新增苹果再抓起", phases=[layout, robot])


def test_composite_reuses_semantics_and_grounds_new_instance():
    session, task = session_and_task()
    results = session.process_composite_turn("composite", task)
    created = results[0].layout_resolution.instance_ids
    assert results[1].grounded_task.entities[0].scene_object_id == created[0]
    assert results[1].commands.scene_version == session.scene.scene_version
    from robot_agent_brain.web.protocol import digest
    assert results[1].commands.scene_digest == digest(session.scene)
    assert session.exported_commands["composite-phase-2"]["scene_digest"] == digest(session.scene)
    record = session.composite_turn_records[-1]
    assert [phase["status"] for phase in record["phases"]] == ["committed", "planned"]
    assert record["phases"][0]["scene_digest_after"] == record["phases"][1]["scene_digest_before"]
    assert record["phases"][1]["scene_digest_after"] == record["phases"][1]["scene_digest_before"]
    with pytest.raises(ValueError, match="already_recorded"):
        session.process_composite_turn("composite", task)


def test_robot_failure_preserves_committed_layout_without_old_commands():
    session, task = session_and_task(target="banana")
    before_version = session.scene.scene_version
    with pytest.raises(Exception):
        session.process_composite_turn("missing", task)
    assert len(session.scene.objects) == 2
    assert session.scene.scene_version == before_version + 1
    assert not session.exported_commands
    assert [p["status"] for p in session.composite_turn_records[-1]["phases"]] == ["committed", "failed"]


@pytest.mark.parametrize("corruption", [{"scene_digest": "0" * 64}, {"scene_version": 999}])
def test_export_rejects_stale_scene_binding_without_rebinding(corruption):
    session, task = session_and_task()
    result = session.process_composite_turn("binding", task)[1]
    stale = result.model_copy(update={"commands": result.commands.model_copy(
        update={"request_id": "stale", **corruption})})
    before = dict(session.exported_commands)
    with pytest.raises(ValueError, match="commands_scene_binding_mismatch"):
        session._accept_result("stale", stale)
    assert session.exported_commands == before


def test_historical_commands_without_digest_remain_replayable():
    from robot_agent_brain.contracts.commands import canonical_commands, parse_commands
    session, task = session_and_task()
    result = session.process_composite_turn("history", task)[1]
    old = canonical_commands(result.commands)
    old.pop("scene_digest")
    assert canonical_commands(parse_commands(old)) == old


def test_layout_failure_skips_robot_phase():
    session, task = session_and_task()
    spec = task.phases[0].arrangement_spec
    invalid = spec.model_copy(update={"region": spec.region.model_copy(update={"surface_ref": "missing_surface"})})
    task.phases[0] = task.phases[0].model_copy(update={"arrangement_spec": invalid})
    before = session.scene.model_dump()
    with pytest.raises(ValueError, match="region_unresolved"):
        session.process_composite_turn("layout-failed", task)
    assert session.scene.model_dump() == before
    assert not session.exported_commands
    assert [p["status"] for p in session.composite_turn_records[-1]["phases"]] == ["failed", "skipped"]
