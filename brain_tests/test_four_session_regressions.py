from types import SimpleNamespace

import pytest

from robot_agent_brain.models.qwen_http import _repair_live_scene_edit_quantity
from robot_agent_brain.models.task_understanding import parse_qwen_turn
from robot_agent_brain.adapters.subprocess_execution import unique_named_document
from robot_agent_brain.semantics.recovery_routing import continuation_candidate
from robot_agent_brain.scene.editor import SceneEditor
from robot_agent_brain.scene.component_access import SceneIndex
from test_scene_scale_color import fixture


@pytest.mark.parametrize('shared,added,removed', [(False, 10, 11), (True, 11, 10)])
def test_compound_quantity_is_local_to_operation(shared, added, removed):
    catalog = SimpleNamespace(models=[SimpleNamespace(name='apple', aliases=['苹果'])])
    entities = [dict(entity_id='a', semantic_name='apple', count=added)]
    if not shared:
        entities.append(dict(entity_id='b', semantic_name='apple', count=removed))
    value = dict(status='accepted', turn_kind='scene_edit', scene_edit=dict(entities=entities,
        operations=[dict(operation='add', target='a'),
                    dict(operation='remove', target='a' if shared else 'b')]))
    result = _repair_live_scene_edit_quantity(value, f'生成{added}个苹果并删除{removed}个苹果', catalog)
    edit = result['scene_edit']
    by_id = {e['entity_id']: e for e in edit['entities']}
    assert edit['operations'][0]['target'] != edit['operations'][1]['target']
    assert by_id[edit['operations'][0]['target']]['count'] == added
    assert by_id[edit['operations'][1]['target']]['count'] == removed
    assert value['scene_edit']['entities'][0]['count'] == added


def test_catalog_selector_preserves_pending_task():
    names = ['胶头滴管', 'turkey_baster']
    assert continuation_candidate('最左侧胶头滴管', asset_names=names)
    assert not continuation_candidate('查询最左侧胶头滴管', asset_names=names)
    assert not continuation_candidate('把最左侧胶头滴管移到苹果右侧', asset_names=names)


def test_robot_config_uses_canonical_wire():
    turn = parse_qwen_turn(dict(turn_kind='robot_config', status='accepted',
        robot_asset_switch=dict(robot_asset='piper')), '换成Piper')
    assert turn.robot_asset_switch.robot_asset == 'piper'


@pytest.mark.parametrize('route', ['scene_edit', 'scene_query', 'robot_task', 'robot_config'])
def test_clarification_keeps_original_route_without_executable_payload(route):
    turn = parse_qwen_turn(dict(status='clarification_required', turn_kind=route,
        clarification_question='请选择对象'), '请选择对象')
    assert turn.turn_kind == route
    assert turn.task_intent is None and turn.scene_edit is None and turn.scene_query is None


@pytest.mark.parametrize('penetration,collision', [(2.23e-7, False), (.01, True)])
def test_support_contact_is_not_obstacle(penetration, collision):
    assets, scene = fixture()
    SceneIndex(scene).component(1, 'Transform').properties['position'] = [0, 0, .1 - penetration]
    assert SceneEditor(assets)._overlaps(SceneIndex(scene).object(1), scene) is collision


def test_transport_names_are_ascii_unique_without_mutating_source():
    source = dict(objects=[dict(object_id_in_scene=i, object_name_in_scene=name)
                          for i, name in enumerate(['苹果', 'object_0', 'apple', 'apple', 'apple-2'])])
    result = unique_named_document(source)
    names = [o['object_name_in_scene'] for o in result['objects']]
    assert len(set(names)) == len(names)
    assert all(name.isascii() for name in names)
    assert source['objects'][0]['object_name_in_scene'] == '苹果'


@pytest.mark.parametrize('label', ['8', 'ID 8', 'object_id 8', '对象编号8'])
def test_recovery_id_spelling_does_not_lose_confirmed_selection(label):
    from robot_agent_brain.application import BrainApplication
    entity = SimpleNamespace(entity_id='rack', semantic_name='test_tube_rack', scene_object_ids=[8])
    turn = SimpleNamespace(scene_edit=None, task_intent=SimpleNamespace(
        entities=[entity], operations=[SimpleNamespace(source='rack')], spatial_relations=[]))
    evidence = {'accepted_amendments':[dict(field='selection', subject_role='source',value=label)]}
    BrainApplication._validate_recovery_u_conditions(turn, evidence)
    entity.scene_object_ids = [9]
    with pytest.raises(ValueError, match='u_condition_lost:selection'):
        BrainApplication._validate_recovery_u_conditions(turn, evidence)


def test_recovery_destination_selection_cannot_prove_source_or_target():
    from robot_agent_brain.application import BrainApplication
    turn = SimpleNamespace(scene_edit=None, task_intent=SimpleNamespace(
        entities=[], operations=[SimpleNamespace(source='apple', destination='dropper')],
        spatial_relations=[SimpleNamespace(scope='selection', subject='dropper', relation='leftmost')]))
    amendment = dict(field='selection', subject_role='destination', value='leftmost')
    BrainApplication._validate_recovery_u_conditions(turn, {'accepted_amendments':[amendment]})
    for role in ('source', 'target'):
        with pytest.raises(ValueError, match='u_condition_lost:selection'):
            BrainApplication._validate_recovery_u_conditions(turn, {'accepted_amendments':[
                dict(amendment, subject_role=role)]})


@pytest.mark.parametrize('instruction,route', [
    ('把苹果放到柜子右边','robot_task'), ('把苹果移动到柜子右侧','scene_edit'),
    ('让机械臂把苹果移动五厘米','robot_task'), ('直接修改场景，把苹果放到右侧','scene_edit'),
    ('新增苹果然后把它放进篮子',None), ('最左侧胶头滴管',None),
])
def test_action_default_is_context_not_payload_conversion(instruction,route):
    from robot_agent_brain.pipeline import _action_route_hint, _check_action_route
    assert _action_route_hint(instruction) == route
    if route is not None:
        wrong = SimpleNamespace(protocol_version='task_understanding.v3.1', status='accepted', turn_kind='scene_edit' if route=='robot_task' else 'robot_task')
        result = _check_action_route(wrong,instruction,route)
        assert result.status=='clarification_required'
        assert result.scene_edit is None and result.task_intent is None
