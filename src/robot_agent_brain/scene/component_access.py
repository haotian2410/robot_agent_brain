"""Read-only typed component access; retains one canonical Scene object."""
from ..contracts.scene import COMPONENT_PROPERTIES


class SceneIndex:
    def __init__(self, scene):
        self.scene = scene
        self._objects = {obj.object_id_in_scene: obj for obj in scene.objects}

    def object(self, identifier):
        try:
            return self._objects[identifier]
        except KeyError as exc:
            raise LookupError(f"scene_object_missing: {identifier}") from exc

    def component(self, identifier, component_type):
        return next((c for c in self.object(identifier).components if c.component_type == component_type), None)

    def properties(self, identifier, component_type):
        component = self.component(identifier, component_type)
        if component is None:
            return None
        model = COMPONENT_PROPERTIES[component_type]
        try:
            return model.model_validate(component.properties)
        except Exception:
            # Web Scene v1 is intentionally lossless and permissive.  Keep
            # malformed/unknown fields in the raw component while exposing a
            # safe typed view with component defaults to Brain algorithms.
            values = {}
            for name, field in model.model_fields.items():
                if name in component.properties:
                    values[name] = component.properties[name]
                elif not field.is_required():
                    values[name] = field.default_factory() if field.default_factory is not None else field.default
                else:
                    values[name] = None
            return model.model_construct(**values)

    def transform(self, identifier):
        return self.properties(identifier, "Transform")

    def metadata_ref(self, identifier):
        value = self.properties(identifier, "MetadataRef")
        return value.path if value is not None else None

    def metadata_ref_properties(self, identifier):
        return self.properties(identifier, "MetadataRef")

    def metadata_type(self, identifier):
        value = self.metadata_ref_properties(identifier)
        return value.type if value is not None else None

    def semantic(self, identifier):
        return self.properties(identifier, "Semantic")

    def robot_driver(self, identifier):
        return self.properties(identifier, "RobotDriver")

    def semantic_objects(self):
        return [obj for obj in self.scene.objects if self.component(obj.object_id_in_scene, "Semantic") is not None]
