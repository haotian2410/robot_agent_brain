import pytest

from robot_agent_brain.config import BrainConfig
from robot_agent_brain.contracts.asset_library import BrainAssetView
from robot_agent_brain.contracts.task_intent import TaskEntity
from robot_agent_brain.contracts.turn import SceneEditIntent
from robot_agent_brain.scene.asset_resolver import AssetResolver
from robot_agent_brain.scene.scene_layout import SceneLayoutPolicy
from robot_agent_brain.scene.scene_graph import WorldTransform


class AmbiguousAssets:
    typed_namespaces = True
    supports_features = True
    demo_assets = False

    def __init__(self):
        self.baskets = [
            BrainAssetView(library_asset_id=4, metadata_ref="$LIBRARY_SERVER/4", semantic_name="basket",
                           category="container", dimensions_m=(.2, .2, .2),
                           local_aabb_min_m=(-.1, -.1, -.1), local_aabb_max_m=(.1, .1, .1), tags=("blue",)),
            BrainAssetView(library_asset_id=12, metadata_ref="$LIBRARY_SERVER/12", semantic_name="basket",
                           category="container", dimensions_m=(.2, .2, .2),
                           local_aabb_min_m=(-.1, -.1, -.1), local_aabb_max_m=(.1, .1, .1), tags=("white",)),
        ]

    def find_by_name(self, name):
        return list(self.baskets) if name == "basket" else []

    def find_by_category(self, category):
        return list(self.baskets) if category == "container" else []

    def resolve(self, ref, asset_type=None):
        return next(item for item in self.baskets if item.metadata_ref == ref)


def test_legacy_position_hint_normalizes_to_center_and_unknown_props_reject():
    intent = SceneEditIntent(operation="add", target="apple", relation="on", reference="table",
                             properties={"position_hint": "center"})
    assert intent.placement_hint == "center" and intent.properties == {}
    with pytest.raises(ValueError, match="scene_edit_properties_unsupported"):
        SceneEditIntent(operation="add", target="apple", relation="on", reference="table",
                        properties={"position_hint": "somewhere"})


def test_model_default_any_placement_hint_is_ignored_for_non_placement_ops():
    """Qwen's placement default must not invalidate move/property edits."""
    moved = SceneEditIntent(operation="translate", target="apple", direction="left",
                            distance_m=.05, placement_hint="any")
    assert moved.placement_hint is None
    rotated = SceneEditIntent(operation="rotate", target="apple", axis="z", angle_deg=90,
                              placement_hint="any")
    assert rotated.placement_hint is None
    with pytest.raises(ValueError, match="scene_edit_fields_forbidden: translate"):
        SceneEditIntent(operation="translate", target="apple", direction="left",
                        distance_m=.05, placement_hint="center")


def test_default_asset_is_only_used_for_ambiguous_scene_add():
    entity = TaskEntity(entity_id="basket", semantic_name="basket", category="container")
    binding = AssetResolver(AmbiguousAssets(), default_refs={"basket": "$LIBRARY_SERVER/4"}).resolve(
        entity, allow_default=True)
    assert binding.model.library_asset_id == 4
    assert any(item.startswith("source=default_asset:") for item in binding.assumptions)
    with pytest.raises(ValueError, match="asset_ambiguous"):
        AssetResolver(AmbiguousAssets()).resolve(entity)
    blue = entity.model_copy(update={"color": "blue"})
    assert AssetResolver(AmbiguousAssets(), default_refs={"basket": "$LIBRARY_SERVER/4"}).resolve(
        blue, allow_default=True).model.library_asset_id == 4


def test_surface_grid_has_multiple_xy_candidates_and_region_filter():
    policy = SceneLayoutPolicy()
    reference = WorldTransform((0., 0., 0.), ((1., 0., 0.), (0., 1., 0.), (0., 0., 1.)))
    asset = BrainAssetView(library_asset_id=1, metadata_ref="$LIBRARY_SERVER/1", semantic_name="table",
                           category="surface", dimensions_m=(1., 1., .1),
                           local_aabb_min_m=(-.5, -.5, 0.), local_aabb_max_m=(.5, .5, .1))
    object_asset = BrainAssetView(library_asset_id=2, metadata_ref="$LIBRARY_SERVER/2", semantic_name="tray",
                                  category="container", dimensions_m=(.2, .2, .1),
                                  local_aabb_min_m=(-.1, -.1, 0.), local_aabb_max_m=(.1, .1, .1))
    candidates = policy.surface_candidates(reference, asset, object_asset, reference,
                                           workspace_min=(-.45, -.45), workspace_max=(.45, .45))
    assert len(candidates) > 1
    right = policy.surface_candidates(reference, asset, object_asset, reference, region="right_half")
    assert right and all(candidate.position[0] >= 0 for candidate in right)
    center = policy.surface_candidates(reference, asset, object_asset, reference, center_only=True)
    assert len(center) == 1


def test_web_config_contains_scene_add_defaults():
    config = BrainConfig.load("config/webeditor.json")
    assert config.default_scene_edit_assets["basket"] == "$LIBRARY_SERVER/4"
    assert config.default_scene_edit_assets["tray"] == "$LIBRARY_SERVER/17"
    assert set(config.default_scene_edit_assets) == {
        "apple", "banana", "baseball", "basket", "pen", "screwdriver", "gum_bottle", "cream",
        "marker", "test_tube_rack", "mug", "rubiks_cube", "school_bell", "tray", "coffee_table",
        "sugar_box", "test_tube", "doll", "drawer", "cabinet", "table", "microwave", "bottle",
        "button", "can",
    }
