import json
import math
import pytest
from support_fixtures import add_table
from jsonschema import Draft202012Validator
from robot_agent_brain.config import BrainConfig
from robot_agent_brain.contracts.scene import SceneConfig, SceneObject, Transform
from robot_agent_brain.contracts.commands import CommandsFile
from robot_agent_brain.contracts.turn import SceneEditIntent
from robot_agent_brain.scene.editor import SceneEditor
from test_export_roundtrip import wire


@pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf])
def test_nonfinite_nested_properties_fail_before_scene_commit(value):
    with pytest.raises(ValueError, match="finite JSON"):
        SceneObject(scene_object_id="a", asset_id="a", semantic_name="apple", category="fruit",
                    properties={"nested":{"values":[value]}})


@pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf])
def test_nonfinite_displacement_fails_model_and_independent_wire_decode(value):
    payload = wire("move", {"target":"a", "motion_direction":"right", "distance_m":value})
    with pytest.raises(ValueError):
        CommandsFile.model_validate(payload)
    # A wire file must be JSON before JSON Schema applies. Python's default
    # json.loads accepts NaN/Infinity extensions, which are not valid JSON.
    def invalid_constant(token):
        raise ValueError("non-finite JSON constant: " + token)
    with pytest.raises(ValueError, match="non-finite"):
        parsed = json.loads(json.dumps(payload), parse_constant=invalid_constant)
        Draft202012Validator(CommandsFile.model_json_schema()).validate(parsed)


def test_native_schema_version_is_fixed_in_model_and_public_schema():
    payload = {"scene_id":"s", "schema_version":"9.9"}
    with pytest.raises(ValueError):
        SceneConfig.model_validate(payload)
    assert not Draft202012Validator(SceneConfig.model_json_schema()).is_valid(payload)


def test_relative_add_exhausts_workspace_without_changing_reference():
    config = BrainConfig()
    assets, defaults = config.load_assets(), config.load_defaults()
    defaults.max_attempts = 4
    scene = SceneConfig(scene_id="s", objects=[SceneObject(scene_object_id="a", semantic_name="apple", category="fruit",
        asset_id="demo_apple", transform=Transform(position=(defaults.workspace_max[0]-.01,0,.1)))])
    add_table(scene, assets)
    original = scene.model_dump()
    with pytest.raises(ValueError, match="bootstrap_layout_failed"):
        SceneEditor(assets).edit(SceneEditIntent(operation="add", semantic_name="banana", category="fruit",
                                               relation="right_of", reference="a"), scene, defaults=defaults)
    assert scene.model_dump() == original


def test_collision_resolution_preserves_behind_relation():
    config = BrainConfig()
    assets = config.load_assets()
    scene = SceneConfig(scene_id="s", objects=[SceneObject(scene_object_id="a", semantic_name="apple", category="fruit",
        asset_id="demo_apple", transform=Transform(position=(0,0,.1)))])
    add_table(scene, assets)
    patch = SceneEditor(assets).edit(SceneEditIntent(operation="add", semantic_name="banana", category="fruit", count=3,
                                                   relation="behind", reference="a"), scene)
    added = [op for op in patch.operations if op.action == "add"]
    assert len(added) == 3
    assert all(op.object.transform.position[1] < 0 for op in added)
    assert len({op.object.transform.position for op in added}) == 3
