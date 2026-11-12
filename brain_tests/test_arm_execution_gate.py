"""S0: single-arm executability is an arm-count question, not a model-name one.

The gate used to refuse every platform outside the UR5 naming family.  The
control runtime resolves the URDF and joint table from the imported scene, so
the Brain now only requires one arm plus a driver that matches the OLS entry it
was assembled from; dual-arm platforms stay behind an explicit RobotProfile.
"""
from types import SimpleNamespace

import pytest

from robot_agent_brain.contracts.scene import SceneComponent, SceneConfig, SceneObject, SceneSnapshot
from robot_agent_brain.session.brain_session import BrainSession


def _arm(object_id, ref, sequence=("joint1",), limits=None):
    return SceneObject(object_id_in_scene=object_id, object_name_in_scene=f"arm{object_id}", components=[
        SceneComponent(component_type="Transform", properties={"position": [0, 0, 0],
            "quaternion_xyzw": [0, 0, 0, 1], "scale": [1, 1, 1], "parent": None}),
        SceneComponent(component_type="MetadataRef", properties={"path": ref, "type": "robot"}),
        SceneComponent(component_type="Semantic", properties={"semantic_name": ref.rsplit("/", 1)[-1],
            "category": "robot", "support": None}),
        SceneComponent(component_type="RobotDriver", properties={"joint_sequence": list(sequence),
            "joint_limits": limits if limits is not None else {name: [-1, 1] for name in sequence}}),
    ])


def _scene(*objects):
    return SceneConfig(scene_schema_version=1, scene_id=1, scene_version=1, scene_name="gate",
                       objects=list(objects))


class _Adapter:
    """Minimal stand-in for ``OlsRobotAssemblyAdapter`` over a declared catalog."""

    def __init__(self, catalog):
        self.catalog = catalog

    def classify_scene(self, scene):
        arms = [(obj.object_id_in_scene, self.catalog[obj.components[1].properties["path"]])
                for obj in scene.objects if obj.components[1].properties.get("type") == "robot"]
        return {"arm": arms, "gripper": [], "camera": [], "prop": []}

    def scene_binding(self, scene):
        classified = self.classify_scene(scene)
        name = classified["arm"][0][1] if len(classified["arm"]) == 1 else None
        return {"robot_asset": name, "gripper_asset": None, "camera_asset": None}

    def resolve(self, name, *, role=None):
        for ref, value in self.catalog.items():
            if value == name:
                return SimpleNamespace(semantic_name=name,
                                       driver={"joint_sequence": ["joint1"], "joint_limits": {"joint1": [-1, 1]}})
        raise ValueError("robot_asset_unknown:" + str(name))


class _Platform:
    def __init__(self):
        self.scene = None
        self.next_object_id = 0

    def load_scene(self, scene, *, change_kind="scene_edit"):
        self.scene = scene
        self.next_object_id = max((item.object_id_in_scene for item in scene.objects), default=-1) + 1
        return SceneSnapshot(scene_id=scene.scene_id, scene_version=scene.scene_version,
                             scene_sub_version=scene.scene_sub_version)

    def adopt(self, scene):
        return self.load_scene(scene)


def _session(scene, robot_asset=...):
    session = BrainSession(scene, SimpleNamespace(robot="ur5"), _Platform())
    session.robot_assembly_adapter = _Adapter({"$LIBRARY_SERVER/6": "ur10", "$LIBRARY_SERVER/8": "piper",
                                               "$LIBRARY_SERVER/1": "ur5"})
    session.robot_asset = (session.robot_assembly_adapter.scene_binding(scene)["robot_asset"]
                           if robot_asset is ... else robot_asset)
    return session


def _turn():
    return SimpleNamespace(turn_kind="robot_task", scene_edit=None, robot_asset_switch=None,
                           robot_setup_request=None, session_control=None,
                           require_legacy_execution=lambda: None)


@pytest.mark.parametrize("ref", ["$LIBRARY_SERVER/6", "$LIBRARY_SERVER/8", "$LIBRARY_SERVER/1"])
def test_any_single_arm_platform_is_supported(ref):
    assert _session(_scene(_arm(2, ref)))._execution_capability_detail() == ("supported", "")


def test_two_arms_require_a_profile():
    """A second arm can arrive through scene edits, after the binding was made."""
    session = _session(_scene(_arm(2, "$LIBRARY_SERVER/6"), _arm(3, "$LIBRARY_SERVER/6")), robot_asset="ur10")
    assert session._execution_capability_detail() == ("unsupported", "single_arm_required: scene_has_2_arms")
    assert session._execution_capability_detail(_scene(_arm(2, "$LIBRARY_SERVER/6"))) == ("supported", "")


def test_driver_must_match_the_platform_it_was_assembled_from():
    drifted = _session(_scene(_arm(2, "$LIBRARY_SERVER/6", sequence=("shoulder_pan_joint",))))
    assert drifted._execution_capability_detail()[1].startswith(
        "joint_sequence_mismatch: scene=shoulder_pan_joint ols=joint1")
    limits = _session(_scene(_arm(2, "$LIBRARY_SERVER/6", limits={"joint1": [-3, 3]})))
    assert limits._execution_capability_detail()[1] == "joint_limits_mismatch: joint1"


def test_refusal_names_the_failed_criterion():
    session = _session(_scene(_arm(2, "$LIBRARY_SERVER/6"), _arm(3, "$LIBRARY_SERVER/6")), robot_asset="ur10")
    session.execution_capability = session._platform_execution_capability()
    with pytest.raises(ValueError, match=r"capability_unsupported: single_arm_required: scene_has_2_arms"):
        session.check_turn(_turn())
