import math
import pytest

from robot_agent_brain.contracts.asset_library import BrainAssetView
from robot_agent_brain.contracts.scene import SceneConfig, SceneComponent
from robot_agent_brain.contracts.task_intent import TaskEntity
from robot_agent_brain.contracts.turn import SceneEditPlan, SceneEditIntent, SceneQueryIntent
from robot_agent_brain.scene.bootstrapper import make_object
from robot_agent_brain.scene.component_access import SceneIndex
from robot_agent_brain.scene.editor import SceneEditor
from robot_agent_brain.scene.scene_manager import SceneManager
from robot_agent_brain.scene.scene_graph import world_transform
from robot_agent_brain.scene.geometry import world_bounds
from robot_agent_brain.scene.colors import ColorResolver, ColorEvidenceResolver
from robot_agent_brain.scene.query import SceneQueryEngine
from robot_agent_brain.config import BrainConfig, LayoutDefaults


class Library:
    def __init__(self):
        self.models = {}
        for name, identifier, dims in [("table", 1, (4., 4., .2)), ("basket", 2, (.2, .2, .2))]:
            self.models[name] = BrainAssetView(library_asset_id=identifier, metadata_ref=name, semantic_name=name,
                dimensions_m=dims, local_aabb_min_m=tuple(-v/2 for v in dims), local_aabb_max_m=tuple(v/2 for v in dims),
                scalable=True, scale_range=(.5, 3), color_tags=("red", "white"))
    def resolve(self, ref, kind=None):
        return self.models[ref]


def fixture():
    library = Library()
    scene = SceneConfig(scene_schema_version=1, scene_id=1, scene_version=1, scene_name="test", objects=[
        make_object(0, "table", "table", (0, 0, -.1), category="surface"),
        make_object(1, "basket", "basket", (0, 0, .1), category="container", support=0)])
    scene.objects[1].components.append(SceneComponent(component_type="Opaque", properties={"data": [1, None]}))
    return library, scene


def plan(*ops, **entity):
    return SceneEditPlan(entities=[TaskEntity(entity_id="b", semantic_name="basket", category="container", **entity)],
                         operations=[SceneEditIntent(target="b", **op) for op in ops])


def apply(library, scene, edit, **kwargs):
    return SceneManager(scene).apply_patch(SceneEditor(library, **kwargs).edit(edit, scene))


@pytest.mark.parametrize("mode,xyz,expected", [
    ("multiply", (1.2,)*3, (1.2,)*3), ("multiply", (.8,)*3, (.8,)*3),
    ("multiply", (1.2,1,1), (1.2,1,1)), ("set", (1.3,1.2,.8), (1.3,1.2,.8))])
def test_scale_preserves_support_and_components(mode, xyz, expected):
    library, scene = fixture()
    changed = apply(library, scene, plan(dict(operation="scale", scale_mode=mode, scale_xyz=xyz)))
    index = SceneIndex(changed)
    assert index.transform(1).scale == expected
    assert world_bounds(library.resolve("basket"), world_transform(changed, 1))[0][2] == pytest.approx(0)
    assert index.transform(1).position[:2] == (0,0)
    assert index.transform(1).quaternion_xyzw == (0,0,0,1)
    assert index.semantic(1).support == 0
    assert index.component(1, "Opaque") == SceneIndex(scene).component(1,"Opaque")
    assert index.metadata_ref(1) == "basket"
    assert changed.scene_version == 2 and scene.scene_version == 1


@pytest.mark.parametrize("direction,amount,value", [("enlarge","small",1.1),("shrink","medium",1/1.5),("enlarge","large",2)])
def test_fuzzy_policy(direction, amount, value):
    library, scene = fixture()
    changed = apply(library, scene, plan(dict(operation="scale", scale_direction=direction, scale_amount=amount)))
    assert SceneIndex(changed).transform(1).scale == pytest.approx((value,)*3)


@pytest.mark.parametrize("value", [0,-1,float("nan"),float("inf")])
def test_invalid_scale_rejected(value):
    with pytest.raises(ValueError):
        SceneEditIntent(operation="scale",target="b",scale_mode="set",scale_xyz=(value,1,1))


@pytest.mark.parametrize("fields", [{}, {"scale_mode":"set"}, {"scale_xyz":[1,1,1]},
    {"scale_direction":"enlarge"}, {"scale_mode":"set","scale_xyz":[1,1,1],"scale_amount":"small"}])
def test_scale_modes_exclusive(fields):
    with pytest.raises(ValueError, match="scale_modes"):
        SceneEditIntent(operation="scale",target="b",**fields)


@pytest.mark.parametrize("permission,code", [(False,"forbidden"),(None,"permission_unknown")])
def test_permission(permission, code):
    library, scene = fixture()
    library.models["basket"] = library.models["basket"].model_copy(update={"scalable":permission})
    with pytest.raises(ValueError,match=code):
        apply(library,scene,plan(dict(operation="scale",scale_mode="set",scale_xyz=[1.2]*3)))


def test_limits_and_rollback():
    library,scene=fixture()
    before=scene.model_dump()
    with pytest.raises(ValueError,match="out_of_range"):
        apply(library,scene,plan(dict(operation="update_properties",properties={"color":"blue"}),
                               dict(operation="scale",scale_mode="set",scale_xyz=[4]*3)))
    assert scene.model_dump()==before
    with pytest.raises(ValueError):
        BrainConfig(scene_scale_min=2,scene_scale_max=1)


def test_collision_and_workspace():
    library,scene=fixture()
    scene.objects.append(make_object(2,"obstacle","basket",(.25,0,.1),category="container",support=0))
    with pytest.raises(ValueError,match="collision"):
        apply(library,scene,plan(dict(operation="scale",scale_mode="set",scale_xyz=[2]*3)))
    scene.objects.pop()
    with pytest.raises(ValueError,match="workspace"):
        apply(library,scene,plan(dict(operation="scale",scale_mode="set",scale_xyz=[2]*3)),
              scale_defaults=LayoutDefaults(workspace_min=(-.15,-.15),workspace_max=(.15,.15)),table_metadata_ref="table")


def test_parent_and_no_support_position_preserved():
    library,scene=fixture()
    scene.objects[1].components[0].properties.update(parent=0,position=[0,0,2],quaternion_xyzw=[0,0,0,.99999])
    SceneIndex(scene).component(1,"Semantic").properties["support"]=None
    before=SceneIndex(scene).component(1,"Transform").properties.copy()
    changed=apply(library,scene,plan(dict(operation="scale",scale_mode="set",scale_xyz=[1.5,1,1])))
    after=SceneIndex(changed).component(1,"Transform").properties
    assert {k:v for k,v in after.items() if k!="scale"}=={k:v for k,v in before.items() if k!="scale"}


@pytest.mark.parametrize("raw,expected", [("红","#FF0000"),("蓝色","#0000FF"),("green","#00FF00"),
                                        ("#aabbcc","#AABBCC"),("#ff000080","#FF000080")])
def test_color_normalization(raw,expected):
    assert ColorResolver.resolve(raw)==expected


def test_color_query_override_and_unchanged_geometry():
    library,scene=fixture()
    query=lambda color: SceneQueryIntent(query_type="count",target="b",entities=[
        TaskEntity(entity_id="b",semantic_name="basket",category="container",color=color)])
    engine=SceneQueryEngine(assets=library)
    assert engine.query(query("red"),scene).count==1
    changed=apply(library,scene,plan(dict(operation="update_properties",properties={"color":"blue"})))
    assert engine.query(query("blue"),changed).count==1
    assert engine.query(query("red"),changed).count==0
    assert SceneIndex(changed).component(1,"Transform")==SceneIndex(scene).component(1,"Transform")
    assert SceneIndex(changed).semantic(1)==SceneIndex(scene).semantic(1)
    changed=apply(library,changed,plan(dict(operation="update_properties",properties={"color":"#FF000080"})))
    assert engine.query(query("red"),changed).count==1
    assert engine.query(query("#FF000080"),changed).count==1
    assert engine.query(query("#FF0000FF"),changed).count==0


def test_unknown_evidence_not_zero_and_unrelated_objects_ignored():
    library,scene=fixture()
    scene.objects.append(make_object(3,"unknown","missing",(3,0,0),category="container"))
    query=SceneQueryIntent(query_type="count",target="b",entities=[TaskEntity(entity_id="b",semantic_name="basket",category="container",color="red")])
    assert SceneQueryEngine(assets=library).query(query,scene).count==1
    library.models["basket"]=library.models["basket"].model_copy(update={"color_tags":()})
    with pytest.raises(ValueError,match="evidence_missing"):
        SceneQueryEngine(assets=library).query(query,scene)


def test_multi_object_mixed_atomic_edit():
    library,scene=fixture()
    scene.objects.append(make_object(2,"basket","basket",(.7,0,.1),category="container",support=0))
    changed=apply(library,scene,plan(dict(operation="translate",direction="right",distance_m=.02),
                                   dict(operation="scale",scale_direction="enlarge",scale_amount="small"),
                                   dict(operation="update_properties",properties={"color":"blue"}),
                                   count=2,quantity_mode="all"))
    assert changed.scene_version==2
    for identifier in (1,2):
        assert SceneIndex(changed).transform(identifier).scale==pytest.approx((1.1,)*3)
        assert SceneIndex(changed).component(identifier,"MeshRenderer").properties["forceOverrideColor"]=="#0000FF"


def test_support_footprint_and_missing_geometry():
    library,scene=fixture()
    scene.objects[1].components[0].properties["position"][0]=1.88
    with pytest.raises(ValueError,match="footprint"):
        apply(library,scene,plan(dict(operation="scale",scale_mode="set",scale_xyz=[2]*3)))
    scene.objects[1].components[0].properties["position"][0]=0
    library.models["basket"]=library.models["basket"].model_copy(update={"local_aabb_min_m":None,"local_aabb_max_m":None})
    with pytest.raises(ValueError,match="requires_platform"):
        apply(library,scene,plan(dict(operation="scale",scale_mode="set",scale_xyz=[2]*3)))


@pytest.mark.parametrize("kind", ["child","supported","robot"])
def test_unsupported_scale_targets(kind):
    library,scene=fixture()
    if kind=="robot":
        library.models["basket"]=library.models["basket"].model_copy(update={"asset_type":"robot"})
    else:
        child=make_object(3,"other","basket",(0,0,2),category="container",support=1 if kind=="supported" else None)
        if kind=="child":
            child.components[0].properties["parent"]=1
        scene.objects.append(child)
    with pytest.raises(ValueError,match="target_unsupported"):
        apply(library,scene,plan(dict(operation="scale",scale_mode="set",scale_xyz=[2]*3)))


def test_parented_supported_nonuniform_transform():
    library,scene=fixture()
    parent=make_object(3,"parent","table",(0,0,0),category="structure")
    parent.components[0].properties["scale"]=[2,1,1]
    parent.components=[c for c in parent.components if c.component_type!="MetadataRef"]
    scene.objects.append(parent)
    props=scene.objects[1].components[0].properties
    props.update(parent=3,quaternion_xyzw=[0,0,math.sin(.2),math.cos(.2)])
    old=list(props["quaternion_xyzw"])
    changed=apply(library,scene,plan(dict(operation="scale",scale_mode="set",scale_xyz=[1.2,1.1,1.5])))
    transform=SceneIndex(changed).component(1,"Transform").properties
    assert transform["parent"]==3 and transform["quaternion_xyzw"]==old
    assert world_bounds(library.resolve("basket"),world_transform(changed,1))[0][2]==pytest.approx(0)


def test_scale_does_not_create_support_for_unattached_object():
    library,scene=fixture()
    SceneIndex(scene).component(1,"Semantic").properties["support"]=None
    changed=apply(library,scene,plan(dict(operation="scale",scale_mode="set",scale_xyz=[1.1,1.1,1])))
    assert SceneIndex(changed).semantic(1).support is None
    assert SceneIndex(changed).transform(1).position==(0,0,.1)


def test_dialogue_stable_binding_and_external_input_unchanged():
    from robot_agent_brain.session.dialogue_state import DialogueState
    library,scene=fixture()
    scene.objects.append(make_object(2,"basket","basket",(.7,0,.1),category="container",support=0))
    dialogue=DialogueState(last_entity_id=2,last_entity_ids=[2])
    before=dialogue.model_dump()
    edit=plan(dict(operation="scale",scale_direction="shrink",scale_amount="small"),dialogue_ref=True)
    patch=SceneEditor(library).edit(edit,scene,dialogue=dialogue)
    changed=SceneManager(scene).apply_patch(patch)
    assert SceneIndex(changed).transform(1).scale==(1,1,1)
    assert SceneIndex(changed).transform(2).scale==pytest.approx((1/1.1,)*3)
    assert dialogue.model_dump()==before


@pytest.mark.parametrize("props", [{},{"color":"blue","mass":1},{"mass":1}])
def test_only_color_property(props):
    library,scene=fixture()
    with pytest.raises(ValueError,match="property_unsupported"):
        apply(library,scene,plan(dict(operation="update_properties",properties=props)))


def test_unknown_color_and_white_override():
    library,scene=fixture()
    with pytest.raises(ValueError,match="color_unknown"):
        apply(library,scene,plan(dict(operation="update_properties",properties={"color":"magic"})))
    changed=apply(library,scene,plan(dict(operation="update_properties",properties={"color":"white"})))
    evidence=ColorEvidenceResolver(library)
    assert not evidence.matches("red",changed.objects[1],SceneIndex(changed))
    assert evidence.matches("white",changed.objects[1],SceneIndex(changed))


def test_geometry_cache_and_policy_fingerprint():
    from robot_agent_brain.diagnostics import configuration_summary, fingerprint
    config=BrainConfig()
    assets=config.load_assets()
    first=configuration_summary(config,assets,config.load_defaults())
    second=configuration_summary(config.model_copy(update={"scene_scale_small":1.2}),assets,config.load_defaults())
    assert fingerprint(first)!=fingerprint(second)


def test_multi_object_failure_no_partial_scene_mutation():
    library,scene=fixture()
    other=make_object(2,"basket","basket",(.7,0,.1),category="container",support=0)
    other.components[0].properties["scale"]=[2,1,1]
    scene.objects.append(other)
    before=scene.model_dump()
    with pytest.raises(ValueError,match="out_of_range"):
        apply(library,scene,plan(dict(operation="scale",scale_mode="multiply",scale_xyz=[2]*3),count=2,quantity_mode="all"))
    assert scene.model_dump()==before


def test_color_change_does_not_reselect_mixed_edit_target():
    library,scene=fixture()
    changed=apply(library,scene,plan(dict(operation="update_properties",properties={"color":"blue"}),
                                   dict(operation="scale",scale_direction="enlarge",scale_amount="small"),color="red"))
    assert SceneIndex(changed).transform(1).scale==pytest.approx((1.1,)*3)
    assert SceneIndex(changed).component(1,"MeshRenderer").properties["forceOverrideColor"]=="#0000FF"
