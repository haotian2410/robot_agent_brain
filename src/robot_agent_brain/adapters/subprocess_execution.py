"""Execute an exported plan by running the control repository as a child process.

Three properties decide this shape: the native collision library writes its logs
relative to the current directory, a fault inside FCL or a MuJoCo step must not
take the web service down, and the control side re-reads ``catalog.json`` from
wherever its scene lives, so every run needs a scratch directory of its own.
The workspace therefore doubles as the isolation mechanism and as the reason no
upstream file is ever modified.
"""
from __future__ import annotations

import copy
import sys
from collections import Counter
from pathlib import Path

from ..contracts.commands_atomic import AtomicCommandsFile, canonical_atomic_commands
from ..errors import BrainError
from ..ports.execution import ExecutionOutcome, ExecutionStep


def _link_modules(link_root: str | None):
    try:
        from link import error_descriptions, feedback, runner, workspace
    except ImportError:
        if link_root is None:
            raise
        sys.path.insert(0, str(Path(link_root).resolve()))
        from link import error_descriptions, feedback, runner, workspace
    return error_descriptions, feedback, runner, workspace


def unique_named_document(document: dict) -> dict:
    """Stamp the scene id onto repeated object names, which the control side forbids.

    The web dialect happily names eight apples ``apple``; the runner keys its bodies, its
    report and therefore the read-back poses by ``object_name_in_scene``, so a duplicate
    is a hard ``Duplicate scene object ID/name`` before a single command runs. Plans and
    the write-back both address objects by id, so renaming here only has to be visible to
    the one document handed to ``feedback.summarize``.
    """
    objects = document.get("objects") or []
    counts = Counter(item.get("object_name_in_scene") for item in objects)
    if not any(count > 1 for count in counts.values()):
        return document
    renamed = copy.deepcopy(document)
    for item in renamed["objects"]:
        name = item.get("object_name_in_scene")
        if counts.get(name, 0) > 1:
            item["object_name_in_scene"] = f"{name}-{item['object_id_in_scene']}"
    return renamed


class SubprocessExecutionAdapter:
    def __init__(self, *, python: str, control_root: str, library: str, asset_root: str,
                 object_library_url: str, workspace_root: str, link_root: str | None = None,
                 timeout_seconds: float = 180.0, backend: str = "mujoco",
                 vlm_base_url: str | None = None, vlm_model: str | None = None):
        self.python, self.control_root, self.library = python, control_root, library
        self.asset_root, self.object_library_url = asset_root, object_library_url
        self.workspace_root, self.link_root = workspace_root, link_root
        self.timeout_seconds, self.backend = timeout_seconds, backend
        self.vlm_base_url, self.vlm_model = vlm_base_url, vlm_model

    def child_env(self) -> dict:
        """The perception endpoint the child must use instead of its built-in one.

        ``QWEN_MODEL`` is the control's own knob and is left alone when this
        deployment names no model; the base URL has no such knob because the
        control hard-codes it, which is why the bridge exports its own variable.
        """
        if not self.vlm_base_url:
            return {}
        env = {"ROBOT_LINK_VLM_BASE_URL": self.vlm_base_url}
        if self.vlm_model:
            env["QWEN_MODEL"] = self.vlm_model
        return env

    def run(self, commands: AtomicCommandsFile, scene_document: dict, *, progress=None) -> ExecutionOutcome:
        error_descriptions, feedback, runner, workspace = _link_modules(self.link_root)
        task = canonical_atomic_commands(commands)
        header = (scene_document.raw_document() if hasattr(scene_document, "raw_document")
                  else scene_document)
        if (task["scene_id"], task["scene_version"]) != (header.get("scene_id"), header.get("scene_version")):
            raise BrainError("execution_scene_identity_mismatch", "execution",
                             f"命令文档写 {task['scene_id']}/{task['scene_version']}，"
                             f"场景文档写 {header.get('scene_id')}/{header.get('scene_version')}")
        header = unique_named_document(header)
        ws, commands_path, _ = workspace.build(
            self.workspace_root, scene_document=header, task=task, asset_root=self.asset_root,
            request_id=commands.request_id)
        # The control's error_messages module owns the wording of a control failure;
        # the Brain reads it from the checkout it was pointed at and copies nothing.
        describe = error_descriptions.describe_for(self.control_root)
        result = runner.run(ws, commands_path=commands_path, catalog_path=ws.catalog_path,
                            python=self.python, control_root=self.control_root, library=self.library,
                            object_library_url=self.object_library_url,
                            timeout_seconds=self.timeout_seconds, backend=self.backend,
                            child_env=self.child_env(),
                            progress=(lambda report: progress([ExecutionStep(
                                command_id=row["command_id"], skill_name=row["skill_name"],
                                status=row["status"], error_code=row["error_code"],
                                detail=row["detail"]) for row in feedback.steps(report, describe)]))
                            if progress else None)
        # The reduction reads poses back by object name, and only the scene
        # document carries those names: ``workspace.build`` returns the stamped
        # task document, which would reduce every moved object to nothing.
        return self.outcome(feedback.summarize(result, header, describe), result)

    @staticmethod
    def outcome(summary: dict, result) -> ExecutionOutcome:
        return ExecutionOutcome(
            ok=summary["ok"],
            steps=[ExecutionStep(command_id=step["command_id"], skill_name=step["skill_name"],
                                 status=step["status"], error_code=step["error_code"],
                                 detail=step["detail"]) for step in summary["steps"]],
            moved=summary["moved"], holding_object=summary["holding_object"],
            traj_path=summary["traj_path"], error_code=summary["error_code"], detail=summary["detail"])
