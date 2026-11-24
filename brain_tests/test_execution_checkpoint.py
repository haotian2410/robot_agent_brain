from copy import deepcopy
from types import SimpleNamespace
import pytest
from robot_agent_brain.session.execution_checkpoint import bind, for_dispatch
from robot_agent_brain.session.store import SessionState


def test_checkpoint_binds_committed_scene_and_survives_serialization():
    scene = {'scene_id': 3, 'scene_version': 4, 'objects': [{'object_id_in_scene': 7, 'position': [0, 0, 1]}]}
    snapshot = {'schema_version': 1, 'source_request_id': 'pick', 'held_object_id': 7}
    envelope = bind(snapshot, scene, 'pick', 7)
    session = SimpleNamespace(scene=scene, holding_object=7, execution_checkpoint=envelope)
    assert for_dispatch(session) == snapshot
    returned = for_dispatch(session)
    returned['held_object_id'] = 8
    assert for_dispatch(session)['held_object_id'] == 7
    # Use the actual durable model field, including backwards-compatible default.
    assert SessionState.model_fields['execution_checkpoint'].default is None
    session.scene = deepcopy(scene)
    session.scene['objects'][0]['position'][2] = 2
    with pytest.raises(ValueError, match='GRASP_RESTORE_FAILED'):
        for_dispatch(session)


def test_missing_stale_and_released_checkpoints():
    session = SimpleNamespace(scene={}, holding_object=7, execution_checkpoint=None)
    with pytest.raises(ValueError, match='GRASP_RESTORE_FAILED'):
        for_dispatch(session)
    with pytest.raises(ValueError, match='identity_mismatch'):
        bind({'schema_version': 1, 'source_request_id': 'old', 'held_object_id': 7}, {}, 'new', 7)
    session.holding_object = None
    assert for_dispatch(session) is None


def test_checkpoint_roundtrips_durable_session_state(tmp_path):
    from test_session_store import application
    from robot_agent_brain.session.store import SessionStore
    app = application(tmp_path)
    app.handle('two apples', session_id='physical')
    session = app.get_session('physical')
    held = session.scene.objects[0].object_id_in_scene
    snapshot = {'schema_version': 1, 'source_request_id': 'pick', 'held_object_id': held}
    envelope = bind(snapshot, session.scene, 'pick', held)
    session.holding_object = held
    session.execution_checkpoint = envelope
    store = app.store
    store.save('physical', session, revision=1)
    state = store.load('physical')
    assert state.execution_checkpoint == envelope
    other = application(tmp_path / 'other').get_session('physical')
    store.restore(state, other)
    assert other.execution_checkpoint == envelope
    assert for_dispatch(other) == snapshot


def test_browser_numeric_roundtrip_preserves_checkpoint():
    scene = {'scene_id': 3, 'scene_version': 4, 'objects': [
        {'object_id_in_scene': 7, 'position': [0.0, -0.0, 1.0],
         'quaternion_xyzw': [0.0, 0.0, 0.7071067811865476, 0.7071067811865476]}]}
    snapshot = {'schema_version': 1, 'source_request_id': 'pick', 'held_object_id': 7}
    session = SimpleNamespace(scene=deepcopy(scene), holding_object=7,
                              execution_checkpoint=bind(snapshot, scene, 'pick', 7))
    session.scene['objects'][0]['position'] = [0, 0, 1]
    session.scene['objects'][0]['quaternion_xyzw'][:2] = [0, 0]
    assert for_dispatch(session) == snapshot
    session.scene['objects'][0]['position'][0] = 1e-9
    with pytest.raises(ValueError, match='GRASP_RESTORE_FAILED'):
        for_dispatch(session)


def test_legacy_digest_stays_strict_and_unknown_versions_fail_closed():
    from robot_agent_brain.session.execution_checkpoint import scene_digest
    scene = {'value': 0.0}
    snapshot = {'held_object_id': 7}
    envelope = {'scene_digest': scene_digest(scene, canonical=False), 'snapshot': snapshot}
    session = SimpleNamespace(scene=scene, holding_object=7, execution_checkpoint=envelope)
    assert for_dispatch(session) == snapshot
    session.scene = {'value': 0}
    with pytest.raises(ValueError, match='GRASP_RESTORE_FAILED'):
        for_dispatch(session)
    envelope['digest_version'] = 99
    with pytest.raises(ValueError, match='GRASP_RESTORE_FAILED'):
        for_dispatch(session)
