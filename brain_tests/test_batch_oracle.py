from copy import deepcopy

from robot_agent_brain.batch_oracle import evaluate_turn


def _obj(oid, name, x=0.0, y=0.0, color=None):
    components = [
        {"component_type": "Transform", "properties": {
            "position": [x, y, 0.1], "quaternion_xyzw": [0, 0, 0, 1],
            "scale": [1, 1, 1], "parent": None}},
        {"component_type": "MetadataRef", "properties": {"path": "$LIBRARY_SERVER/1", "type": "model"}},
        {"component_type": "Semantic", "properties": {"semantic_name": name, "category": "fruit", "support": 10}},
    ]
    if color:
        components.append({"component_type": "MeshRenderer", "properties": {"forceOverrideColor": color}})
    return {"object_id_in_scene": oid, "object_name_in_scene": name, "components": components}


def _scene(objects):
    return {"scene_schema_version": 1, "scene_id": 1, "scene_version": 1,
            "scene_sub_version": 0, "scene_name": "fixture", "objects": objects}


def test_oracle_proves_add_and_asset_role_without_using_brain_selector():
    before = _scene([_obj(10, "table")])
    # Make the table discoverable by the independent tabletop rule.
    before["objects"][0]["components"][1]["properties"] = {"path": "$LIBRARY_SERVER/29", "type": "model"}
    before["objects"][0]["components"][2]["properties"] = {"semantic_name": "table", "category": "surface", "support": None}
    after = _scene(before["objects"] + [_obj(11, "apple", 0.2, 0.1)])
    after["objects"][-1]["components"][1]["properties"] = {"path": "$LIBRARY_SERVER/1", "type": "model"}
    expected = {"operation": "add", "target_role": "object_a", "count": 1,
                "asset_selection": "catalog_member", "support": "primary_table"}
    value = evaluate_turn(expected=expected, expected_outcome="scene_updated",
                          before_scene=before, after_scene=after,
                          result={"outcome": "scene_updated", "executed": False},
                          role_mapping={"object_a": {"semantic_name": "apple", "metadata_ref": "$LIBRARY_SERVER/1"}})
    assert value["status"] == "passed", value


def test_oracle_counts_only_requested_role_during_platform_bootstrap():
    # The first empty-scene edit creates the tabletop platform together with
    # the requested object.  Platform IDs must not be counted as user adds.
    before = _scene([])
    table = _obj(1, "table")
    table["components"][1]["properties"] = {"path": "$LIBRARY_SERVER/29", "type": "model"}
    table["components"][2]["properties"] = {"semantic_name": "table", "category": "surface", "support": None}
    marker = _obj(8, "marker", 0.2, 0.1)
    marker["components"][1]["properties"] = {"path": "$LIBRARY_SERVER/10", "type": "model"}
    marker["components"][2]["properties"] = {"semantic_name": "marker", "category": "tool", "support": 1}
    after = _scene([table, marker])
    value = evaluate_turn(
        expected={"operation": "add", "target_role": "object_a", "count": 1,
                  "support": "primary_table"},
        expected_outcome="scene_updated", before_scene=before, after_scene=after,
        result={"outcome": "scene_updated", "executed": False},
        role_mapping={"object_a": {"semantic_name": "marker",
                                    "metadata_ref": "$LIBRARY_SERVER/10",
                                    "type": "model"}},
    )
    assert value["status"] == "passed", value


def test_oracle_filters_platform_bootstrap_for_multi_role_add():
    """A two-object add must not count the bootstrap platform as user data."""
    before = _scene([])
    table = _obj(1, "work_table")
    table["components"][1]["properties"] = {"path": "$LIBRARY_SERVER/29", "type": "model"}
    table["components"][2]["properties"] = {"semantic_name": "work_table", "category": "surface", "support": None}
    pen = _obj(8, "pen", 0.2, 0.1)
    pen["components"][1]["properties"] = {"path": "$LIBRARY_SERVER/6", "type": "model"}
    pen["components"][2]["properties"] = {"semantic_name": "pen", "category": "tool", "support": 1}
    marker = _obj(9, "marker", -0.2, 0.1)
    marker["components"][1]["properties"] = {"path": "$LIBRARY_SERVER/10", "type": "model"}
    marker["components"][2]["properties"] = {"semantic_name": "marker", "category": "tool", "support": 1}
    after = _scene([table, pen, marker])
    value = evaluate_turn(
        expected={"operations": ["add:object_a", "add:object_b"],
                  "counts": {"object_a": 1, "object_b": 1},
                  "support": "primary_table"},
        expected_outcome="scene_updated", before_scene=before, after_scene=after,
        result={"outcome": "scene_updated", "executed": False},
        role_mapping={
            "object_a": {"semantic_name": "pen", "metadata_ref": "$LIBRARY_SERVER/6", "type": "model"},
            "object_b": {"semantic_name": "marker", "metadata_ref": "$LIBRARY_SERVER/10", "type": "model"},
            "surface_1": {"semantic_name": "work_table", "metadata_ref": "$LIBRARY_SERVER/29", "type": "model"},
        },
    )
    assert value["status"] == "passed", value


def test_oracle_catalog_member_allows_unspecified_style_variant():
    """A generic semantic request may choose another real OLS style variant."""
    before = _scene([])
    table = _obj(1, "work_table")
    table["components"][1]["properties"] = {"path": "$LIBRARY_SERVER/29", "type": "model"}
    table["components"][2]["properties"] = {"semantic_name": "work_table", "category": "surface", "support": None}
    selected = _obj(8, "pen", 0.2, 0.1)
    selected["components"][1]["properties"] = {"path": "$LIBRARY_SERVER/5", "type": "model"}
    selected["components"][2]["properties"] = {"semantic_name": "pen", "category": "tool", "support": 1}
    after = _scene([table, selected])
    value = evaluate_turn(
        expected={"operation": "add", "target_role": "object_a", "count": 1,
                  "asset_selection": "catalog_member", "support": "primary_table"},
        expected_outcome="scene_updated", before_scene=before, after_scene=after,
        result={"outcome": "scene_updated", "executed": False},
        role_mapping={"object_a": {"semantic_name": "pen", "metadata_ref": "$LIBRARY_SERVER/6", "type": "model"}},
    )
    assert value["status"] == "passed", value
    assert any(item["name"] == "added_object_asset_catalog_member" for item in value["checks"])


def test_oracle_detects_query_mutating_scene():
    before = _scene([_obj(10, "apple")])
    after = _scene([_obj(10, "apple", 0.1, 0.0)])
    value = evaluate_turn(expected={"route": "scene_query", "scene_unchanged": True},
                          expected_outcome="answered", before_scene=before, after_scene=after,
                          result={"outcome": "answered", "executed": False})
    assert value["status"] == "failed_assertion"
    assert "scene_changed_when_unchanged_expected" in value["errors"]


def test_oracle_keeps_model_and_robot_namespaces_separate():
    table = _obj(10, "table")
    baseball = _obj(11, "baseball", 0.2, 0.1)
    baseball["components"][1]["properties"] = {
        "path": "$LIBRARY_SERVER/3", "type": "model"
    }
    camera = _obj(12, "wrist_camera_d435i", 0.0, 0.0)
    camera["components"][1]["properties"] = {
        "path": "$LIBRARY_SERVER/3", "type": "robot"
    }
    before = _scene([table, baseball, camera])
    after = _scene(deepcopy([table, baseball, camera]))
    after["objects"][1]["components"].append({
        "component_type": "MeshRenderer",
        "properties": {"forceOverrideColor": "#0000FF"},
    })
    value = evaluate_turn(
        expected={"operation": "update_properties", "target_role": "object_a",
                  "color": "blue", "preserve_instance": True},
        expected_outcome="scene_updated", before_scene=before, after_scene=after,
        result={"outcome": "scene_updated", "executed": False},
        role_mapping={"object_a": {"semantic_name": "baseball",
                                    "metadata_ref": "$LIBRARY_SERVER/3",
                                    "type": "model"}},
    )
    assert value["status"] == "passed", value


def test_oracle_classifies_expected_clarification_without_scene_change():
    scene = _scene([_obj(10, "apple")])
    value = evaluate_turn(expected={"required_missing_slot": "selection.reference", "scene_unchanged": True},
                          expected_outcome="clarification_required", before_scene=scene, after_scene=scene,
                          result={"outcome": "clarification_required", "executed": False})
    assert value["status"] == "expected_clarification"


def test_oracle_checks_rotation_axis_and_angle_not_only_changed_quaternion():
    before = _scene([_obj(10, "apple")])
    after = _scene([deepcopy(before["objects"][0])])
    after["objects"][0]["components"][0]["properties"]["quaternion_xyzw"] = [0, 0, 0.70710678, 0.70710678]
    value = evaluate_turn(
        expected={"operation": "rotate", "target_role": "object_a", "axis": "z", "angle_deg": 90,
                  "preserve_instance": True, "non_targets_unchanged": True},
        expected_outcome="scene_updated", before_scene=before, after_scene=after,
        result={"outcome": "scene_updated", "executed": False},
        role_mapping={"object_a": {"semantic_name": "apple", "metadata_ref": "$LIBRARY_SERVER/1", "type": "model"}},
    )
    assert value["status"] == "passed", value


def test_oracle_checks_translation_non_target_axes_and_distance():
    before = _scene([_obj(10, "apple")])
    after = _scene([deepcopy(before["objects"][0])])
    after["objects"][0]["components"][0]["properties"]["position"] = [0.05, 0.0, 0.1]
    value = evaluate_turn(
        expected={"operation": "translate", "target_role": "object_a", "direction": "right",
                  "distance_m": 0.05, "preserve_orientation": True, "non_targets_unchanged": True},
        expected_outcome="scene_updated", before_scene=before, after_scene=after,
        result={"outcome": "scene_updated", "executed": False},
        role_mapping={"object_a": {"semantic_name": "apple", "metadata_ref": "$LIBRARY_SERVER/1", "type": "model"}},
    )
    assert value["status"] == "passed", value


def test_oracle_checks_scale_factor():
    before = _scene([_obj(10, "apple")])
    after = _scene([deepcopy(before["objects"][0])])
    after["objects"][0]["components"][0]["properties"]["scale"] = [1.1, 1.1, 1.1]
    value = evaluate_turn(
        expected={"operation": "scale", "target_role": "object_a", "scale_mode": "multiply",
                  "scale_xyz": [1.1, 1.1, 1.1], "preserve_orientation": True},
        expected_outcome="scene_updated", before_scene=before, after_scene=after,
        result={"outcome": "scene_updated", "executed": False},
        role_mapping={"object_a": {"semantic_name": "apple", "metadata_ref": "$LIBRARY_SERVER/1", "type": "model"}},
    )
    assert value["status"] == "passed", value


def test_oracle_checks_query_count_and_relation_evidence():
    scene = _scene([_obj(10, "apple")])
    value = evaluate_turn(
        expected={"route": "scene_query", "query_type": "count", "count": 1,
                  "scene_unchanged": True},
        expected_outcome="answered", before_scene=scene, after_scene=scene,
        result={"outcome": "answered", "executed": False,
                "query_result": {"query_type": "count", "count": 1}},
    )
    assert value["status"] == "passed", value
