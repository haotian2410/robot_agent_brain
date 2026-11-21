import json

import httpx
import pytest

from robot_agent_brain.contracts.task_intent import TaskIntent
from robot_agent_brain.contracts.scene import SceneConfig
from robot_agent_brain.scene.bootstrapper import make_object
from robot_agent_brain.grounding.scene_grounder import SceneGrounder, GroundingAmbiguous
from robot_agent_brain.models.task_understanding import apply_tabletop_placement_region


def robot_task(text, **source):
    return TaskIntent(instruction=text, entities=[
        dict(entity_id='source', semantic_name='cube', category='object', **source),
        dict(entity_id='dest', semantic_name='cube', category='object', scene_object_ids=[1])],
        operations=[dict(operation_id='op-1', task_type='pick_and_place', source='source', destination='dest',
                        placement_target=dict(kind='support_surface', reference='dest'))])


@pytest.mark.parametrize('excluded', [[], [1, 2, 3]])
def test_other_cubes_means_complement_not_model_exclusion(excluded):
    scene = SceneConfig(scene_schema_version=1, scene_id=1, scene_version=1, scene_name='test', objects=[
        make_object(i, 'cube', 'cube', (i*.2, 0, .1), category='object') for i in (1, 2, 3)])
    task = robot_task('把其他魔方放到最左边的魔方上', quantity_mode='all', count=2,
                      all_available=True, exclude_scene_object_ids=excluded)
    from robot_agent_brain.contracts.spatial import SpatialRelation
    task.spatial_relations = [SpatialRelation(subject='source', relation='farthest', reference='dest')]
    result = SceneGrounder(aliases={'魔方': 'cube'}).ground(task, scene)
    assert result.entities[0].scene_object_ids == [2, 3]
    assert task.entities[0].exclude_scene_object_ids == excluded


@pytest.mark.parametrize('relation,sign', [('left_of', -1), ('right_of', 1)])
def test_relative_layout_candidate_and_collision_share_clearance(relation, sign):
    from test_scene_scale_color import fixture
    from robot_agent_brain.config import LayoutDefaults
    from robot_agent_brain.contracts.turn import SceneEditIntent
    from robot_agent_brain.scene.editor import SceneEditor
    assets, scene = fixture()
    editor = SceneEditor(assets)
    result = editor._placement(assets.resolve('basket'), scene, scene.objects[1],
        SceneEditIntent(operation='add', target='new', relation=relation, reference='basket'),
        LayoutDefaults(table_object_id=0, robot_object_id=99, clearance_m=.04), 2)
    assert result[0] == pytest.approx(sign*(.2 + .2*editor.layout.clearance_ratio))
    assert result[1] == pytest.approx(0)


@pytest.mark.parametrize('scale,expected_gap', [(.25, .005), (1, .02), (3, .02)])
def test_adaptive_clearance_uses_scaled_models_and_smaller_reference(scale, expected_gap):
    from test_scene_scale_color import fixture
    from robot_agent_brain.scene.scene_layout import SceneLayoutPolicy
    from robot_agent_brain.scene.scene_graph import WorldTransform
    assets, _ = fixture()
    linear = ((scale, 0, 0), (0, scale, 0), (0, 0, scale))
    target = WorldTransform((0, 0, 0), linear)
    ref = WorldTransform((0, 0, 0), ((1, 0, 0), (0, 1, 0), (0, 0, 1)))
    policy = SceneLayoutPolicy()
    gap = policy.adaptive_clearance(assets.resolve('basket'), target, assets.resolve('basket'), ref)
    assert gap == pytest.approx(expected_gap)
    candidate = policy.relative_candidates('right_of', ref, assets.resolve('basket'), assets.resolve('basket'), target)[0]
    assert candidate.position[0] - .1*scale - .1 == pytest.approx(gap)


def test_other_cubes_requires_unique_destination():
    scene = SceneConfig(scene_schema_version=1, scene_id=1, scene_version=1, scene_name='test', objects=[
        make_object(i, 'cube', 'cube', (i*.2, 0, .1), category='object') for i in (1, 2, 3)])
    task = robot_task('把其他魔方放到魔方上')
    task.entities[1].scene_object_ids = []
    with pytest.raises(GroundingAmbiguous):
        SceneGrounder(aliases={'魔方': 'cube'}).ground(task, scene)


@pytest.mark.parametrize('source,destination,region', [
    ('左上角的魔方','桌面的中间',None), ('最左边的魔方','桌面的中间',None),
    ('魔方','桌面的左上角','left_front')])
def test_source_direction_never_becomes_destination_region(source, destination, region):
    task = robot_task(f'把{source}放到{destination}')
    from robot_agent_brain.contracts.task_intent import PlacementTarget
    task.operations[0].placement_target = PlacementTarget(kind='support_surface', reference='table')
    assert apply_tabletop_placement_region(task).operations[0].placement_target.region == region


def test_panda_noun_tag_does_not_filter_existing_panda():
    task = TaskIntent(instruction='把熊猫放到桌上', entities=[dict(entity_id='p',
        semantic_name='toy_panda', category='toy', tags=['熊猫玩具'])],
        operations=[dict(operation_id='op-1', task_type='grasp', target='p')])
    scene = SceneConfig(scene_schema_version=1, scene_id=1, scene_version=1, scene_name='test', objects=[
        make_object(11, 'ToyPanda', 'model:22', (0, 0, .1), category='graspable')])
    assert SceneGrounder().ground(task, scene).entities[0].scene_object_ids == [11]


@pytest.mark.parametrize('acknowledged', [False, True])
def test_http_lease_rejection_has_result_and_evidence(tmp_path, acknowledged):
    from test_web_service import configured
    from robot_agent_brain.web.protocol import SessionRequest, StartTask, digest
    service, browser = configured(tmp_path)
    original = browser.handle
    def handle(request):
        if request.url.path == '/acquireSceneLease':
            payload = json.loads(request.content)
            body = {'error': 'browser_scene_version_conflict'}
            if acknowledged:
                body.update(lease_status='not_granted', taskID=payload['taskID'], browserID='b', sessionID=None)
            return httpx.Response(409, json=body)
        return original(request)
    browser.handle = handle
    sid = service.activate(SessionRequest(browserID='b'))['sessionID']
    request = StartTask(sessionID=sid, browserID='b', clientRequestID='lease-fail', command='增加苹果',
        scene=browser.scene.model_dump(mode='json'), sceneDigest=digest(browser.scene))
    record, _ = service.tasks.submit(request)
    identifier = record['id']
    service.execute(identifier)
    result = service.tasks.get(identifier)
    assert result['result']['outcome'] == 'failed'
    assert result['result']['error']['code'] == ('gateway_lease_not_granted' if acknowledged else 'gateway_transport_error')
    evidence = json.loads((tmp_path/sid/'web_failures'/f'{identifier}.json').read_text())
    assert evidence['http_status'] == 409
    assert 'browser_scene_version_conflict' in evidence['response_body']
