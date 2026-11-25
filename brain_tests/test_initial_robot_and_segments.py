import pytest

from robot_agent_brain.scene.initial_robot import split_initial_robot
from robot_agent_brain.contracts.decomposition import Subtask
from robot_agent_brain.models.task_decomposition import execution_segments


@pytest.mark.parametrize('text,robot,command', [
    ('使用ur10把苹果放到篮子里', 'ur10', '把苹果放到篮子里'),
    ('使用 Piper 机械臂把香蕉放到托盘里', 'piper', '把香蕉放到托盘里'),
    ('使用UR10来增加一个苹果', 'ur10', '增加一个苹果'),
    ('添加UR10机械臂然后添加四个魔方然后把其他魔方放在最左侧的魔方上面',
     'ur10', '添加四个魔方然后把其他魔方放在最左侧的魔方上面'),
    ('添加 UR10 机械臂，再添加四个魔方', 'ur10', '添加四个魔方'),
    ('增加 Piper 机械臂，接着把苹果放进篮子里', 'piper', '把苹果放进篮子里'),
    ('添加Apple然后把它放进篮子里', None, '添加Apple然后把它放进篮子里'),
    ('把苹果放到篮子里', None, '把苹果放到篮子里'),
])
def test_initial_qualifier(text, robot, command):
    assert split_initial_robot(text) == (robot, command)


def test_arm_initialization_stays_with_first_edit_when_decomposing():
    from types import SimpleNamespace
    from unittest.mock import Mock
    from robot_agent_brain.contracts.decomposition import TaskDecomposition
    from robot_agent_brain.web.service import AgentService

    instruction = '添加UR10机械臂然后添加四个魔方然后把其他魔方放在最左侧的魔方上面'
    plan = TaskDecomposition(steps=[
        Subtask(kind='scene_edit', instruction='添加四个魔方'),
        Subtask(kind='robot_task', instruction='把其他魔方放在最左侧的魔方上面'),
    ])
    pipeline = SimpleNamespace(decompose=Mock(return_value=plan))
    steps = AgentService.decomposition(None,
        SimpleNamespace(change_kind='scene_edit', command=instruction),
        SimpleNamespace(pipeline=pipeline, scene=None))
    pipeline.decompose.assert_called_once_with(
        '添加四个魔方然后把其他魔方放在最左侧的魔方上面', scene=None)
    assert [step.instruction for step in steps] == [
        '使用 ur10 添加四个魔方', '把其他魔方放在最左侧的魔方上面']
    assert [step.kind for step in steps] == ['scene_edit', 'robot_task']


def test_robot_segments_do_not_cross_edits_or_queries():
    kinds = ['robot_task', 'robot_task', 'scene_edit', 'robot_task', 'scene_query', 'robot_task']
    original = [Subtask(kind=kind, instruction=f'动作{i}') for i, kind in enumerate(kinds)]
    grouped, sources = execution_segments(original)
    assert len(grouped) == 5
    assert grouped[0].instruction == '动作0；然后动作1'
    assert sources == [['动作0', '动作1'], ['动作2'], ['动作3'], ['动作4'], ['动作5']]
    assert original[0].instruction == '动作0'


def test_segment_preserves_pronouns():
    grouped, _ = execution_segments([Subtask(kind='robot_task', instruction=s)
        for s in ['抓起最左边的苹果', '把它放进托盘']])
    assert len(grouped) == 1 and '把它' in grouped[0].instruction


def test_segment_ignores_legacy_intermediate_observation_hint():
    steps = [Subtask(kind='robot_task', instruction='移开盒子'),
             Subtask(kind='robot_task', instruction='根据露出的画面抓取物体')]
    grouped, _ = execution_segments(steps)
    assert len(grouped) == 1
    assert grouped[0].instruction == '移开盒子；然后根据露出的画面抓取物体'


def test_explicit_query_boundary_allows_subsequent_observation():
    steps = [Subtask(kind='robot_task', instruction='移开盒子'),
             Subtask(kind='scene_query', instruction='观察盒子后的物体'),
             Subtask(kind='robot_task', instruction='根据画面抓取苹果')]
    grouped, _ = execution_segments(steps)
    assert len(grouped) == 3


def test_legacy_observation_hint_is_ignored_by_wire_parse():
    from robot_agent_brain.models.task_decomposition import parse_decomposition, task_decomposition_wire_schema
    schema = task_decomposition_wire_schema()['properties']['steps']['items']['properties']
    parsed = parse_decomposition({'steps': [dict(kind='robot_task', instruction='看新画面抓取',
                                                requires_fresh_observation=True)]})
    assert 'requires_fresh_observation' not in schema
    assert parsed.steps[0].instruction == '看新画面抓取'


def test_complete_task_classifier_is_distinct_from_short_recovery():
    from robot_agent_brain.semantics.recovery_routing import (
        continuation_candidate, independent_task_candidate)
    names = ['苹果', '魔方', '小汽车', '托盘']
    assert continuation_candidate('左边的', asset_names=names)
    assert not independent_task_candidate('左边的', asset_names=names)
    assert independent_task_candidate('先删除苹果和魔方，再把小汽车放进托盘里', asset_names=names)
