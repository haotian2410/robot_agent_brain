import json
import math
import pytest
from jsonschema import Draft202012Validator
from robot_agent_brain.config import BrainConfig
from robot_agent_brain.contracts.scene import SceneConfig, SceneComponent
from robot_agent_brain.contracts.commands import CommandsFile
from robot_agent_brain.contracts.turn import SceneEditIntent, SceneEditPlan
from robot_agent_brain.scene.editor import SceneEditor
from test_export_roundtrip import wire
from test_query_scene_continuity import supported_scene, set_transform


@pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf])
def test_nonfinite_nested_properties_fail_before_scene_commit(value):
    with pytest.raises(ValueError, match="finite_number"):
        SceneComponent(component_type="Sensor", properties={"nested":{"values":[value]}})


@pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf])
def test_nonfinite_displacement_fails_model_and_independent_wire_decode(value):
    payload = wire("move", {"target":0, "motion_direction":"right", "distance_m":value})
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
    payload = {"scene_schema_version":9, "scene_id":1, "scene_version":0, "scene_name":"s", "objects":[]}
    with pytest.raises(ValueError):
        SceneConfig.model_validate(payload)
    assert not Draft202012Validator(SceneConfig.model_json_schema()).is_valid(payload)


def test_relative_add_exhausts_workspace_without_changing_reference():
    config = BrainConfig()
    assets, defaults = config.load_assets(), config.load_defaults()
    defaults.max_attempts = 4
    scene = supported_scene()
    scene.objects.pop()
    set_transform(scene, 1, position=(defaults.workspace_max[0]-.01, 0, .045))
    original = scene.model_dump()
    with pytest.raises(ValueError, match="scene_edit_layout_collision"):
        SceneEditor(assets).edit(SceneEditPlan(entities=[dict(entity_id="target", semantic_name='banana', category='fruit', count=1, quantity_mode='single'), dict(entity_id="reference", semantic_name='apple', category="fruit")], operations=[SceneEditIntent(operation='add', relation='right_of', target="target", reference="reference")]), scene, defaults=defaults)
    assert scene.model_dump() == original


def test_collision_resolution_preserves_behind_relation():
    config = BrainConfig()
    assets = config.load_assets()
    scene = supported_scene()
    scene.objects.pop()
    set_transform(scene, 1, position=(0, 0, .045))
    patch = SceneEditor(assets).edit(SceneEditPlan(entities=[dict(entity_id="target", semantic_name='banana', category='fruit', count=3, quantity_mode='all'), dict(entity_id="reference", semantic_name='apple', category="fruit")], operations=[SceneEditIntent(operation='add', relation='behind', target="target", reference="reference")]), scene)
    added = [op for op in patch.operations if op.action == "add_object"]
    assert len(added) == 3
    assert all(op.object.components[0].properties["position"][1] < 0 for op in added)
    assert len({tuple(op.object.components[0].properties["position"]) for op in added}) == 3
