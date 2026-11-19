"""Opt-in checks against the installed OLS, without launching Control."""
import os
from pathlib import Path
import pytest
from robot_agent_brain.application import BrainApplication
from robot_agent_brain.config import BrainConfig
from robot_agent_brain.contracts.task_intent import TaskIntent, TaskEntity, Operation
from robot_agent_brain.contracts.turn import BrainTurn


@pytest.mark.parametrize('name', ['ur10', 'piper'])
def test_initial_arm_bootstrap_keeps_default_accessories(tmp_path, name):
    path = os.environ.get('ROBOT_BRAIN_RUNTIME_CONFIG')
    if not path:
        pytest.skip('set ROBOT_BRAIN_RUNTIME_CONFIG for installed OLS verification')
    class Provider:
        def understand_turn(self, request):
            return BrainTurn(status='accepted', turn_kind='robot_task', instruction=request.instruction,
                task_intent=TaskIntent(instruction=request.instruction, entities=[
                    TaskEntity(entity_id='a', semantic_name='apple', category='fruit'),
                    TaskEntity(entity_id='b', semantic_name='basket', category='container')],
                    operations=[Operation(operation_id='op-1', task_type='pick_and_place', source='a',
                        destination='b', placement_target={'kind': 'container_interior', 'reference': 'b'})]))
    config = BrainConfig.load(path).model_copy(update={'vision': False, 'planner': 'recipe',
        'output_dir': str(tmp_path), 'execution_enabled': False})
    app = BrainApplication(config, provider=Provider())
    invalid = app.handle('使用 unknown_arm 把苹果放到篮子里', session_id='initial')
    assert invalid.run_status != 'success'
    assert app.get_session('initial').scene is None
    report = app.handle(f'使用 {name} 把苹果放到篮子里', session_id='initial')
    assert report.run_status == 'success', report.error
    session = app.get_session('initial')
    assert session.robot_asset == name
    assert session.gripper_asset and session.camera_asset
    assert len(app.robot_assembly.classify_scene(session.scene)['arm']) == 1
    from robot_agent_brain.scene.component_access import SceneIndex
    assembly = app.robot_assembly.classify_scene(session.scene)
    arm_asset = assembly['arm'][0][1]
    gripper_id = assembly['gripper'][0][0]
    mount = SceneIndex(session.scene).component(gripper_id, 'RobotAttachment').properties['transform']
    assert mount['position'] == arm_asset.driver['position'][0]
    assert mount['quaternion_xyzw'] == arm_asset.driver['quaternion_xyzw'][0]
    before = session.scene.raw_document()
    other = 'piper' if name == 'ur10' else 'ur10'
    rejected = app.handle(f'使用 {other} 把苹果放到篮子里', session_id='initial')
    assert rejected.error.code == 'robot_initialization_requires_empty_session'
    assert session.scene.raw_document() == before
    restored = BrainApplication(config, provider=Provider()).get_session('initial')
    assert restored.robot_asset == name
    assert restored.scene.raw_document() == before
