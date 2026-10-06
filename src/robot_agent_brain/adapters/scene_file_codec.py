import json
from pathlib import Path
from pydantic import ValidationError
from ..contracts.scene import SceneConfig
from ..errors import BrainError


class SceneFileCodec:
    """Brain-native flat scene format only. Never edits an input file."""
    def __init__(self, assets):
        self.assets = assets

    def load(self, path):
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"),
                              parse_constant=lambda value: (_ for _ in ()).throw(ValueError("non-finite JSON")))
        except (OSError, UnicodeError, ValueError) as exc:
            raise BrainError("scene_file_invalid", "scene_import", str(exc)) from exc
        if not isinstance(data, dict) or "components" in data or data.get("schema_version") != "1.0":
            raise BrainError("scene_schema_unsupported", "scene_import", "Expected Brain flat SceneConfig version 1.0")
        try:
            scene = SceneConfig.model_validate(data)
            for obj in scene.objects:
                self.assets.get_model_property(obj.asset_id)
        except (ValidationError, LookupError) as exc:
            raise BrainError("scene_file_invalid", "scene_import", str(exc)) from exc
        return scene

    @staticmethod
    def payload(scene):
        scene = SceneConfig.model_validate(scene.model_dump())
        value = scene.model_dump(mode="json")
        json.dumps(value, allow_nan=False)
        return value
