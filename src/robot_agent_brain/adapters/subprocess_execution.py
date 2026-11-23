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
import json
import sys
from collections import Counter
from pathlib import Path

from ..contracts.commands_atomic import AtomicCommandsFile, canonical_atomic_commands
from ..errors import BrainError
from ..perf_trace import timed, span
from ..ports.execution import ExecutionOutcome, ExecutionStep


def _link_modules(link_root: str | None):
    # The configured bridge checkout is authoritative.  Importing an already
    # installed ``link`` package first can silently bind an older integrated
    # copy, so a new bridge fix appears ineffective until the process is
    # restarted (and can still be wrong after restart).  Put the configured
    # root first for every run; only fall back to the environment package when
    # no root was configured.
    if link_root is not None:
        root = str(Path(link_root).resolve())
        if root in sys.path:
            sys.path.remove(root)
        sys.path.insert(0, root)
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
    def safe(name):
        return isinstance(name, str) and bool(name) and all(
            ch in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-" for ch in name)
    if all(count == 1 and safe(name) for name, count in counts.items()):
        return document
    renamed = copy.deepcopy(document)
    reserved = {name for name, count in counts.items() if count == 1 and safe(name)}
    for item in renamed["objects"]:
        name = item.get("object_name_in_scene")
        if counts.get(name, 0) > 1 or not safe(name):
            candidate = f"{name}-{item['object_id_in_scene']}" if safe(name) else f"object_{item['object_id_in_scene']}"
            while candidate in reserved:
                candidate += "_"
            reserved.add(candidate)
            item["object_name_in_scene"] = candidate
    return renamed


def restore_runtime_state_names(report: dict, name_mapping: list[dict]) -> None:
    """Translate control runtime names back to the submitted Scene names.

    The control runner is deliberately given ASCII/unique transport names.  Its
    measured ``final_state`` uses those names too, including the held object's
    ``gripper.object_id`` and the keys of ``objects``.  The bridge previously
    restored names only in ``final_scene.json``; consequently a successful grasp
    of a non-ASCII or duplicate-named object was rejected as an incomplete
    recoverable state.  Normalize the runtime report before feedback validation,
    without changing the control report on disk.
    """
    if not isinstance(report, dict):
        return
    transport_to_original = {
        row.get("transport_name"): row.get("source_name", row.get("original_name"))
        for row in name_mapping
        if isinstance(row, dict)
        and isinstance(row.get("transport_name"), str)
        and isinstance(row.get("original_name"), str)
    }
    final = report.get("final_state")
    if not isinstance(final, dict):
        return
    gripper = final.get("gripper")
    if isinstance(gripper, dict) and isinstance(gripper.get("object_id"), str):
        gripper["object_id"] = transport_to_original.get(
            gripper["object_id"], gripper["object_id"])
    objects = final.get("objects")
    if isinstance(objects, dict):
        restored = {}
        for key, value in objects.items():
            restored[transport_to_original.get(key, key)] = value
        final["objects"] = restored


def restore_final_scene_names(path: Path, name_mapping: list[dict]) -> None:
    """Restore transport names before the immutable final-scene check.

    The control runner receives ASCII/unique names, and therefore writes those
    names into ``snapshots/final_scene.json`` as well as ``final_state``.  The
    validator compares that snapshot with the submitted Scene, so translating
    only after ``feedback.summarize`` is too late: a valid run is rejected as
    an immutable component change.  Keep the mapping at this bridge boundary;
    IDs and all other authored fields remain untouched.
    """
    if not path.is_file():
        return
    transport_to_original = {
        row.get("transport_name"): row.get("original_name")
        for row in name_mapping
        if isinstance(row, dict)
        and isinstance(row.get("transport_name"), str)
        and isinstance(row.get("original_name"), str)
    }
    if not transport_to_original:
        return
    document = json.loads(path.read_text(encoding="utf-8"))
    # Object IDs are the stable identity.  A session may already contain a
    # transport name from an earlier round, while the control snapshot may use
    # its semantic name (or the reverse).  Prefer the submitted Scene's name
    # carried in the mapping row, falling back to the name map for old rows.
    id_to_scene_name = {
        row.get("object_id"): row.get("source_name", row.get("original_name"))
        for row in name_mapping
        if isinstance(row, dict) and isinstance(row.get("object_id"), int)
        and isinstance(row.get("original_name"), str)
    }
    for item in document.get("objects") or []:
        if not isinstance(item, dict):
            continue
        object_id = item.get("object_id_in_scene")
        if object_id in id_to_scene_name:
            item["object_name_in_scene"] = id_to_scene_name[object_id]
        elif isinstance(item.get("object_name_in_scene"), str):
            item["object_name_in_scene"] = transport_to_original.get(
                item["object_name_in_scene"], item["object_name_in_scene"])
    path.write_text(json.dumps(document, ensure_ascii=False, indent=2), encoding="utf-8")


class SubprocessExecutionAdapter:
    def __init__(self, *, python: str, control_root: str, library: str, asset_root: str,
                 object_library_url: str, workspace_root: str, link_root: str | None = None,
                 timeout_seconds: float = 180.0, backend: str = "mujoco",
                 vlm_base_url: str | None = None, vlm_model: str | None = None,
                 collision_model: str | None = None):
        self.python, self.control_root, self.library = python, control_root, library
        self.asset_root, self.object_library_url = asset_root, object_library_url
        self.workspace_root, self.link_root = workspace_root, link_root
        self.timeout_seconds, self.backend = timeout_seconds, backend
        self.vlm_base_url, self.vlm_model = vlm_base_url, vlm_model
        if collision_model not in (None, 'proxy', 'precise'):
            raise ValueError('collision_model_invalid')
        self.collision_model = collision_model

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

    @timed("control.dispatch", component="brain.execution")
    def run(self, commands: AtomicCommandsFile, scene_document: dict, *, progress=None) -> ExecutionOutcome:
        error_descriptions, feedback, runner, workspace = _link_modules(self.link_root)
        task = canonical_atomic_commands(commands)
        header = (scene_document.raw_document() if hasattr(scene_document, "raw_document")
                  else scene_document)
        if (task["scene_id"], task["scene_version"]) != (header.get("scene_id"), header.get("scene_version")):
            raise BrainError("execution_scene_identity_mismatch", "execution",
                             f"命令文档写 {task['scene_id']}/{task['scene_version']}，"
                             f"场景文档写 {header.get('scene_id')}/{header.get('scene_version')}")
        source_header = header
        header = unique_named_document(header)
        with span("control.workspace_build", component="bridge", source="adapters/subprocess_execution.py:SubprocessExecutionAdapter.run"):
            ws, commands_path, _ = workspace.build(
                self.workspace_root, scene_document=header, task=task, asset_root=self.asset_root,
                request_id=commands.request_id)
            name_mapping = [{"object_id": original["object_id_in_scene"],
                             "original_name": original["object_name_in_scene"],
                             "source_name": original["object_name_in_scene"],
                             "transport_name": transported["object_name_in_scene"]}
                            for original, transported in zip(source_header["objects"], header["objects"])]
            (ws.root / "object_name_mapping.json").write_text(
                json.dumps(name_mapping, ensure_ascii=False, indent=2), encoding="utf-8")
        # The control's error_messages module owns the wording of a control failure;
        # the Brain reads it from the checkout it was pointed at and copies nothing.
        describe = error_descriptions.describe_for(self.control_root)
        with span("control.child_run", component="control", source="adapters/subprocess_execution.py:SubprocessExecutionAdapter.run", wait_kind="child_process"):
            result = runner.run(ws, commands_path=commands_path, catalog_path=ws.catalog_path,
                            python=self.python, control_root=self.control_root, library=self.library,
                            object_library_url=self.object_library_url,
                            timeout_seconds=self.timeout_seconds, backend=self.backend,
                            **({'collision_model': self.collision_model} if self.collision_model else {}),
                            child_env=self.child_env(),
                            progress=(lambda report: progress([ExecutionStep(
                                command_id=row["command_id"], skill_name=row["skill_name"],
                                status=row["status"], error_code=row["error_code"],
                                detail=row["detail"]) for row in feedback.steps(report, describe)]))
                            if progress else None)
        # The reduction reads poses back by object name, and only the scene
        # document carries those names: ``workspace.build`` returns the stamped
        # task document, which would reduce every moved object to nothing.
        with span("control.feedback_parse", component="bridge", source="adapters/subprocess_execution.py:SubprocessExecutionAdapter.run"):
            # ``header`` is the unique ASCII transport document handed to the
            # control process.  Feedback reduction must therefore use those
            # names as well; restoring directly to the user's display names
            # here makes the active robot/base name differ from ``header`` and
            # causes complete_state() to report a missing final pose.  The
            # public final_scene is restored separately below.
            feedback_mapping = [dict(row, original_name=row.get("transport_name"),
                                     source_name=row.get("transport_name"))
                                for row in name_mapping]
            restore_runtime_state_names(result.report, feedback_mapping)
            final_scene_path = getattr(result, "final_scene_path", None)
            if final_scene_path is not None:
                restore_final_scene_names(final_scene_path, name_mapping)
            summary = feedback.summarize(result, header, describe)
        if summary.get("final_scene") is not None:
            original_names = {item["object_id_in_scene"]: item["object_name_in_scene"]
                              for item in source_header["objects"]}
            for item in summary["final_scene"]["objects"]:
                item["object_name_in_scene"] = original_names[item["object_id_in_scene"]]
        # Only the report for this exact request can certify a pre-execution rejection.
        summary["no_effect_verified"] = (summary.get("no_effect_verified") is True
                                         and result.report.get("request_id") == commands.request_id)
        if summary["ok"] and not summary.get("state_verified"):
            summary.update(ok=False, error_code="execution_final_state_incomplete",
                           detail="控制端报告命令完成，但没有完整可恢复的最终关节、物体或持物状态；请核验后继续。")
        return self.outcome(summary, result)

    @staticmethod
    def outcome(summary: dict, result) -> ExecutionOutcome:
        return ExecutionOutcome(
            ok=summary["ok"],
            steps=[ExecutionStep(command_id=step["command_id"], skill_name=step["skill_name"],
                                 status=step["status"], error_code=step["error_code"],
                                 detail=step["detail"]) for step in summary["steps"]],
            moved=summary["moved"], holding_object=summary["holding_object"],
            articulated_joints=summary.get("articulated_joints", {}),
            active_joint_ids=summary.get("active_joint_ids", []),
            state_verified=summary.get("state_verified", False),
            no_effect_verified=summary.get("no_effect_verified", False),
            final_scene=summary.get("final_scene"), final_scene_path=summary.get("final_scene_path"),
            traj_path=summary["traj_path"], error_code=summary["error_code"], detail=summary["detail"])
