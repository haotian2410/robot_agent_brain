"""Bind physical execution checkpoints to the committed session scene."""
from copy import deepcopy
import hashlib
import json


def _canonical_numbers(value):
    """JSON/browser round trips serialize 0.0 as 0; preserve numeric meaning."""
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, dict):
        return {key: _canonical_numbers(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_canonical_numbers(item) for item in value]
    return value


def scene_digest(scene, *, canonical=True):
    document = scene.raw_document() if hasattr(scene, 'raw_document') else scene
    if canonical:
        document = _canonical_numbers(document)
    return hashlib.sha256(json.dumps(document, sort_keys=True, separators=(',', ':'),
                                    ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def bind(snapshot, scene, request_id, holding_object):
    if snapshot is None:
        return None
    if (snapshot.get('schema_version') != 1 or snapshot.get('source_request_id') != request_id
            or snapshot.get('held_object_id') != holding_object or holding_object is None):
        raise ValueError('execution_checkpoint_identity_mismatch')
    return {'scene_digest': scene_digest(scene), 'digest_version': 2, 'snapshot': deepcopy(snapshot)}


def for_dispatch(session):
    envelope = getattr(session, 'execution_checkpoint', None)
    if session.holding_object is None:
        return None
    if envelope is None:
        raise ValueError('GRASP_RESTORE_FAILED: 已持有物体但缺少执行快照，请恢复场景后重新抓取')
    version = envelope.get('digest_version', 1)
    if (version not in (1, 2)
            or envelope['scene_digest'] != scene_digest(session.scene, canonical=version == 2)
            or envelope['snapshot']['held_object_id'] != session.holding_object):
        raise ValueError('GRASP_RESTORE_FAILED: 场景或持有关系已变化，旧抓持快照失效')
    return deepcopy(envelope['snapshot'])
