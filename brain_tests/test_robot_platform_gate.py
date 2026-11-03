from types import SimpleNamespace

import pytest

from robot_agent_brain.pipeline import BrainPipeline
from robot_agent_brain.contracts.scene import SceneComponent, SceneConfig, SceneObject


class _Assets:
    metadata = SimpleNamespace(aliases={}, category_aliases={})

    def __init__(self, name):
        self.name = name

    def resolve(self, _ref, _kind):
        return SimpleNamespace(semantic_name=self.name)


def _scene(asset_name):
    return SceneConfig(scene_schema_version=1, scene_id=1, scene_version=1,
        scene_name="platform", objects=[SceneObject(object_id_in_scene=2,
        object_name_in_scene="arm", components=[
            SceneComponent(component_type="Transform", properties={"position": [0, 0, 0],
                "quaternion_xyzw": [0, 0, 0, 1], "scale": [1, 1, 1], "parent": None}),
            SceneComponent(component_type="MetadataRef", properties={"path": "$LIBRARY_SERVER/8", "type": "robot"}),
            SceneComponent(component_type="Semantic", properties={"semantic_name": asset_name,
                "category": "robot", "support": None}),
            SceneComponent(component_type="RobotDriver", properties={"joint_sequence": ["joint1"],
                "joint_limits": {"joint1": [-1, 1]}}),
        ])])


def test_non_default_robot_is_rejected_before_exporter():
    pipeline = BrainPipeline(None, _Assets("piper"), robot="ur5e")
    with pytest.raises(Exception, match="capability_unsupported"):
        pipeline._validate_robot_platform(_scene("piper"))


def test_matching_ur5e_arm_is_allowed():
    pipeline = BrainPipeline(None, _Assets("ur5e_arm"), robot="ur5e")
    pipeline._validate_robot_platform(_scene("ur5e_arm"))

