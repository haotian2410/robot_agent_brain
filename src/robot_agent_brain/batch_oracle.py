"""Independent assertions for semantic-matrix v2 runs.

The batch runner is intentionally not allowed to treat an ``answered`` or
``scene_updated`` envelope as proof that the requested edit happened.  This
module contains small, dependency-free assertions over the before/after Scene
documents.  It does not call Brain's selector, direction parser, layout
policy, or query implementation; those are the code under test.

The oracle is conservative.  When a requested assertion cannot be proven from
the supplied Scene evidence it returns ``not_checked``/``failed_assertion``
instead of claiming success.
"""
from __future__ import annotations

import math
from copy import deepcopy
from typing import Any

from .web.protocol import digest


SUCCESS_OUTCOMES = {"scene_updated", "answered", "plan_ready", "robot_setup_updated"}
UNCHANGED_EXPECTATIONS = {"answered", "clarification_required", "safe_rejection", "capability_unsupported"}


def _dump(value: Any) -> dict:
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    raise TypeError(f"oracle_scene_not_mapping:{type(value).__name__}")


def _oid(value: Any) -> str:
    # Scene IDs may arrive as uint32 JSON numbers or strings.  A canonical text
    # form avoids false changes when a browser serializes the same ID
    # differently.
    return str(value)


def _objects(scene: Any) -> dict[str, dict]:
    value = _dump(scene)
    return {_oid(item.get("object_id_in_scene")): item for item in value.get("objects", [])
            if isinstance(item, dict) and item.get("object_id_in_scene") is not None}


def _component(obj: dict | None, component_type: str) -> dict | None:
    if not obj:
        return None
    for component in obj.get("components", []):
        if isinstance(component, dict) and component.get("component_type") == component_type:
            return component.get("properties") or {}
    return None


def _semantic(obj: dict | None) -> str:
    value = _component(obj, "Semantic") or {}
    return str(value.get("semantic_name") or "").casefold()


def _category(obj: dict | None) -> str:
    value = _component(obj, "Semantic") or {}
    return str(value.get("category") or "").casefold()


def _metadata(obj: dict | None) -> tuple[str | None, str | None]:
    value = _component(obj, "MetadataRef") or {}
    return value.get("path"), value.get("type")


def _transform(obj: dict | None) -> dict:
    return _component(obj, "Transform") or {}


def _vec(value: Any, length: int = 3) -> tuple[float, ...] | None:
    if not isinstance(value, (list, tuple)) or len(value) != length:
        return None
    try:
        result = tuple(float(x) for x in value)
    except (TypeError, ValueError):
        return None
    return result if all(math.isfinite(x) for x in result) else None


def _close(a: float, b: float, tolerance: float) -> bool:
    return math.isfinite(a) and math.isfinite(b) and abs(a - b) <= tolerance


def _role_name(role_mapping: dict | None, role: str | None) -> str | None:
    if not role or not isinstance(role_mapping, dict):
        return None
    value = role_mapping.get(role)
    if not isinstance(value, dict):
        return None
    return str(value.get("semantic_name") or value.get("name") or "").casefold() or None


def _role_asset(role_mapping: dict | None, role: str | None) -> dict:
    value = role_mapping.get(role) if isinstance(role_mapping, dict) and role else {}
    return value if isinstance(value, dict) else {}


def _role_asset_type(role_mapping: dict | None, role: str | None) -> str | None:
    """Return the expected metadata namespace for a role.

    OLS model and robot references intentionally share numeric IDs.  The
    matrix catalog historically omitted ``type`` for model entries, so the
    oracle treats an omitted value as the catalog's default ``model`` rather
    than matching a robot with the same ``$LIBRARY_SERVER/<id>`` path.
    """
    asset = _role_asset(role_mapping, role)
    if not asset:
        return None
    value = asset.get("type") or asset.get("asset_type")
    return str(value).casefold() if value else "model"


def _find_by_role(scene_objects: dict[str, dict], role: str | None,
                  role_mapping: dict | None, *, exclude: set[str] | None = None) -> list[tuple[str, dict]]:
    name = _role_name(role_mapping, role)
    asset = _role_asset(role_mapping, role)
    metadata_ref = asset.get("metadata_ref")
    metadata_type = _role_asset_type(role_mapping, role)
    exclude = exclude or set()
    result = []
    for oid, obj in scene_objects.items():
        if oid in exclude:
            continue
        ref, kind = _metadata(obj)
        # Match both namespace and path.  A model:3 baseball must not be
        # confused with robot:3 wrist/overhead cameras in the same scene.
        if metadata_ref and ref == metadata_ref and (metadata_type is None or kind == metadata_type):
            result.append((oid, obj))
        elif name and _semantic(obj) == name and (metadata_type is None or kind in {metadata_type, None}):
            result.append((oid, obj))
    return result


def _find_primary_table(objects: dict[str, dict], role_mapping: dict | None) -> tuple[str, dict] | None:
    surface = _find_by_role(objects, "surface_1", role_mapping)
    if len(surface) == 1:
        return surface[0]
    candidates = [(oid, obj) for oid, obj in objects.items()
                  if _semantic(obj) in {"table", "desk", "desktop", "work_table"}
                  and _category(obj) in {"surface", "support_surface", "table", "furniture", ""}]
    return candidates[0] if len(candidates) == 1 else None


def _scene_changed(before: Any, after: Any) -> bool:
    if before is None or after is None:
        return False
    return digest(_dump(before)) != digest(_dump(after))


def _scene_identity_changed(before: Any, after: Any) -> bool:
    if before is None or after is None:
        return False
    left, right = _dump(before), _dump(after)
    return (left.get("scene_id"), left.get("scene_version"), left.get("scene_sub_version", 0), digest(left)) != (
        right.get("scene_id"), right.get("scene_version"), right.get("scene_sub_version", 0), digest(right))


def _append(checks: list[dict], name: str, passed: bool, **details):
    checks.append({"name": name, "passed": bool(passed), **details})


def _expected_error(result: dict) -> str | None:
    if not isinstance(result, dict):
        return None
    error = result.get("error")
    if isinstance(error, dict):
        return error.get("code")
    return result.get("error_code")


def _check_new_object(expected: dict, before: dict[str, dict], after: dict[str, dict],
                      role_mapping: dict | None, checks: list[dict], errors: list[str]):
    before_ids, after_ids = set(before), set(after)
    added = sorted(after_ids - before_ids, key=lambda x: (len(x), x))
    count = expected.get("count")
    if count is not None:
        ok = len(added) == int(count)
        _append(checks, "added_object_count", ok, expected=int(count), actual=len(added), ids=added)
        if not ok:
            errors.append("added_object_count")
    role = expected.get("target_role")
    if role and added:
        target_name = _role_name(role_mapping, role)
        matching = [oid for oid in added if not target_name or _semantic(after[oid]) == target_name]
        ok = len(matching) >= 1
        _append(checks, "added_object_role", ok, role=role, expected_semantic=target_name,
                matching_ids=matching)
        if not ok:
            errors.append("added_object_role")
        asset = _role_asset(role_mapping, role)
        expected_ref = asset.get("metadata_ref")
        if expected_ref and matching:
            refs = [_metadata(after[oid])[0] for oid in matching]
            ok = expected_ref in refs
            _append(checks, "added_object_asset", ok, expected_metadata_ref=expected_ref, actual_refs=refs)
            if not ok:
                errors.append("added_object_asset")
    support = expected.get("support")
    if support == "primary_table" and added:
        table = _find_primary_table(after, role_mapping)
        table_id = table[0] if table else None
        supported = []
        for oid in added:
            semantic = _component(after[oid], "Semantic") or {}
            if _oid(semantic.get("support")) == _oid(table_id) and table_id is not None:
                supported.append(oid)
        # Some browser fixtures omit support while still placing a model on a
        # configured tabletop.  Treat that as unproven, never as a pass.
        ok = table_id is not None and len(supported) == len(added)
        _append(checks, "primary_table_support", ok, table_id=table_id, supported_ids=supported,
                added_ids=added)
        if not ok:
            errors.append("primary_table_support")
    region = expected.get("region")
    if region and region != "any" and added:
        table = _find_primary_table(after, role_mapping)
        table_transform = _transform(table[1]) if table else {}
        center = _vec(table_transform.get("position"))
        positions = [_vec(_transform(after[oid]).get("position")) for oid in added]
        if not table or center is None or any(position is None for position in positions):
            _append(checks, "region_position_evidence", False, region=region, reason="missing_table_or_transform")
            errors.append("region_position_evidence")
        else:
            # Without geometry dimensions, this oracle can prove the sign of a
            # region but not footprint containment.  Geometry containment is a
            # separate check in the editor and is reported as unproven here.
            dx, dy = positions[0][0] - center[0], positions[0][1] - center[1]
            signs = {
                "right_half": dx > 0, "left_half": dx < 0,
                "front_half": dy > 0, "back_half": dy < 0,
                "right_front": dx > 0 and dy > 0, "left_front": dx < 0 and dy > 0,
                "right_back": dx > 0 and dy < 0, "left_back": dx < 0 and dy < 0,
            }
            ok = bool(signs.get(region, False))
            if region == "center":
                ok = _close(dx, 0.0, 1e-4) and _close(dy, 0.0, 1e-4)
            _append(checks, "region_position_sign", ok, region=region, dx=dx, dy=dy)
            if not ok:
                errors.append("region_position_sign")


def _check_transform_operation(expected: dict, before: dict[str, dict], after: dict[str, dict],
                               role_mapping: dict | None, checks: list[dict], errors: list[str]):
    role = expected.get("target_role")
    before_matches = _find_by_role(before, role, role_mapping)
    after_matches = _find_by_role(after, role, role_mapping)
    if len(before_matches) != 1 or len(after_matches) != 1:
        _append(checks, "unique_target_instance", False, role=role,
                before_count=len(before_matches), after_count=len(after_matches))
        errors.append("unique_target_instance")
        return
    before_id, before_obj = before_matches[0]
    after_id, after_obj = after_matches[0]
    if expected.get("preserve_instance"):
        ok = before_id == after_id
        _append(checks, "instance_preserved", ok, before_id=before_id, after_id=after_id)
        if not ok:
            errors.append("instance_preserved")
    operation = expected.get("operation")
    if operation == "translate":
        bp, ap = _vec(_transform(before_obj).get("position")), _vec(_transform(after_obj).get("position"))
        direction = expected.get("direction")
        distance = expected.get("distance_m")
        if bp is None or ap is None:
            _append(checks, "translation_evidence", False, reason="missing_position")
            errors.append("translation_evidence")
        else:
            delta = tuple(ap[i] - bp[i] for i in range(3))
            axis, sign = {"right": (0, 1), "left": (0, -1), "front": (1, 1), "back": (1, -1),
                          "up": (2, 1), "down": (2, -1)}.get(direction, (None, None))
            ok = axis is not None and delta[axis] * sign > 0
            if distance is not None and axis is not None:
                ok = ok and _close(abs(delta[axis]), float(distance), 1e-4)
            _append(checks, "translation_delta", ok, direction=direction, expected_distance_m=distance,
                    actual_delta=delta)
            if not ok:
                errors.append("translation_delta")
    elif operation == "rotate":
        bq, aq = _vec(_transform(before_obj).get("quaternion_xyzw"), 4), _vec(_transform(after_obj).get("quaternion_xyzw"), 4)
        # A rotation assertion needs a changed quaternion.  Exact angle
        # extraction is intentionally conservative; the canonical payload is
        # still retained for a future fixture-specific matrix comparison.
        ok = bq is not None and aq is not None and any(abs(aq[i] - bq[i]) > 1e-5 for i in range(4))
        _append(checks, "rotation_changed", ok, before_quaternion=bq, after_quaternion=aq,
                expected_axis=expected.get("axis"), expected_angle_deg=expected.get("angle_deg"))
        if not ok:
            errors.append("rotation_changed")
    elif operation == "update_properties":
        before_pose = _transform(before_obj)
        after_pose = _transform(after_obj)
        pose_ok = before_pose.get("position") == after_pose.get("position") and before_pose.get("quaternion_xyzw") == after_pose.get("quaternion_xyzw")
        color = _component(after_obj, "MeshRenderer") or {}
        requested = expected.get("color")
        color_ok = str(color.get("forceOverrideColor", "")).upper() == str(requested or "").upper() or (requested in {"blue", "green", "red"} and str(color.get("forceOverrideColor", "")).upper() in {"#0000FF", "#00FF00", "#FF0000"})
        _append(checks, "color_override", color_ok, expected_color=requested, actual_color=color.get("forceOverrideColor"))
        _append(checks, "pose_preserved", pose_ok)
        if not color_ok:
            errors.append("color_override")
        if not pose_ok:
            errors.append("pose_preserved")
    elif operation == "scale":
        bs, ass = _vec(_transform(before_obj).get("scale")), _vec(_transform(after_obj).get("scale"))
        ok = bs is not None and ass is not None and any(abs(ass[i] - bs[i]) > 1e-5 for i in range(3))
        _append(checks, "scale_changed", ok, before_scale=bs, after_scale=ass)
        if not ok:
            errors.append("scale_changed")


def evaluate_turn(*args, expected: dict | None = None, expected_outcome: str | None = None,
                  before_scene: Any = None, after_scene: Any = None, result: dict | None = None,
                  role_mapping: dict | None = None, state: dict | None = None,
                  tolerance: float = 1e-4) -> dict:
    """Evaluate one matrix turn with an independent Scene oracle.

    ``expected`` may be supplied positionally as a compatibility convenience.
    The returned object is JSON serializable and deliberately carries both
    protocol checks and geometry checks, even when the actual task failed.
    """
    if args:
        if expected is None and isinstance(args[0], dict):
            expected = args[0]
        else:
            raise TypeError("oracle_expected_must_be_mapping")
    expected = expected or {}
    result = result or {}
    before = _objects(before_scene)
    after = _objects(after_scene)
    actual = result.get("outcome") or result.get("failure_class")
    expected_outcome = expected_outcome or expected.get("expected_outcome") or "scene_updated"
    checks: list[dict] = []
    errors: list[str] = []

    changed = _scene_changed(before_scene, after_scene)
    if expected_outcome in UNCHANGED_EXPECTATIONS or expected.get("scene_unchanged"):
        ok = not changed
        _append(checks, "scene_unchanged", ok, before_digest=digest(_dump(before_scene)) if before_scene is not None else None,
                after_digest=digest(_dump(after_scene)) if after_scene is not None else None)
        if not ok:
            errors.append("scene_changed_when_unchanged_expected")
    elif expected_outcome in {"scene_updated", "plan_ready", "robot_setup_updated", "semantic_accepted"}:
        if expected_outcome != "semantic_accepted":
            ok = changed
            _append(checks, "scene_changed", ok, actual_outcome=actual)
            if not ok:
                errors.append("scene_not_changed")
        _append(checks, "executed_false", result.get("executed", False) is False,
                actual_executed=result.get("executed"))
        if result.get("executed", False) is not False:
            errors.append("executed_not_false")

    allowed = expected.get("allowed_error_codes") or expected.get("error_codes") or []
    if allowed:
        code = _expected_error(result)
        ok = code in allowed
        _append(checks, "error_code", ok, expected=allowed, actual=code)
        if not ok:
            errors.append("error_code")

    if expected_outcome == "scene_updated" and not errors:
        operation = expected.get("operation")
        if operation == "add" or "operations" in expected:
            _check_new_object(expected, before, after, role_mapping, checks, errors)
        elif operation in {"translate", "rotate", "update_properties", "scale"}:
            _check_transform_operation(expected, before, after, role_mapping, checks, errors)
        elif operation == "remove":
            role = expected.get("target_role")
            before_matches = _find_by_role(before, role, role_mapping)
            after_matches = _find_by_role(after, role, role_mapping)
            expected_count = int(expected.get("count", 1))
            ok = len(before_matches) - len(after_matches) == expected_count
            _append(checks, "removed_object_count", ok, before_count=len(before_matches), after_count=len(after_matches), expected=expected_count)
            if not ok:
                errors.append("removed_object_count")
        elif operation == "replace":
            old = _find_by_role(before, expected.get("target_role"), role_mapping)
            new = _find_by_role(after, expected.get("replacement_role"), role_mapping)
            ok = bool(old) and bool(new) and not ({oid for oid, _ in old} & {oid for oid, _ in new})
            _append(checks, "replacement_new_instance", ok, old_ids=[oid for oid, _ in old], new_ids=[oid for oid, _ in new])
            if not ok:
                errors.append("replacement_new_instance")

    if expected_outcome == "plan_ready":
        ok = isinstance(result.get("plan") or result.get("commands"), dict) or bool(result.get("artifacts"))
        _append(checks, "plan_artifact_present", ok)
        if not ok:
            errors.append("plan_artifact_present")

    protocol_error = bool(result.get("error") and actual in {"failed", "provider_error"})
    if protocol_error and expected_outcome not in {"safe_rejection", "clarification_required", "capability_unsupported"}:
        errors.append("unexpected_runtime_or_protocol_error")
        _append(checks, "no_unexpected_error", False, error=result.get("error"))

    if errors:
        status = "failed_assertion" if not protocol_error else "failed_protocol/runtime"
    elif expected_outcome == "clarification_required":
        status = "expected_clarification"
    elif expected_outcome == "safe_rejection":
        status = "expected_safe_rejection"
    elif expected_outcome == "capability_unsupported":
        status = "expected_safe_rejection"
    else:
        status = "passed"
    return {"status": status, "checks": checks, "errors": errors,
            "actual_outcome": actual, "expected_outcome": expected_outcome,
            "before_digest": digest(_dump(before_scene)) if before_scene is not None else None,
            "after_digest": digest(_dump(after_scene)) if after_scene is not None else None,
            "changed": changed, "details": {"before_object_ids": sorted(before), "after_object_ids": sorted(after)}}
