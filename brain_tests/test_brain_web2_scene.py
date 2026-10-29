import json
from pathlib import Path

from robot_agent_brain.contracts.scene import parse_scene_document
from robot_agent_brain.web.protocol import PROTOCOL_VERSION, digest, validate_web_scene


ROOT = Path(__file__).resolve().parents[1]


def test_protocol_version_and_real_scene_documents():
    assert PROTOCOL_VERSION == "brain-web/2"
    for name in ("ur5e_table_sorting.json", "piper_r_table_twist.json"):
        raw = json.loads((ROOT / "docs/docs/执行包" / name).read_text(encoding="utf-8"))
        document = parse_scene_document(raw)
        assert document.view.scene_id == raw["scene_id"]
        assert document.view.scene_version == raw["scene_version"]
        assert document.rejected_objects == []
        assert validate_web_scene(raw).objects


def test_raw_digest_is_not_rewritten_by_view_defaults():
    raw = {
        "scene_schema_version": 1,
        "scene_id": 7,
        "scene_version": 0,
        "scene_name": "minimal",
        "objects": [{
                "object_id_in_scene": 1,
                "object_name_in_scene": "empty",
                "components": [{
                    "component_type": "Transform",
                    "properties": {},
                }, {
                    "component_type": "MeshRenderer",
                    "properties": {"note": "keep", "forceOverrideColor": "#FFFFFF"},
                }],
        }],
    }
    document = parse_scene_document(raw)
    assert document.raw == raw
    assert digest(document) == digest(raw)
    assert document.view.scene_sub_version == 0
    assert document.view.objects[0].components[1].properties["note"] == "keep"


def test_sub_version_changes_digest_without_scene_version_change():
    raw = {
        "scene_schema_version": 1, "scene_id": 1, "scene_version": 2,
        "scene_name": "s", "objects": [], "scene_sub_version": 2,
    }
    no_sub = dict(raw)
    no_sub.pop("scene_sub_version")
    assert digest(raw) != digest(no_sub)
    assert parse_scene_document(raw).view.scene_sub_version == 2
    assert parse_scene_document(no_sub).view.scene_sub_version == 0


def test_bad_parent_rejects_subtree_by_submission_index():
    raw = {
        "scene_schema_version": 1, "scene_id": 1, "scene_version": 0,
        "scene_name": "s",
        "objects": [
            {"object_id_in_scene": 2, "components": [{"component_type": "Transform", "properties": {"parent": 99}}]},
            {"object_id_in_scene": 3, "components": [{"component_type": "Transform", "properties": {"parent": 2}}]},
        ],
    }
    document = parse_scene_document(raw)
    assert {item["index"] for item in document.rejected_objects} == {0, 1}
