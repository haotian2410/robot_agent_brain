import json
import re
import shutil
import tempfile
from pathlib import Path
from jsonschema import Draft202012Validator
from ..contracts.commands import CommandsFile, canonical_commands
from ..contracts.scene import SceneConfig
from ..contracts.run_report import BrainRunReport
from .scene_file_codec import SceneFileCodec


def safe_identifier(value):
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,99}", value):
        raise ValueError("unsafe_artifact_identifier")
    return value


class ArtifactWriter:
    """Publish a new request directory; never reuse a previous delivery."""
    def __init__(self, root):
        self.root = Path(root).resolve()

    @staticmethod
    def _write(path, value, schema=None):
        if schema is not None:
            Draft202012Validator(schema).validate(value)
        path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
        readback = json.loads(path.read_text(encoding="utf-8"))
        if schema is not None:
            Draft202012Validator(schema).validate(readback)
        if readback != value:
            raise ValueError("artifact_readback_mismatch")

    def publish(self, report, *, scene=None, result=None, request_record=None, debug=None):
        parent = self.root / safe_identifier(report.session_id)
        parent.mkdir(parents=True, exist_ok=True)
        if parent.resolve().parent != self.root:
            raise ValueError("artifact_path_escape")
        destination = parent / safe_identifier(report.request_id)
        if destination.exists():
            raise ValueError("artifact_request_already_exists")
        staged = Path(tempfile.mkdtemp(prefix=".staging-", dir=parent))
        artifacts = {}
        try:
            if scene is not None:
                self._write(staged / "scene_config.json", SceneFileCodec.payload(scene), SceneConfig.model_json_schema())
                artifacts["scene_config"] = str(destination / "scene_config.json")
            if result is not None and report.run_status == "success":
                if result.commands is not None:
                    if scene is None or (result.commands.scene_id, result.commands.scene_version) != (scene.scene_id, scene.scene_version):
                        raise ValueError("artifact_scene_commands_mismatch")
                    self._write(staged / "commands.json", canonical_commands(result.commands), CommandsFile.model_json_schema())
                    artifacts["commands"] = str(destination / "commands.json")
                for key in ("scene_patch", "scene_query_result"):
                    value = getattr(result, key)
                    if value is not None:
                        name = "query_result" if key == "scene_query_result" else key
                        self._write(staged / (name + ".json"), value.model_dump(mode="json"), type(value).model_json_schema())
                        artifacts[name] = str(destination / (name + ".json"))
            self._write(staged / "request_record.json", request_record or {})
            if debug:
                directory = staged / "debug"
                directory.mkdir()
                for name, value in debug.items():
                    if name not in {"brain_turn", "task_intent", "grounded_task", "skill_plan", "model_calls", "raw_model_response", "traceback"}:
                        raise ValueError("artifact_debug_name_invalid")
                    if isinstance(value, str):
                        (directory / (name + ".txt")).write_text(value, encoding="utf-8")
                    else:
                        self._write(directory / (name + ".json"), value)
                artifacts["debug"] = str(destination / "debug")
            published = report.model_copy(update={"artifacts": artifacts})
            self._write(staged / "result.json", published.model_dump(mode="json"), BrainRunReport.model_json_schema())
            staged.rename(destination)
            return published
        finally:
            if staged.exists():
                shutil.rmtree(staged)
