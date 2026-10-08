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
        return COMPONENT_PROPERTIES[component_type].model_validate(component.properties)

    def transform(self, identifier):
        return self.properties(identifier, "Transform")

    def metadata_ref(self, identifier):
        value = self.properties(identifier, "MetadataRef")
        return value.path if value is not None else None

    def semantic(self, identifier):
        return self.properties(identifier, "Semantic")

    def robot_driver(self, identifier):
        return self.properties(identifier, "RobotDriver")

    def semantic_objects(self):
        return [obj for obj in self.scene.objects if self.component(obj.object_id_in_scene, "Semantic") is not None]
