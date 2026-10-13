"""Small generated metadata fixtures: run in CI without shipping raw models."""
import json

import pytest

from robot_agent_brain.adapters.final_models_library import FinalModelsLibraryAdapter
from robot_agent_brain.contracts.scene import TransformProperties, RobotAttachmentProperties
from robot_agent_brain.contracts.task_intent import TaskEntity
from robot_agent_brain.scene.asset_resolver import AssetResolver
from robot_agent_brain.scene.scene_graph import quaternion_matrix


@pytest.fixture
def library(tmp_path):
    cache = {}
    for kind, names in (("model", {"1": "apple", "2": "basket", "3": "basket"}),
                        ("robot", {"1": "ur5e_arm"})):
        folder = tmp_path / ("models" if kind == "model" else "robots")
        folder.mkdir()
        by_name = {}
        for identifier, name in names.items():
            by_name.setdefault(name, []).append(int(identifier))
            directory = folder / identifier
            directory.mkdir()
            data = {"semantic_properties": {"object_id": int(identifier), "object_name": name,
                       "tag": "blue" if identifier == "2" else "red"},
                    "physical_properties": {"mass_kg": .1}, "grasp_properties": {"poses": []}}
            (directory / f"{name}.json").write_text(json.dumps(data))
            cache[f"{kind}:{identifier}"] = {"dimensions_m": [1, 1, 1],
                 "local_aabb_min_m": [0, 0, 0], "local_aabb_max_m": [1, 1, 1]}
        (folder / f"{kind}_index.json").write_text(json.dumps({"by_name": by_name, "by_id": names}))
    cache_path = tmp_path / "cache.json"
    cache_path.write_text(json.dumps(cache))
    return FinalModelsLibraryAdapter(tmp_path, cache_path)


def test_namespaces_and_no_mesh_reads(library):
    # No OBJ/URDF/PNG exists in this fixture. Runtime must use only JSON/cache.
    assert library.resolve("$LIBRARY_SERVER/1", "model").semantic_name == "apple"
    assert library.resolve("$LIBRARY_SERVER/1", "robot").semantic_name == "ur5e_arm"
    for reference, kind in [("$LIBRARY_SERVER/1", None), ("$LIBRARY_SERVER/2", "robot"),
                            ("$LIBRARY_SERVER/1", "bad")]:
        with pytest.raises(ValueError, match="type_required_or_unknown"):
            library.resolve(reference, kind)
    assert library.resolve("$LIBRARY_SERVER/1", "model").physical_properties["mass_kg"] == .1


def test_asset_ambiguity_and_explicit_features(library):
    resolver = AssetResolver(library)
    entity = TaskEntity(entity_id="b", semantic_name="basket", category="container")
    with pytest.raises(ValueError, match="asset_ambiguous"):
        resolver.resolve(entity)
    assert resolver.resolve(entity.model_copy(update={"color": "蓝色"})).model.library_asset_id == 2
    assert resolver.resolve(entity.model_copy(update={"tags": ["red"]})).model.library_asset_id == 3
    with pytest.raises(ValueError, match="asset_feature_missing"):
        resolver.resolve(entity.model_copy(update={"color": "green"}))


def test_quaternion_tolerance_preserves_raw_and_rejects_invalid():
    raw = [0, 0, 0, .99996]
    transform = TransformProperties(position=[0, 0, 0], quaternion_xyzw=raw, scale=[1, 1, 1], parent=None)
    assert list(transform.quaternion_xyzw) == raw
    assert quaternion_matrix(transform.quaternion_xyzw) == ((1, 0, 0), (0, 1, 0), (0, 0, 1))
    with pytest.raises(ValueError, match="quaternion"):
        TransformProperties(position=[0, 0, 0], quaternion_xyzw=[0, 0, 0, 2], scale=[1, 1, 1], parent=None)
    with pytest.raises(ValueError, match="quaternion"):
        RobotAttachmentProperties(parent_object_id=1, parent_joint="j", parent_link="a", child_link="b",
            connection_type="fixed", transform={"position": [0, 0, 0], "quaternion_xyzw": [0, 0, 0, 2],
                                               "reference_frame": "parent_link"})


def test_metadata_changes_affect_fingerprint_without_geometry_rebuild(library):
    from robot_agent_brain.diagnostics import fingerprint
    root=library.root
    cache=root/"cache.json"
    before_cache=cache.read_bytes()
    before=fingerprint(library.configuration_payload())
    metadata=root/"models/1/apple.json"
    data=json.loads(metadata.read_text())
    data["semantic_properties"].update(scalable=True,tag="blue")
    data["physical_properties"]["scale"]=[.5,2]
    metadata.write_text(json.dumps(data))
    updated=FinalModelsLibraryAdapter(root,cache)
    assert fingerprint(updated.configuration_payload())!=before
    assert updated.resolve("$LIBRARY_SERVER/1","model").color_tags==("blue",)
    assert updated.resolve("$LIBRARY_SERVER/1","model").scale_range==(.5,2)
    assert cache.read_bytes()==before_cache
