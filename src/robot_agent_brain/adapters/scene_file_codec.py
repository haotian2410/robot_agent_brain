import json
from pathlib import Path
from pydantic import ValidationError
from ..contracts.scene import SceneConfig, parse_scene_document
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
        return self.decode(data)

    def decode(self, data):
        if not isinstance(data, dict) or type(data.get("scene_schema_version")) is not int or data["scene_schema_version"] != 1:
            raise BrainError("scene_schema_unsupported", "scene_import", "Expected shared component Scene version 1")
        try:
            document = parse_scene_document(data, uint32=False)
            scene = document.view
        except (ValidationError, LookupError, ValueError) as exc:
            raise BrainError("scene_file_invalid", "scene_import", str(exc)) from exc
        if getattr(self.assets, "typed_namespaces", False):
            for obj in scene.objects:
                for component in obj.components:
                    if component.component_type == "MetadataRef":
                        props = component.properties
                        if props.get("path"):
                            try:
                                self.assets.resolve(props["path"], props.get("type"))
                            except (KeyError, LookupError):
                                # Resource resolution is separate from the
                                # lossless Scene protocol; unresolved assets
                                # remain visible to downstream diagnostics.
                                pass
                            except ValueError as exc:
                                # A typed asset library cannot safely infer a
                                # namespace when a numeric id is shared by a
                                # model and a robot.  Preserve the explicit
                                # protocol error instead of silently accepting
                                # an ambiguous MetadataRef.
                                raise BrainError("scene_file_invalid", "scene_import", str(exc)) from exc
        return scene

    @staticmethod
    def payload(scene):
        if hasattr(scene, "raw_document") and getattr(scene, "_raw_document", None) is not None:
            value = scene.raw_document()
        else:
            scene = SceneConfig.model_validate(scene.model_dump())
            value = scene.model_dump(mode="json")
        json.dumps(value, allow_nan=False)
        return value
