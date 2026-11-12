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


def _arm(object_id, asset_name):
    return SceneObject(object_id_in_scene=object_id,
        object_name_in_scene="arm", components=[
            SceneComponent(component_type="Transform", properties={"position": [0, 0, 0],
                "quaternion_xyzw": [0, 0, 0, 1], "scale": [1, 1, 1], "parent": None}),
            SceneComponent(component_type="MetadataRef", properties={"path": "$LIBRARY_SERVER/8", "type": "robot"}),
            SceneComponent(component_type="Semantic", properties={"semantic_name": asset_name,
                "category": "robot", "support": None}),
            SceneComponent(component_type="RobotDriver", properties={"joint_sequence": ["joint1"],
                "joint_limits": {"joint1": [-1, 1]}}),
        ])


def _scene(asset_name, object_id=2):
    return SceneConfig(scene_schema_version=1, scene_id=1, scene_version=1,
        scene_name="platform", objects=[_arm(object_id, asset_name)])


@pytest.mark.parametrize("asset_name", ["ur5e_arm", "ur10", "piper", "cr5"])
def test_any_single_arm_reaches_the_controller(asset_name):
    """The control runtime reads the arm model from the scene, so a name is
    never a planning refusal; only an undeclared multi-arm platform is."""
    BrainPipeline(None, _Assets(asset_name), robot="ur5")._validate_robot_platform(_scene(asset_name))


def test_second_arm_requires_an_explicit_profile():
    scene = SceneConfig(scene_schema_version=1, scene_id=1, scene_version=1, scene_name="dual",
        objects=[_arm(2, "ur10"), _arm(3, "ur10")])
    pipeline = BrainPipeline(None, _Assets("ur10"), robot="ur5")
    with pytest.raises(Exception, match="capability_unsupported"):
        pipeline._validate_robot_platform(scene)
    profile = SimpleNamespace(setup=SimpleNamespace(mode="dual"))
    pipeline._validate_robot_platform(scene, robot_profile=profile)
