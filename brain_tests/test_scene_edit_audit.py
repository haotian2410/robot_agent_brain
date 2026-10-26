import pytest
from robot_agent_brain.contracts.asset_library import BrainAssetView
from robot_agent_brain.contracts.task_intent import TaskEntity
from robot_agent_brain.scene.asset_resolver import AssetResolver

class TypedAssets:
    typed_namespaces = True
    supports_features = True
    model = BrainAssetView(library_asset_id=3, metadata_ref='$LIBRARY_SERVER/3',
        semantic_name='baseball', category='ball', dimensions_m=(.07,.07,.07),
        local_aabb_min_m=(-.035,-.035,-.035),local_aabb_max_m=(.035,.035,.035),
        color_tags=('white',), tags=('white',))
    def find_by_name(self, name): return [self.model] if name=='baseball' else []
    def find_by_category(self, category): return [self.model] if category=='ball' else []

def test_named_typed_asset_does_not_require_model_generated_category():
    entity=TaskEntity(entity_id='b',semantic_name='baseball',category='sports_equipment')
    assert AssetResolver(TypedAssets()).resolve(entity).model.library_asset_id==3
    with pytest.raises(ValueError,match='asset_missing'):
        AssetResolver(TypedAssets()).resolve(entity.model_copy(update={'category_only':True}))
    with pytest.raises(ValueError,match='asset_feature_missing'):
        AssetResolver(TypedAssets()).resolve(entity.model_copy(update={'color':'blue'}))

def test_named_typed_asset_does_not_pick_first_ambiguous_resource():
    assets=TypedAssets()
    assets.find_by_name=lambda name:[assets.model,assets.model.model_copy(update={'library_asset_id':30})]
    with pytest.raises(ValueError,match='asset_ambiguous'):
        AssetResolver(assets).resolve(TaskEntity(entity_id='b',semantic_name='baseball',category='object'))

def test_supported_translation_bounds_and_atomic_rollback():
    from test_scene_scale_color import fixture,plan
    from robot_agent_brain.scene.editor import SceneEditor
    from robot_agent_brain.scene.scene_manager import SceneManager
    from robot_agent_brain.config import LayoutDefaults
    library,scene=fixture()
    defaults=LayoutDefaults(table_object_id=0,workspace_min=(-.5,-.5),workspace_max=(.5,.5))
    editor=SceneEditor(library,scale_defaults=defaults,table_metadata_ref='table')
    before=scene.model_dump()
    with pytest.raises(ValueError,match='scene_edit_workspace_exceeded'):
        editor.edit(plan(dict(operation='update_properties',properties={'color':'blue'}),
            dict(operation='translate',direction='right',distance_m=1)),scene,defaults=defaults)
    assert scene.model_dump()==before
    with pytest.raises(ValueError,match='support_footprint_exceeded'):
        editor.edit(plan(dict(operation='translate',direction='right',distance_m=2)),scene,defaults=defaults)
    patch=editor.edit(plan(dict(operation='translate',direction='right',distance_m=.2)),scene,defaults=defaults)
    changed=SceneManager(scene).apply_patch(patch)
    from robot_agent_brain.scene.component_access import SceneIndex
    assert SceneIndex(changed).transform(1).position[0]==pytest.approx(.2)
    assert SceneIndex(changed).semantic(1).support==0

def test_uploaded_table_does_not_inherit_template_workspace():
    from test_scene_scale_color import fixture,plan
    from robot_agent_brain.scene.editor import SceneEditor
    from robot_agent_brain.config import LayoutDefaults
    library,scene=fixture()
    defaults=LayoutDefaults(table_object_id=0,workspace_min=(-.2,-.2),workspace_max=(.2,.2))
    # Different resource: its own footprint is authoritative, not template XY.
    editor=SceneEditor(library,scale_defaults=defaults,table_metadata_ref='another_table')
    assert editor.edit(plan(dict(operation='translate',direction='right',distance_m=1)),scene).operations

def test_unique_extremum_does_not_assert_unspecified_pool_size():
    from test_b01_b06_regressions import fixture,entities
    from robot_agent_brain.grounding.scene_object_selector import SceneObjectSelector
    from robot_agent_brain.contracts.spatial import SpatialRelation
    scene=fixture()
    relations=[SpatialRelation(subject='apple',relation='rightmost')]
    assert [o.object_id_in_scene for o in SceneObjectSelector().resolve('apple',entities(),relations,scene)]==[3]
    e=entities();e[0]=e[0].model_copy(update={'quantity_mode':'candidate_pool','count':3})
    with pytest.raises(ValueError,match='candidate_pool_count_mismatch'):
        SceneObjectSelector().resolve('apple',e,relations,scene)

def test_supported_move_without_geometry_rejected_not_reported_safe():
    from test_scene_scale_color import fixture,plan
    from test_component_editor import UnavailableGeometry
    from robot_agent_brain.scene.editor import SceneEditor
    _,scene=fixture()
    before=scene.model_dump()
    with pytest.raises(ValueError,match='scene_edit_support_invalid'):
        SceneEditor(UnavailableGeometry()).edit(plan(dict(operation='translate',direction='right',distance_m=.1)),scene)
    assert scene.model_dump()==before

def test_reference_relative_half_and_extremum_keep_reference_origin():
    from test_b01_b06_regressions import fixture
    from robot_agent_brain.grounding.scene_relation_resolver import SceneRelationResolver
    from robot_agent_brain.contracts.spatial import ResolvedSelectionRelation
    scene=fixture()
    scene.objects[1].components[0].properties['position']=[1,0,0]
    scene.objects[2].components[0].properties['position']=[.2,.4,0]
    scene.objects[3].components[0].properties['position']=[.6,.1,0]
    resolver=SceneRelationResolver(); candidates=scene.objects[2:]
    relations=[ResolvedSelectionRelation(relation='left',reference_object_id=1),
               ResolvedSelectionRelation(relation='frontmost')]
    assert [o.object_id_in_scene for o in resolver.resolve(candidates,relations,scene)]==[2]
    # Without an explicit reference the existing world-origin meaning stays.
    assert resolver.resolve(candidates,[ResolvedSelectionRelation(relation='left')],scene)==[]

def test_local_translation_after_world_rotation_uses_rotated_axes():
    from robot_agent_brain.scene.transform_editor import rotate,translate
    from robot_agent_brain.scene.scene_graph import WorldTransform
    identity=((1.,0.,0.),(0.,1.,0.),(0.,0.,1.))
    initial=WorldTransform((.4,.1,.6),identity)
    turned=rotate(initial,'z',90)
    assert translate(turned,'right',.02,'object_local').position==pytest.approx((.4,.12,.6))
    assert translate(turned,'right',.02,'world').position==pytest.approx((.42,.1,.6))

def test_prompt_complete_edit_examples_validate():
    import json
    from robot_agent_brain.models.prompts import TASK_UNDERSTANDING_PROMPT
    from robot_agent_brain.models.task_understanding import TaskParseOutput
    operations=[]
    for line in TASK_UNDERSTANDING_PROMPT.splitlines():
        if line.startswith('{') and ('"coordinate_frame":"object_local"' in line or '"operation":"move_relative"' in line):
            value=TaskParseOutput.model_validate(json.loads(line))
            operations.extend(value.scene_edit.operations)
    assert any(o.operation=='translate' and o.direction=='right' and o.distance_m==.02 for o in operations)
    assert any(o.operation=='move_relative' and o.relation=='left_of' and o.reference=='basket' for o in operations)

def test_live_edit_schema_cannot_omit_motion_or_relative_fields():
    from robot_agent_brain.models.task_understanding import task_understanding_wire_schema
    required=task_understanding_wire_schema()['$defs']['SceneEditIntent']['required']
    assert {'direction','distance_m','motion_scale','relation','reference','coordinate_frame'}<=set(required)

def test_explicit_axis_motion_evidence_is_scene_only():
    from robot_agent_brain.semantics.motion_evidence import resolve_motion_evidence
    text='把香蕉沿自身局部X轴正方向移动两厘米'
    span=resolve_motion_evidence(text,1,allow_axes=True)[0]
    assert span.direction=='right' and span.distance_m==pytest.approx(.02)
    with pytest.raises(ValueError,match='motion_clause_binding_ambiguous'):
        resolve_motion_evidence(text,1)
    assert resolve_motion_evidence('沿世界Y轴负方向移动五厘米',1,allow_axes=True)[0].direction=='back'
    with pytest.raises(ValueError,match='motion_clause_binding_ambiguous'):
        resolve_motion_evidence('把香蕉沿X轴移动两厘米',1,allow_axes=True)

def test_opposite_edit_extrema_cannot_collapse_to_single_object():
    from robot_agent_brain.contracts.turn import SceneEditPlan
    from pydantic import ValidationError
    value={'entities':[{'entity_id':'ball','semantic_name':'baseball','category':'ball'}],
        'relations':[{'subject':'ball','relation':'leftmost'},{'subject':'ball','relation':'rightmost'}],
        'operations':[{'operation':'update_properties','target':'ball','properties':{'color':'blue'}}]}
    with pytest.raises(ValidationError,match='scene_edit_selection_conflict'):SceneEditPlan.model_validate(value)
    value['entities'].append({'entity_id':'other','semantic_name':'baseball','category':'ball'})
    value['relations'][1]['subject']='other'
    value['operations'].append({'operation':'update_properties','target':'other','properties':{'color':'blue'}})
    assert len(SceneEditPlan.model_validate(value).operations)==2

@pytest.mark.parametrize('fail',[False,True])
def test_empty_first_edit_commits_once_or_not_at_all(tmp_path,fail):
    from robot_agent_brain.application import BrainApplication
    from robot_agent_brain.config import BrainConfig
    from robot_agent_brain.contracts.turn import BrainTurn,SceneEditPlan,SceneEditIntent
    from robot_agent_brain.adapters.local_scene_platform import LocalScenePlatform
    class Platform(LocalScenePlatform):
        writes=[]
        def load_scene(self,scene):
            self.writes.append(scene.model_copy(deep=True));return super().load_scene(scene)
        def apply_patch(self,patch):
            raise AssertionError('initial edit must be a single complete scene commit')
    class Provider:
        def understand_turn(self,request):
            ops=[SceneEditIntent(operation='add',target='a')]
            if fail:ops.append(SceneEditIntent(operation='translate',target='a',direction='right',distance_m=2))
            return BrainTurn(status='accepted',turn_kind='scene_edit',instruction=request.instruction,
                scene_edit=SceneEditPlan(entities=[TaskEntity(entity_id='a',semantic_name='apple',category='fruit')],operations=ops))
    app=BrainApplication(BrainConfig(provider='replay',output_dir=str(tmp_path)),provider=Provider(),platform_factory=Platform)
    report=app.handle('add',session_id='initial-edit')
    session=app.get_session('initial-edit')
    if fail:
        assert report.run_status!='success' and session.scene is None and Platform.writes==[]
        assert session.original_scene_manifest is None
    else:
        assert report.run_status=='success',report
        assert len(Platform.writes)==1 and session.scene.scene_version==1
        assert session.original_scene_manifest is not None
