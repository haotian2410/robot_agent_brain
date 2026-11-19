import pytest

from robot_agent_brain.scene.initial_robot import split_initial_robot
from robot_agent_brain.contracts.decomposition import Subtask
from robot_agent_brain.models.task_decomposition import execution_segments


@pytest.mark.parametrize('text,robot,command', [
    ('使用ur10把苹果放到篮子里', 'ur10', '把苹果放到篮子里'),
    ('使用 Piper 机械臂把香蕉放到托盘里', 'piper', '把香蕉放到托盘里'),
    ('使用UR10来增加一个苹果', 'ur10', '增加一个苹果'),
    ('把苹果放到篮子里', None, '把苹果放到篮子里'),
])
def test_initial_qualifier(text, robot, command):
    assert split_initial_robot(text) == (robot, command)


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


def test_segment_rejects_intermediate_observation_before_dispatch():
    steps = [Subtask(kind='robot_task', instruction='移开盒子'),
             Subtask(kind='robot_task', instruction='根据露出的画面抓取物体',
                     requires_fresh_observation=True)]
    with pytest.raises(ValueError, match='robot_segment_intermediate_observation_unsupported'):
        execution_segments(steps)
    assert steps[0].instruction == '移开盒子'


def test_explicit_query_boundary_allows_subsequent_observation():
    steps = [Subtask(kind='robot_task', instruction='移开盒子'),
             Subtask(kind='scene_query', instruction='观察盒子后的物体'),
             Subtask(kind='robot_task', instruction='根据画面抓取苹果',
                     requires_fresh_observation=True)]
    grouped, _ = execution_segments(steps)
    assert len(grouped) == 3


def test_observation_requirement_survives_wire_parse():
    from robot_agent_brain.models.task_decomposition import parse_decomposition, task_decomposition_wire_schema
    schema = task_decomposition_wire_schema()['properties']['steps']['items']['properties']
    assert schema['requires_fresh_observation'] == {'type': 'boolean'}
    parsed = parse_decomposition({'steps': [dict(kind='robot_task', instruction='看新画面抓取',
                                                requires_fresh_observation=True)]})
    assert parsed.steps[0].requires_fresh_observation
