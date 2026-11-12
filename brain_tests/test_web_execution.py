"""The dispatch seam: exported plan -> runner -> feedback -> committed world -> playback.

Nothing here launches a process.  The runner is a stand-in that answers with the
same structure a control report is reduced into, so the invariants the WebEditor
depends on -- what counts as success, what gets written back, when the clips
leave -- are testable without a simulator or an open browser.
"""
import copy
import json
from types import SimpleNamespace

import httpx
import pytest

pytest.importorskip("aiohttp", reason="optional web integration dependencies not installed")
pytest.importorskip("rfc8785", reason="optional web integration dependencies not installed")
from robot_agent_brain.config import BrainConfig
from robot_agent_brain.contracts.commands import canonical_commands
from robot_agent_brain.contracts.commands_atomic import AtomicCommand, AtomicCommandsFile
from robot_agent_brain.ports.execution import ExecutionOutcome, ExecutionStep
from robot_agent_brain.web.protocol import SessionRequest, StartTask, digest
from robot_agent_brain.web.service import AgentService
from test_application_artifacts import Provider, robot
from test_web_gateway import Browser, adapter

GOLDEN = [("approach", 1), ("pick", 1), ("lift_up", None), ("retreat", 1), ("move_to", "home"),
          ("approach", 2), ("put", 2), ("retreat", 2)]
APPLE, TABLE = 1, 0
MOVED = {APPLE: {"position": [0.0, 0.05, 0.06], "quaternion_xyzw": [0.0, 0.0, 0.0, 1.0]}}
_EXECUTABLE = {"execution_python": "/bin/false", "execution_control_root": "/tmp/control",
               "execution_library": "/tmp/control/libsim_platform_c.so"}


def exported():
    return AtomicCommandsFile(request_id="r-1", scene_id=1, scene_version=0, commands=[
        AtomicCommand(command_id=str(index), skill_name=skill,
                      parameters={"target": target} if target is not None else {})
        for index, (skill, target) in enumerate(GOLDEN, 1)])


def rows(count=len(GOLDEN), status="success", error_code=None):
    """What the runner reported: only the first ``count`` commands came back."""
    return [ExecutionStep(command_id=str(index), skill_name=skill, status=status,
                          error_code=error_code if status == "failed" else None)
            for index, (skill, _) in enumerate(GOLDEN[:count], 1)]


def stopped_at(index, error_code="collision"):
    """A run that accounted for every command: the one at ``index`` failed and ended it."""
    return [ExecutionStep(command_id=str(number), skill_name=skill,
                          status="success" if number < index else "failed",
                          error_code=None if number < index else error_code)
            for number, (skill, _) in enumerate(GOLDEN, 1)]


class Runner:
    """The port, answered from a recorded control report."""

    def __init__(self, outcome=None, *, progress_at=None, raises=None):
        self.outcome, self.progress_at, self.raises, self.calls = outcome, progress_at, raises, []

    def run(self, commands, scene_document, *, progress=None):
        self.calls.append((commands, copy.deepcopy(scene_document)))
        if self.progress_at is not None and progress is not None:
            progress(self.progress_at)
        if self.raises is not None:
            raise self.raises
        return self.outcome


def world(tmp_path, outcome, execution_enabled=True, **kwargs):
    """A live session with an exported plan, plus the task row a dispatch reports under."""
    browser = Browser()
    service = AgentService(BrainConfig(
        provider="replay", planner="recipe", scene_id_bits=32, scene_platform_object_ids={0},
        output_dir=str(tmp_path), debug=True, execution_enabled=execution_enabled,
        **(_EXECUTABLE if execution_enabled else {})),
        provider=Provider(robot()),
        platform_factory=lambda binding: adapter(browser, tmp_path / binding["id"] / "gateway_transactions"))
    service.execution_port = Runner(outcome, **kwargs)
    identifier = service.activate(SessionRequest(
        browserID="b", scene=browser.scene.model_dump(mode="json")))["sessionID"]
    service.app.accept_browser_scene(identifier, browser.scene)
    session = service._bind(identifier)
    commands = exported()
    session.exported_commands[commands.request_id] = canonical_commands(commands)
    record, fresh = service.tasks.submit(StartTask(
        command="把苹果放进收纳盒", scene=browser.scene, sceneDigest=digest(browser.world()),
        browserID="b", sessionID=identifier, clientRequestID="exec-1"))
    assert fresh
    return service, browser, session, commands, record, identifier


def dispatch(service, tmp_path, session, commands, task_id):
    path = tmp_path / "commands.json"
    path.write_text(json.dumps(canonical_commands(commands)), encoding="utf-8")
    report = SimpleNamespace(artifacts={"commands": str(path)}, request_id=commands.request_id)
    result = {"outcome": "plan_ready", "executed": False}
    return result, service.dispatch(session, session.platform, report, task_id, result)


def pose(scene, object_id):
    from robot_agent_brain.scene.component_access import SceneIndex
    return SceneIndex(scene).component(object_id, "Transform").properties


def test_executed_poses_become_the_next_world(tmp_path):
    clip = tmp_path / "trajectory.traj"
    clip.write_bytes(b"TRAJ")
    service, browser, session, commands, record, identifier = world(tmp_path, ExecutionOutcome(
        ok=True, steps=rows(), moved=MOVED, traj_path=str(clip)))
    started = pose(session.scene, APPLE)["position"]
    result, trajs = dispatch(service, tmp_path, session, commands, record["id"])
    assert result["outcome"] == "scene_updated" and result["executed"] is True
    assert result["execution"]["writeback_status"] == "committed"
    assert result["execution"]["trajectory_available"] is True
    assert result["execution"]["moved_object_ids"] == [APPLE]
    assert trajs == [str(clip)]
    assert session.pending_execution_request is None and session.pending_commands is None
    # The browser received exactly one world: one version ahead, the apple where
    # the runner said it ended up, everything else untouched.
    assert browser.calls.count(("POST", "/commitWorld")) == 1
    assert session.scene.scene_version == commands.scene_version + 1
    assert pose(session.scene, APPLE)["position"] == MOVED[APPLE]["position"] != started
    assert "scene_sub_version" not in session.scene.raw_document()
    # The document handed to the runner is the world the plan was derived from.
    assert service.execution_port.calls[0][1]["scene_id"] == canonical_commands(commands)["scene_id"]
    service.play(record["id"], trajs)
    assert browser.calls[-1] == ("POST", "/updateTraj")
    detail = json.loads((tmp_path / identifier / "traj_playback" / f"{record['id']}.json")
                        .read_text(encoding="utf-8"))
    assert detail["reply"]["ignored_objects"] == [] and detail["accepted"] is True


def test_nothing_is_played_while_the_lease_is_still_held(tmp_path):
    clip = tmp_path / "trajectory.traj"
    clip.write_bytes(b"TRAJ")
    service, browser, session, commands, record, _ = world(tmp_path, ExecutionOutcome(
        ok=True, steps=rows(), moved=MOVED, traj_path=str(clip)))
    _, trajs = dispatch(service, tmp_path, session, commands, record["id"])
    # Dispatch runs under the browser lock; only the post-release play may push.
    assert trajs and all(route != "/updateTraj" for _, route in browser.calls)
    service.play(record["id"], trajs)
    assert browser.calls[-1] == ("POST", "/updateTraj")


def test_a_run_that_did_not_account_for_every_command_is_never_a_success(tmp_path):
    service, browser, session, commands, record, _ = world(tmp_path, ExecutionOutcome(
        ok=True, steps=rows(count=5), moved=MOVED, traj_path="/tmp/trajectory.traj"))
    result, trajs = dispatch(service, tmp_path, session, commands, record["id"])
    # Success requires full coverage; five rows out of eight is not a completed plan,
    # so no world is committed.  The clip still goes out -- it is the only picture of
    # a run that stopped halfway.
    assert result["executed"] is False and result["outcome"] == "failed"
    assert result["execution"]["writeback_status"] == "none"
    assert trajs == ["/tmp/trajectory.traj"]
    assert browser.calls.count(("POST", "/commitWorld")) == 0
    assert session.scene.scene_version == commands.scene_version
    assert session.pending_execution_request is None
    assert session.sync_state == "synchronized"


def test_a_service_that_forbids_execution_never_reaches_the_runner(tmp_path):
    # The config is the only execution authorization: a runner fitted onto a
    # service that forbids dispatching has to stay unused, and the refusal has
    # to happen at the seam itself rather than depend on a hidden button.
    service, browser, session, commands, record, _ = world(
        tmp_path, ExecutionOutcome(ok=True, steps=rows(), moved=MOVED, traj_path="/tmp/trajectory.traj"),
        execution_enabled=False)
    assert service.execution() is None
    with pytest.raises(ValueError, match="execution_disabled"):
        dispatch(service, tmp_path, session, commands, record["id"])
    assert service.execution_port.calls == []
    assert session.pending_commands is None and session.pending_execution_request is None
    assert browser.calls.count(("POST", "/commitWorld")) == 0
    assert session.scene.scene_version == commands.scene_version


def test_execution_authorization_names_the_interpreter_it_will_run(tmp_path):
    # The control pins numpy/mujoco versions the service interpreter cannot
    # satisfy, so switching execution on without an explicit interpreter is a
    # configuration mistake, not a default to fall back on.
    for name, value in (("execution_python", None), ("execution_control_root", None),
                        ("execution_library", None)):
        with pytest.raises(ValueError, match="execution_configuration_incomplete"):
            BrainConfig(execution_enabled=True, **{**_EXECUTABLE, name: value})
    with pytest.raises(ValueError, match="execution_python_must_be_absolute"):
        BrainConfig(execution_enabled=True, **{**_EXECUTABLE, "execution_python": "python"})


def test_a_failed_run_leaves_the_world_alone_but_still_shows_the_clip(tmp_path):
    clip = tmp_path / "failed.traj"
    clip.write_bytes(b"TRAJ")
    service, browser, session, commands, record, _ = world(tmp_path, ExecutionOutcome(
        ok=False, steps=stopped_at(2), error_code="collision", detail="Step failed: collision",
        traj_path=str(clip)))
    started = pose(session.scene, APPLE)["position"]
    result, trajs = dispatch(service, tmp_path, session, commands, record["id"])
    assert result["outcome"] == "failed" and not result["executed"]
    assert result["error"]["code"] == "collision"
    # Every row the runner reported reaches the task, with the failure kept where it happened.
    assert [step["status"] for step in result["execution"]["steps"]] == ["success"] + ["failed"] * 7
    assert [step["error_code"] for step in result["execution"]["steps"]] == [None] + ["collision"] * 7
    assert trajs == [str(clip)] and browser.receipt is None
    assert pose(session.scene, APPLE)["position"] == started != MOVED[APPLE]["position"]
    assert session.scene.scene_version == commands.scene_version
    assert browser.calls.count(("POST", "/commitWorld")) == 0
    assert session.pending_execution_request is None
    # The failure clip reaches the browser the same way a success clip does: after the
    # lease, as playback only, so nothing about the committed world is implied.
    service.play(record["id"], trajs)
    assert browser.calls[-1] == ("POST", "/updateTraj")
    assert browser.calls.count(("POST", "/commitWorld")) == 0


def test_a_runner_that_never_started_still_closes_the_dispatch(tmp_path):
    service, browser, session, commands, record, _ = world(tmp_path, None, raises=OSError("no such file"))
    result, trajs = dispatch(service, tmp_path, session, commands, record["id"])
    assert result["error"]["code"] == "execution_dispatch_failed"
    assert result["execution"]["steps"] == []
    assert session.pending_execution_request is None and session.sync_state == "synchronized"
    assert trajs == [] and browser.calls.count(("POST", "/commitWorld")) == 0


def test_only_objects_the_plan_addressed_are_written_back(tmp_path):
    service, browser, session, commands, record, _ = world(tmp_path, ExecutionOutcome(
        ok=True, steps=rows(), moved={TABLE: {"position": [0.1, 0.1, 0.1],
                                              "quaternion_xyzw": [0.0, 0.0, 0.0, 1.0]}, **MOVED}))
    table_before = pose(session.scene, TABLE)
    result, _ = dispatch(service, tmp_path, session, commands, record["id"])
    # A report claiming the table itself moved is not something this round can
    # explain, so the world keeps its platform where the plan put it.
    assert result["executed"] is True
    assert result["execution"]["moved_object_ids"] == [TABLE, APPLE]
    assert pose(session.scene, TABLE) == table_before
    assert pose(session.scene, APPLE)["position"] == MOVED[APPLE]["position"]


def test_progress_names_the_command_under_way(tmp_path):
    service, browser, session, commands, record, _ = world(tmp_path, ExecutionOutcome(
        ok=True, steps=rows(), moved=MOVED), progress_at=rows(count=3))
    dispatch(service, tmp_path, session, commands, record["id"])
    assert service.progress[record["id"]] == "执行中 3/8 · lift_up"


def test_the_scene_document_a_dispatch_runs_is_the_one_the_browser_shows(tmp_path):
    service, browser, session, commands, record, _ = world(tmp_path, ExecutionOutcome(
        ok=True, steps=rows()))
    dispatch(service, tmp_path, session, commands, record["id"])
    assert service.execution_port.calls[0][1] == browser.world()


def test_playback_failure_never_changes_the_committed_world(tmp_path):
    clip = tmp_path / "trajectory.traj"
    clip.write_bytes(b"TRAJ")
    service, browser, session, commands, record, identifier = world(tmp_path, ExecutionOutcome(
        ok=True, steps=rows(), moved=MOVED, traj_path=str(clip)))
    dispatch(service, tmp_path, session, commands, record["id"])
    browser.fault = "traj_reject"
    assert service.play(record["id"], [clip]) is None
    detail = json.loads((tmp_path / identifier / "traj_playback" / f"{record['id']}.json")
                        .read_text(encoding="utf-8"))
    assert detail["accepted"] is False and "HTTPStatusError" in detail["error"]
    # The executed world was committed before the clip left; a deaf browser cannot undo it.
    assert session.scene.scene_version == commands.scene_version + 1
    assert service.play(record["id"], []) is None


@pytest.mark.parametrize("fault,count,ok", [(None, 2, True), ("traj_reject", 2, False)])
def test_traj_batch_counts_every_clip(tmp_path, fault, count, ok):
    browser = Browser()
    if fault:
        browser.fault = fault
    platform = adapter(browser, tmp_path / "journal")
    clips = []
    for index in range(count):
        path = tmp_path / f"clip{index}.traj"
        path.write_bytes(b"TRAJ" + bytes([index]))
        clips.append(path)
    if ok:
        assert platform.push_trajs(clips, request_id="r-1")["ok"] is True
        assert browser.trajectories[0].count(b'name="trajs"') == count
        assert json.loads((tmp_path / "journal" / "updateTraj_r-1.json").read_text(
            encoding="utf-8"))["byte_lengths"] == [5] * count
    else:
        with pytest.raises(httpx.HTTPStatusError):
            platform.push_trajs(clips)
        assert browser.trajectories == []


def test_an_empty_traj_batch_never_reaches_the_browser(tmp_path):
    browser = Browser()
    with pytest.raises(ValueError, match="gateway_traj_batch_empty"):
        adapter(browser, tmp_path).push_trajs([])
    assert browser.calls == []


@pytest.mark.parametrize("field,count", [("traj", 1), ("trajs", 2)])
def test_a_body_and_tally_that_disagree_are_refused(tmp_path, field, count):
    browser = Browser()
    platform = adapter(browser, tmp_path)
    clip = tmp_path / "clip.traj"
    clip.write_bytes(b"TRAJ")
    with clip.open("rb") as handle:
        # The editor reads parts named ``trajs`` only, and rejects a count that
        # disagrees with the number of parts, so both mistakes have to fail loudly.
        with pytest.raises(httpx.HTTPStatusError):
            platform._call("POST", "/updateTraj", params={"count": count},
                           files=[(field, ("clip.traj", handle, "application/octet-stream"))])
    assert browser.trajectories == []
