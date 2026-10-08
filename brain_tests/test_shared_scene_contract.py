import json
import math
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, ValidationError as SchemaError

from robot_agent_brain.contracts.scene import SceneConfig
from robot_agent_brain.scene.component_access import SceneIndex
from robot_agent_brain.scene.scene_graph import WorldTransform, world_transform, local_from_world


def fixture():
    return json.loads((Path(__file__).parent / "fixtures/shared_scene_v1.json").read_text())


def test_exact_team_fixture_roundtrip_and_public_schema():
    raw = fixture()
    scene = SceneConfig.model_validate(raw)
    assert scene.model_dump(mode="json") == raw
    Draft202012Validator(SceneConfig.model_json_schema()).validate(raw)
    index = SceneIndex(scene)
    assert index.transform(1).parent == index.transform(2).parent == 0
    assert index.metadata_ref(0) == "$LIBRARY_SERVER/<id>"
    assert index.robot_driver(3).joint_sequence == raw["objects"][3]["components"][2]["properties"]["joint_sequence"]
    assert [o.object_id_in_scene for o in index.semantic_objects()] == [0, 5]


def test_unknown_component_properties_preserved():
    raw = fixture()
    raw["objects"][0]["components"].append({"component_type": "Sensor", "properties": {
        "nested": [{"enabled": True, "value": None, "channels": [1, "x", 1.2]}]}})
    assert SceneConfig.model_validate(raw).model_dump(mode="json") == raw


@pytest.mark.parametrize("mutation", ["missing_transform", "duplicate_transform", "duplicate_id", "self_parent",
    "missing_parent", "cycle", "numeric_string", "bool_id", "overflow_id", "extra_asset", "extra_semantic",
    "bad_quaternion", "bad_scale", "missing_joint_limits", "bad_joint_limits", "bad_resolution"])
def test_invalid_shared_scenes_rejected(mutation):
    raw = fixture()
    obj = raw["objects"][0]
    transform = obj["components"][0]["properties"]
    if mutation == "missing_transform":
        obj["components"].pop(0)
    elif mutation == "duplicate_transform":
        obj["components"].append(obj["components"][0])
    elif mutation == "duplicate_id":
        raw["objects"][1]["object_id_in_scene"] = 0
    elif mutation in {"self_parent", "missing_parent", "cycle"}:
        transform["parent"] = {"self_parent": 0, "missing_parent": 999, "cycle": 1}[mutation]
    elif mutation in {"numeric_string", "bool_id", "overflow_id"}:
        raw["scene_id"] = {"numeric_string": "1", "bool_id": True, "overflow_id": 2**53}[mutation]
    elif mutation == "extra_asset":
        obj["asset_id"] = "apple"
    elif mutation == "extra_semantic":
        obj["components"][3]["properties"]["container_membership"] = 5
    elif mutation == "bad_quaternion":
        transform["quaternion_xyzw"] = [0, 0, 0, 0]
    elif mutation == "bad_scale":
        transform["scale"] = [1, 0, 1]
    elif mutation in {"missing_joint_limits", "bad_joint_limits"}:
        driver = raw["objects"][3]["components"][2]["properties"]
        if mutation == "missing_joint_limits":
            driver.pop("joint_limits")
        else:
            driver["joint_limits"]["joint1"] = [2, 1]
    else:
        raw["objects"][2]["components"][1]["properties"]["resolution"] = [0, 480]
    with pytest.raises(ValueError):
        SceneConfig.model_validate(raw)


def test_public_schema_also_rejects_extra_known_properties():
    raw = fixture()
    raw["objects"][0]["components"][1]["properties"]["asset_id"] = 7
    with pytest.raises(SchemaError):
        Draft202012Validator(SceneConfig.model_json_schema()).validate(raw)


def test_world_parent_zero_rotated_scaled_and_local_inverse():
    raw = fixture()
    parent = raw["objects"][0]["components"][0]["properties"]
    parent.update(position=[10, 20, 30], scale=[2, 3, 4], quaternion_xyzw=[0, 0, math.sqrt(.5), math.sqrt(.5)])
    scene = SceneConfig.model_validate(raw)
    world = world_transform(scene, 1)
    assert world.position == pytest.approx((7, 22, 34))
    moved = WorldTransform((8, 22, 34), world.linear)
    local = local_from_world(scene, 1, moved)
    assert local.parent == 0
    assert local.position == pytest.approx((1, 2/3, 1))
    original = local_from_world(scene, 1, world)
    assert original.position == pytest.approx((1, 1, 1))
    assert original.scale == pytest.approx((1, 1, 1))


def test_nonuniform_scale_rotation_keeps_shear_and_roundtrips_local():
    raw = fixture()
    raw["objects"][0]["components"][0]["properties"]["scale"] = [2, 1, 1]
    child = raw["objects"][1]["components"][0]["properties"]
    child["quaternion_xyzw"] = [0, 0, math.sin(math.pi/8), math.cos(math.pi/8)]
    scene = SceneConfig.model_validate(raw)
    world = world_transform(scene, 1)
    with pytest.raises(ValueError, match="shear"):
        world.to_local_properties()
    restored = local_from_world(scene, 1, world)
    assert restored.quaternion_xyzw == pytest.approx(child["quaternion_xyzw"])
    assert restored.scale == pytest.approx((1, 1, 1))
