"""The adapter that hands an exported plan to the control repository.

The control side is a subprocess, so these tests replace the ``link`` package
with stand-ins and check the two things the real run cannot forgive: which world
document the reduction reads, and that a plan derived from a different scene
never reaches the runner at all.
"""
from pathlib import Path
from types import SimpleNamespace

import pytest

from robot_agent_brain.adapters import subprocess_execution
from robot_agent_brain.adapters.subprocess_execution import SubprocessExecutionAdapter
from robot_agent_brain.contracts.commands_atomic import AtomicCommand, AtomicCommandsFile

SCENE = {"scene_id": 3, "scene_version": 7, "objects": [
    {"object_id_in_scene": 7, "object_name_in_scene": "Apple",
     "components": [{"component_type": "Transform",
                     "properties": {"position": [0.18, -0.185, 0.637]}}]}]}
MOVED = {7: {"position": [0.303, 0.181, 0.655], "quaternion_xyzw": [0., 0., 0.71, 0.7]}}


def commands(**overrides):
    document = {"request_id": "r-1", "scene_id": 3, "scene_version": 7,
                "commands": [AtomicCommand(command_id="1", skill_name="pick", parameters={"target": 7})]}
    return AtomicCommandsFile.model_validate({**document, **overrides})


class Link:
    """The ``link`` modules, reduced to what the adapter touches."""

    def __init__(self, summary):
        self.seen = {}

        def describe_for(control_root):
            self.seen["describe_root"] = control_root
            return None

        self.error_descriptions = SimpleNamespace(describe_for=describe_for)
        self.feedback, self.runner, self.workspace = SimpleNamespace(), SimpleNamespace(), SimpleNamespace()

        def steps(report, describe=None):
            self.seen["describe"] = describe
            return [{"command_id": "1", "skill_name": "pick", "status": "success",
                     "error_code": None, "detail": None}]

        def summarize(result, scene_document, describe=None):
            self.seen["scene_document"] = scene_document
            self.seen["describe"] = describe
            return summary

        def build(root, *, scene_document, task, asset_root, request_id=None):
            self.seen["built"] = (scene_document, task)
            workspace = SimpleNamespace(root=Path(root), catalog_path=Path(root) / "catalog.json")
            return workspace, Path(root) / "commands.json", dict(task, request_id=request_id)

        def run(ws, **kwargs):
            self.seen["runner_kwargs"] = kwargs
            return SimpleNamespace(succeeded=True, report={}, traj_path=str(ws.root / "trajectory.traj"))

        self.feedback.steps, self.feedback.summarize = steps, summarize
        self.workspace.build, self.runner.run = build, run


def adapter(tmp_path, link, monkeypatch, **overrides):
    monkeypatch.setattr(subprocess_execution, "_link_modules",
                        lambda link_root: (link.error_descriptions, link.feedback,
                                           link.runner, link.workspace))
    return SubprocessExecutionAdapter(
        python="/bin/true", control_root="/tmp/control", library="/tmp/control/libsim.so",
        asset_root="/tmp/library", object_library_url="http://127.0.0.1:8000",
        workspace_root=str(tmp_path / "workspaces"), **overrides)


def test_the_reduction_reads_the_world_the_browser_is_showing(tmp_path, monkeypatch):
    # ``workspace.build`` hands back the stamped task document, and a task has no
    # objects to name -- reducing against it silently reports nothing moved.
    summary = {"ok": True, "steps": [{"command_id": "1", "skill_name": "pick", "status": "success",
                                      "error_code": None, "detail": None}],
               "moved": MOVED, "holding_object": None,
               "traj_path": str(tmp_path / "trajectory.traj"), "error_code": None, "detail": None}
    link = Link(summary)
    runner = adapter(tmp_path, link, monkeypatch)
    outcome = runner.run(commands(), SCENE)
    assert outcome.ok and outcome.moved == MOVED and outcome.error_code is None
    assert link.seen["scene_document"] == SCENE
    # Failures are explained with the control's own vocabulary, from the checkout
    # this deployment pointed at -- not a copy of it kept in the Brain.
    assert link.seen["describe_root"] == "/tmp/control"


@pytest.mark.parametrize("overrides", [{"scene_id": 4}, {"scene_version": 8}])
def test_a_plan_from_another_world_is_refused_before_it_runs(tmp_path, monkeypatch, overrides):
    link = Link({"ok": False, "steps": [], "moved": {}, "holding_object": None,
                 "traj_path": None, "error_code": None, "detail": None})
    runner = adapter(tmp_path, link, monkeypatch)
    with pytest.raises(Exception, match="execution_scene_identity_mismatch"):
        runner.run(commands(**overrides), SCENE)
    assert link.seen == {}


def test_perception_is_told_to_use_the_deployments_own_model(tmp_path, monkeypatch):
    # The control hard-codes a cloud endpoint behind a key that no longer
    # works, so grasp and place would fail in the child -- far from the
    # configuration that names the local model here.
    link = Link({"ok": True, "steps": [], "moved": {}, "holding_object": None,
                 "traj_path": None, "error_code": None, "detail": None})
    runner = adapter(tmp_path, link, monkeypatch, vlm_base_url="http://127.0.0.1:8080/v1",
                     vlm_model="/models/qwen.gguf")
    runner.run(commands(), SCENE)
    assert link.seen["runner_kwargs"]["child_env"] == {
        "ROBOT_LINK_VLM_BASE_URL": "http://127.0.0.1:8080/v1", "QWEN_MODEL": "/models/qwen.gguf"}


def test_a_deployment_that_names_no_endpoint_leaves_the_child_to_its_defaults(
        tmp_path, monkeypatch):
    link = Link({"ok": True, "steps": [], "moved": {}, "holding_object": None,
                 "traj_path": None, "error_code": None, "detail": None})
    runner = adapter(tmp_path, link, monkeypatch)
    runner.run(commands(), SCENE)
    assert link.seen["runner_kwargs"]["child_env"] == {}
