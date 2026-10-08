import json
from pathlib import Path
from pydantic import ValidationError
from ..contracts.scene import SceneConfig
from ..errors import BrainError


class SceneFileCodec:
    """Exact shared component Scene v1. Resource resolution is a separate step."""
    def __init__(self, assets=None):
        self.assets = assets

    def load(self, path):
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"),
                              parse_constant=lambda value: (_ for _ in ()).throw(ValueError("non-finite JSON")))
        except (OSError, UnicodeError, ValueError) as exc:
            raise BrainError("scene_file_invalid", "scene_import", str(exc)) from exc
        if not isinstance(data, dict) or type(data.get("scene_schema_version")) is not int or data["scene_schema_version"] != 1:
            raise BrainError("scene_schema_unsupported", "scene_import", "Expected shared component Scene version 1")
        try:
            scene = SceneConfig.model_validate(data)
        except (ValidationError, LookupError) as exc:
            raise BrainError("scene_file_invalid", "scene_import", str(exc)) from exc
        return scene

    @staticmethod
    def payload(scene):
        scene = SceneConfig.model_validate(scene.model_dump())
        value = scene.model_dump(mode="json")
        json.dumps(value, allow_nan=False)
        return value
