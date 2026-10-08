import pytest

from robot_agent_brain.config import LayoutDefaults
from robot_agent_brain.contracts.asset_library import BrainAssetView
from robot_agent_brain.contracts.scene import RobotDriverProperties
from robot_agent_brain.contracts.task_intent import TaskEntity, TaskIntent
from robot_agent_brain.contracts.turn import BrainTurn
from robot_agent_brain.scene.bootstrapper import SceneBootstrapper
from robot_agent_brain.scene.asset_resolver import AssetResolver
from robot_agent_brain.scene.component_access import SceneIndex
from robot_agent_brain.scene.geometry import world_bounds
from robot_agent_brain.scene.scene_graph import world_transform, WorldTransform
from robot_agent_brain.scene.scene_layout import SceneLayoutPolicy
from test_component_geometry import geometry, IDENTITY


class FixtureLibrary:
    """Explicit test-only resources; never production library registrations."""
    def __init__(self):
        self.models = [
            BrainAssetView(library_asset_id=900, metadata_ref="fixture://table", semantic_name="table",
                category="surface", dimensions_m=(2, 2, .1),
                local_aabb_min_m=(-1, -1, -.05), local_aabb_max_m=(1, 1, .05)),
            BrainAssetView(library_asset_id=901, metadata_ref="fixture://robot", semantic_name="robot",
                dimensions_m=(.1, .1, .1), local_aabb_min_m=(0, 0, 0), local_aabb_max_m=(.1, .1, .1)),
            BrainAssetView(library_asset_id=16, metadata_ref="fixture://tool", semantic_name="screwdriver",
                category="tool", **geometry(16).model_dump()),
        ]

    def resolve(self, reference):
        return next(model for model in self.models if model.metadata_ref == reference)

    def find_by_name(self, name):
        return [model for model in self.models if model.semantic_name == name]

    def find_by_category(self, category):
        return [model for model in self.models if model.category == category]


def turn():
    return BrainTurn(status="accepted", turn_kind="robot_task", instruction="两个螺丝刀",
        task_intent=TaskIntent(instruction="两个螺丝刀", operations=[],
            entities=[TaskEntity(entity_id="tools", semantic_name="screwdriver", category="tool",
                                 count=2, quantity_mode="all")]))


def configured(library):
    return SceneBootstrapper(library, LayoutDefaults(), table_metadata_ref="fixture://table",
        robot_metadata_ref="fixture://robot",
        robot_driver=RobotDriverProperties(joint_sequence=["j1"], joint_limits={"j1": (-1., 1.)}))


def test_bootstrap_requires_actual_platform_resource_configuration():
    with pytest.raises(ValueError, match="bootstrap_config_missing"):
        SceneBootstrapper(FixtureLibrary(), LayoutDefaults()).prepare(turn(), scene_id=0)


def test_bootstrap_offset_models_exact_components_counts_and_support():
    library = FixtureLibrary()
    result = configured(library).prepare(turn(), scene_id=0)
    scene = result.scene
    index = SceneIndex(scene)
    assert len(scene.objects) == 4
    assert result.entity_candidates == {"tools": [2, 3]}
    assert result.asset_bindings == {"tools": "fixture://tool"}
    assert index.robot_driver(1).joint_limits == {"j1": (-1, 1)}
    assert scene.scene_id == 0
    boxes = []
    for identifier in (2, 3):
        assert index.metadata_ref(identifier) == "fixture://tool"
        assert index.semantic(identifier).support == 0
        assert index.transform(identifier).parent is None
        assert {c.component_type for c in index.object(identifier).components} == {"Transform", "MetadataRef", "Semantic"}
        box = world_bounds(library.resolve("fixture://tool"), world_transform(scene, identifier))
        assert box[0][2] == pytest.approx(.025)
        assert -.75 <= box[0][0] < box[1][0] <= .75
        assert -.55 <= box[0][1] < box[1][1] <= .55
        boxes.append(box)
    assert any(boxes[0][1][i] + .04 <= boxes[1][0][i] or boxes[1][1][i] + .04 <= boxes[0][0][i]
               for i in (0, 1))
    assert configured(library).prepare(turn(), scene_id=0) == result


def test_asset_alias_and_ambiguous_category_never_pick_randomly():
    library = FixtureLibrary()
    entity = TaskEntity(entity_id="tool", semantic_name="螺丝刀", category="tool")
    assert AssetResolver(library, aliases={"螺丝刀": "screwdriver"}).resolve(entity).model.library_asset_id == 16
    library.models.append(library.models[-1].model_copy(update={"library_asset_id": 19, "metadata_ref": "fixture://second"}))
    with pytest.raises(ValueError, match="asset_ambiguous"):
        AssetResolver(library).resolve(entity.model_copy(update={"category_only": True}))


@pytest.mark.parametrize("relation,axis,sign", [
    ("left_of", 0, -1), ("right_of", 0, 1), ("front_of", 1, 1),
    ("behind", 1, -1), ("above", 2, 1), ("below", 2, -1),
])
def test_relative_layout_uses_measured_offset_bounds(relation, axis, sign):
    reference, target = geometry(4), geometry(16)
    ref_world = WorldTransform((.2, .3, .4), IDENTITY)
    obj_world = WorldTransform((0, 0, .8), IDENTITY)
    result = SceneLayoutPolicy(.03).relative_transform(relation, ref_world, reference, target, obj_world)
    low, high = world_bounds(target, result)
    rlow, rhigh = world_bounds(reference, ref_world)
    gap = low[axis] - rhigh[axis] if sign > 0 else rlow[axis] - high[axis]
    assert gap == pytest.approx(.03)
    if axis != 2:
        assert result.position[2] == .8
