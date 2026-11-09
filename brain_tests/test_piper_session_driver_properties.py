import copy

import pytest

from robot_agent_brain.adapters.mock_scene_platform import MockScenePlatform
from robot_agent_brain.adapters.scene_file_codec import SceneFileCodec
from robot_agent_brain.config import BrainConfig
from robot_agent_brain.contracts.scene import SceneConfig
from robot_agent_brain.contracts.turn import BrainTurn
from robot_agent_brain.pipeline import BrainPipeline
from robot_agent_brain.scene.component_reference_registry import ComponentReferenceRegistry
from robot_agent_brain.scene.id_remapper import remap_scene
from robot_agent_brain.session.brain_session import BrainSession
from test_component_runtime import object_
from test_query_scene_continuity import supported_scene
from test_scene_replace import plan


def switched_scene(raw=None):
    raw = copy.deepcopy(raw) if raw is not None else supported_scene().model_dump(mode="json")
    # Mirror the two RobotDrivers and the exact six error locations reported.
    for identifier in (3, 4, 5):
        obj = object_(identifier).model_dump(mode="json")
        if identifier in (3, 5):
            obj["components"].extend([
                {"component_type": "LocalAxes", "properties": {}},
                {"component_type": "RobotDriver", "properties": {
                    "joint_sequence": ["joint7"], "joint_limits": {"joint7": [-2, 2]},
                    "available_connect_joints": ["joint7"],
                    "available_connect_link": ["link7"],
                    "position": [[0, 0, 0]], "quaternion_xyzw": [[0, 0, 0, 1]],
                }},
            ])
        raw["objects"].append(obj)
    return raw


def edit_turn():
    return BrainTurn(status="accepted", turn_kind="scene_edit", instruction="move apple",
                     scene_edit=plan([{"operation": "translate", "target": "old",
                                       "direction": "right", "distance_m": 0.03}]))


def test_driver_properties_revalidate_without_losing_ols_connection_data():
    raw = switched_scene()
    assert SceneConfig.model_validate(raw).model_dump(mode="json") == raw
    scene = SceneFileCodec().decode(raw)
    assert ComponentReferenceRegistry().validate_scene(scene).model_dump(mode="json") == raw
    remapped = remap_scene(scene, new_scene_id=2, next_object_id=100)
    for index in (3, 5):
        assert remapped.scene.raw_document()["objects"][index]["components"][2] == raw["objects"][index]["components"][2]


def test_edit_then_arm_switch_then_first_command_in_new_session():
    assets = BrainConfig().load_assets()
    platform1 = MockScenePlatform()
    session1 = BrainSession(None, BrainPipeline(None, assets), platform1)
    session1.initialize_scene(supported_scene())
    session1.process_turn("first-edit", edit_turn())
    scene1 = session1.scene.raw_document()
    raw = switched_scene(scene1)
    raw["scene_id"] = 2
    scene2 = SceneFileCodec().decode(raw)
    platform2 = MockScenePlatform()
    session2 = BrainSession(None, BrainPipeline(None, assets), platform2)
    session2.initialize_scene(scene2)
    session2.process_turn("after-switch", edit_turn())
    assert session2.scene.scene_version == scene2.scene_version + 1
    for index in (3, 5):
        assert platform2.manager.scene.raw_document()["objects"][index] == raw["objects"][index]
    assert session1.scene.raw_document() == scene1


def test_first_edit_can_publish_a_bootstrapped_scene_with_connection_data():
    scene = SceneFileCodec().decode(switched_scene())
    session = BrainSession(None, BrainPipeline(None, BrainConfig().load_assets()), MockScenePlatform())
    result = session.process_initial_edit_turn("initial", edit_turn(), scene,
                                              bindings_override={}, edit_defaults=None)
    assert result.scene_replacement.scene_version == 1


@pytest.mark.parametrize("field,value", [
    ("position", [[0, 0]]), ("quaternion_xyzw", [[0, 0, 1]]),
    ("position", [[float("nan"), 0, 0]]), ("quaternion_xyzw", [[0, 0, 0, float("inf")]]),
    ("unknown_driver_field", True),
])
def test_connection_properties_keep_strict_shape_and_value_validation(field, value):
    raw = switched_scene()
    raw["objects"][3]["components"][2]["properties"][field] = value
    with pytest.raises(ValueError):
        SceneConfig.model_validate(raw)
