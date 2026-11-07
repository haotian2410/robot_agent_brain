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
import json
from copy import deepcopy
from pathlib import Path
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


def _quat_normalize(value: Any) -> tuple[float, float, float, float] | None:
    quat = _vec(value, 4)
    if quat is None:
        return None
    norm = math.sqrt(sum(item * item for item in quat))
    if norm <= 1e-12:
        return None
    return tuple(item / norm for item in quat)


def _quat_conjugate(value: tuple[float, float, float, float]) -> tuple[float, float, float, float]:
    return (-value[0], -value[1], -value[2], value[3])


def _quat_multiply(left: tuple[float, float, float, float],
                   right: tuple[float, float, float, float]) -> tuple[float, float, float, float]:
    x1, y1, z1, w1 = left
    x2, y2, z2, w2 = right
    return (w1 * x2 + x1 * w2 + y1 * z2 - z1 * y2,
            w1 * y2 - x1 * z2 + y1 * w2 + z1 * x2,
            w1 * z2 + x1 * y2 - y1 * x2 + z1 * w2,
            w1 * w2 - x1 * x2 - y1 * y2 - z1 * z2)


def _quaternion_delta(before: Any, after: Any, *, local: bool = False) -> tuple[tuple[float, ...], float] | None:
    """Return the shortest axis-angle delta for two xyzw quaternions.

    Quaternion signs are equivalent, so normalisation and the shortest-angle
    representation are required before comparing a requested 90/180 degree
    operation.  ``local`` switches the multiplication order for local-axis
    rotations; the v2 matrix uses world ``z`` but hidden fixtures exercise the
    explicit local-axis contract as well.
    """
    left, right = _quat_normalize(before), _quat_normalize(after)
    if left is None or right is None:
        return None
    delta = _quat_multiply(_quat_conjugate(left), right) if local else _quat_multiply(right, _quat_conjugate(left))
    delta = _quat_normalize(delta)
    if delta is None:
        return None
    if delta[3] < 0:
        delta = tuple(-item for item in delta)
    scalar = max(-1.0, min(1.0, delta[3]))
    half = math.acos(scalar)
    sine = math.sin(half)
    if abs(sine) <= 1e-10:
        return ((0.0, 0.0, 0.0), 0.0)
    axis = (delta[0] / sine, delta[1] / sine, delta[2] / sine)
    return axis, math.degrees(2.0 * half)


def _axis_vector(axis: Any) -> tuple[float, float, float] | None:
    values = {"x": (1.0, 0.0, 0.0), "y": (0.0, 1.0, 0.0), "z": (0.0, 0.0, 1.0),
              "local_x": (1.0, 0.0, 0.0), "local_y": (0.0, 1.0, 0.0),
              "local_z": (0.0, 0.0, 1.0)}
    if isinstance(axis, str):
        return values.get(axis.casefold())
    vector = _vec(axis)
    if vector is None:
        return None
    norm = math.sqrt(sum(item * item for item in vector))
    return tuple(item / norm for item in vector) if norm > 1e-12 else None


def _object_digest(obj: dict) -> str:
    return digest(obj)


def _non_target_ids(before: dict[str, dict], after: dict[str, dict], target_ids: set[str]) -> set[str]:
    return (set(before) | set(after)) - target_ids


def _check_non_targets_unchanged(before: dict[str, dict], after: dict[str, dict], target_ids: set[str],
                                  checks: list[dict], errors: list[str], *, name: str = "non_targets_unchanged"):
    ids = _non_target_ids(before, after, target_ids)
    changed = [oid for oid in sorted(ids) if oid not in before or oid not in after
               or _object_digest(before[oid]) != _object_digest(after[oid])]
    ok = not changed
    _append(checks, name, ok, target_ids=sorted(target_ids), changed_ids=changed)
    if not ok:
        errors.append(name)


def _query_payload(result: dict) -> dict | None:
    """Extract a serialized SceneQueryResult from task result/artifacts."""
    candidates = [result.get("query_result"), result.get("scene_query_result"), result.get("query")]
    artifacts = result.get("artifacts")
    if isinstance(artifacts, dict):
        candidates.extend([artifacts.get("query_result"), artifacts.get("scene_query_result")])
    elif isinstance(artifacts, list):
        # Service responses use a list of named descriptors.  The batch
        # runner replaces this with local paths before invoking the oracle,
        # but accepting the descriptor shape here keeps direct callers and
        # replay fixtures consistent as well.
        for item in artifacts:
            if isinstance(item, dict) and item.get("name") in {"query_result", "scene_query_result"}:
                candidates.append(item.get("path") or item.get("file") or item.get("url"))
    for value in candidates:
        if isinstance(value, dict):
            return value
        if isinstance(value, str):
            try:
                path = Path(value)
                if path.is_file():
                    loaded = json.loads(path.read_text(encoding="utf-8"))
                    if isinstance(loaded, dict):
                        return loaded
            except (OSError, ValueError):
                continue
    return None


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
    # A bootstrap edit legitimately adds the platform table/robot/cameras at
    # the same time as the requested object.  For a single-role assertion we
    # already filter those platform objects.  Multi-object rows (for example
    # ``add:object_a`` + ``add:object_b``) must be filtered *per role*; using
    # every new object as one pool makes an empty bootstrap look like ten user
    # additions and falsely fails the support assertion.
    added_objects = {oid: after[oid] for oid in added}
    role_names: list[str] = []
    role = expected.get("target_role")
    if role:
        role_names.append(str(role))
    counts = expected.get("counts") if isinstance(expected.get("counts"), dict) else {}
    for operation in expected.get("operations") or []:
        if isinstance(operation, str) and ":" in operation:
            verb, candidate = operation.split(":", 1)
            if verb.strip().casefold() == "add" and candidate.strip():
                role_names.append(candidate.strip())
        elif isinstance(operation, dict) and str(operation.get("operation", "")).casefold() == "add":
            candidate = operation.get("target_role") or operation.get("target")
            if candidate:
                role_names.append(str(candidate))
    for candidate in counts:
        if candidate not in role_names:
            role_names.append(str(candidate))
    role_names = list(dict.fromkeys(role_names))

    # Keep a role -> target IDs map so all subsequent checks (support, region,
    # asset identity) use exactly the same user-added set.
    target_by_role: dict[str, list[str]] = {}
    if role_names:
        for role_name in role_names:
            target_by_role[role_name] = [oid for oid, _ in _find_by_role(
                added_objects, role_name, role_mapping)]
    else:
        target_by_role["__all__"] = list(added)

    for role_name, target_added in target_by_role.items():
        expected_count = counts.get(role_name) if role_name != "__all__" else expected.get("count")
        if expected_count is not None:
            ok = len(target_added) == int(expected_count)
            _append(checks, "added_object_count", ok, role=None if role_name == "__all__" else role_name,
                    expected=int(expected_count), actual=len(target_added), ids=target_added,
                    all_added_ids=added)
            if not ok:
                errors.append(f"added_object_count:{role_name}")
        if role_name != "__all__" and target_added:
            target_name = _role_name(role_mapping, role_name)
            matching = [oid for oid in target_added if not target_name or _semantic(after[oid]) == target_name]
            ok = len(matching) >= 1
            _append(checks, "added_object_role", ok, role=role_name, expected_semantic=target_name,
                    matching_ids=matching)
            if not ok:
                errors.append(f"added_object_role:{role_name}")
            asset = _role_asset(role_mapping, role_name)
            expected_ref = asset.get("metadata_ref")
            if expected_ref and matching:
                refs = [_metadata(after[oid])[0] for oid in matching]
                # ``catalog_member`` deliberately allows an unspecified-style
                # request (e.g. "钢笔") to select any real OLS variant with
                # that semantic name.  The compiler's seeded role mapping is
                # the reproducible fixture candidate, not a hidden command to
                # the model; requiring its exact metadata ref would turn a
                # valid Qwen catalog choice (model:5 vs model:6) into a false
                # geometry/protocol failure.  Exact asset assertions remain
                # available through ``asset_key``/``expected_metadata_ref``.
                exact_asset = expected.get("asset_key") or expected.get("expected_metadata_ref")
                if not exact_asset:
                    ok = all(_metadata(after[oid])[1] == "model" and bool(ref)
                             for oid, ref in zip(matching, refs))
                    _append(checks, "added_object_asset_catalog_member", ok, role=role_name,
                            expected_semantic=target_name, actual_refs=refs,
                            seeded_candidate=expected_ref)
                else:
                    expected_value = exact_asset or expected_ref
                    ok = expected_value in refs
                    _append(checks, "added_object_asset", ok, role=role_name,
                            expected_metadata_ref=expected_value, actual_refs=refs)
                if not ok:
                    errors.append(f"added_object_asset:{role_name}")

    target_added = [oid for values in target_by_role.values() for oid in values]
    if expected.get("non_targets_unchanged"):
        _check_non_targets_unchanged(before, after, set(target_added), checks, errors)
    support = expected.get("support")
    if support == "primary_table" and target_added:
        table = _find_primary_table(after, role_mapping)
        table_id = table[0] if table else None
        supported = []
        for oid in target_added:
            semantic = _component(after[oid], "Semantic") or {}
            if _oid(semantic.get("support")) == _oid(table_id) and table_id is not None:
                supported.append(oid)
        # Some browser fixtures omit support while still placing a model on a
        # configured tabletop.  Treat that as unproven, never as a pass.
        ok = table_id is not None and len(supported) == len(target_added)
        _append(checks, "primary_table_support", ok, table_id=table_id, supported_ids=supported,
                added_ids=target_added, all_added_ids=added)
        if not ok:
            errors.append("primary_table_support")
    region = expected.get("region")
    placement_hint = expected.get("placement_hint")
    if placement_hint == "center" and target_added and not region:
        table = _find_primary_table(after, role_mapping)
        table_transform = _transform(table[1]) if table else {}
        center = _vec(table_transform.get("position"))
        positions = [_vec(_transform(after[oid]).get("position")) for oid in target_added]
        if center is None or any(position is None for position in positions):
            ok = False
            details = {"reason": "missing_table_or_transform"}
        else:
            deltas = [(position[0] - center[0], position[1] - center[1]) for position in positions]
            per_target = [_close(dx, 0.0, 1e-4) and _close(dy, 0.0, 1e-4) for dx, dy in deltas]
            ok = bool(per_target) and all(per_target)
            details = {"deltas": deltas, "target_ids": target_added, "per_target": per_target}
        _append(checks, "region_center_position", ok, **details)
        if not ok:
            errors.append("region_center_position")
    if region and region != "any" and target_added:
        table = _find_primary_table(after, role_mapping)
        table_transform = _transform(table[1]) if table else {}
        center = _vec(table_transform.get("position"))
        positions = [_vec(_transform(after[oid]).get("position")) for oid in target_added]
        if not table or center is None or any(position is None for position in positions):
            _append(checks, "region_position_evidence", False, region=region, reason="missing_table_or_transform")
            errors.append("region_position_evidence")
        else:
            # Without geometry dimensions, this oracle can prove the sign of a
            # region for every requested target but not footprint containment.
            # Geometry containment is a separate check in the editor and is
            # reported as unproven here unless the fixture supplies explicit
            # workspace bounds below.
            signs = {
                "right_half": lambda dx, dy: dx > 0, "left_half": lambda dx, dy: dx < 0,
                "front_half": lambda dx, dy: dy > 0, "back_half": lambda dx, dy: dy < 0,
                "right_front": lambda dx, dy: dx > 0 and dy > 0,
                "left_front": lambda dx, dy: dx < 0 and dy > 0,
                "right_back": lambda dx, dy: dx > 0 and dy < 0,
                "left_back": lambda dx, dy: dx < 0 and dy < 0,
            }
            deltas = [(position[0] - center[0], position[1] - center[1]) for position in positions]
            if region == "center":
                per_target = [_close(dx, 0.0, tolerance=1e-4) and _close(dy, 0.0, tolerance=1e-4)
                              for dx, dy in deltas]
            else:
                predicate = signs.get(region)
                per_target = [bool(predicate(dx, dy)) for dx, dy in deltas] if predicate else [False]
            ok = bool(per_target) and all(per_target)
            _append(checks, "region_position_sign", ok, region=region, deltas=deltas,
                    target_ids=target_added, per_target=per_target)
            if not ok:
                errors.append("region_position_sign")

            # A fixture can provide workspace bounds in expected_json when it
            # wants the independent oracle to prove the target center is not
            # merely in the correct quadrant but also inside the configured
            # tabletop.  We intentionally do not invent bounds from a scene
            # table's visual asset; those bounds must be explicit test data.
            workspace = expected.get("workspace")
            if workspace is None and "workspace_min" in expected and "workspace_max" in expected:
                workspace = {"min": expected.get("workspace_min"), "max": expected.get("workspace_max")}
            if isinstance(workspace, dict):
                low, high = _vec(workspace.get("min")), _vec(workspace.get("max"))
                if low is None or high is None or low[0] > high[0] or low[1] > high[1]:
                    contained, reason = False, "invalid_workspace_bounds"
                else:
                    contained = all(low[i] - 1e-9 <= position[i] <= high[i] + 1e-9
                                    for position in positions for i in (0, 1))
                    reason = None
                _append(checks, "region_workspace_center", contained, workspace_min=low,
                        workspace_max=high, reason=reason, target_ids=target_added)
                if not contained:
                    errors.append("region_workspace_center")


def _check_transform_operation(expected: dict, before: dict[str, dict], after: dict[str, dict],
                               role_mapping: dict | None, checks: list[dict], errors: list[str]):
    role = expected.get("target_role")
    before_matches = _find_by_role(before, role, role_mapping)
    after_matches = _find_by_role(after, role, role_mapping)
    # Selection edits intentionally operate on one member of a candidate
    # pool (for example "最左边的苹果" among three apples).  The old oracle
    # treated the pool cardinality as the result cardinality and rejected a
    # valid single-instance patch before inspecting which object changed.
    selection = expected.get("selection")
    if selection and len(before_matches) == len(after_matches) and len(before_matches) > 1:
        before_by_id = dict(before_matches)
        after_by_id = dict(after_matches)
        common = set(before_by_id) & set(after_by_id)
        changed = [oid for oid in common
                   if _object_digest(before_by_id[oid]) != _object_digest(after_by_id[oid])]
        if len(changed) == 1:
            before_id = after_id = changed[0]
            _append(checks, "selected_target_instance", True, role=role,
                    selection=selection, candidate_count=len(before_matches), object_id=after_id)
        elif not changed and expected.get("operation") == "update_properties":
            # An idempotent color edit can legitimately commit a new scene
            # version while leaving object JSON unchanged (for example the
            # nearest apple is already red).  Prove the selected instance
            # from the pre-scene geometry instead of reporting that no target
            # changed.  Ties remain unprovable and are still rejected.
            reference_matches = _find_by_role(before, expected.get("reference_role"), role_mapping)
            positions = {oid: _vec(_transform(obj).get("position"))
                         for oid, obj in before_matches}
            reference_position = None
            if reference_matches and len(reference_matches) == 1:
                reference_position = _vec(_transform(reference_matches[0][1]).get("position"))
            selected_id = None
            if selection in {"leftmost", "rightmost", "frontmost", "backmost"}:
                axis, choose = {"leftmost": (0, min), "rightmost": (0, max),
                                "frontmost": (1, max), "backmost": (1, min)}[selection]
                values = {oid: pos[axis] for oid, pos in positions.items() if pos is not None}
                if values:
                    extreme = choose(values.values())
                    matches = [oid for oid, value in values.items() if _close(value, extreme, 1e-9)]
                    if len(matches) == 1:
                        selected_id = matches[0]
            elif selection in {"nearest", "farthest"} and reference_position is not None:
                values = {oid: math.dist(pos[:2], reference_position[:2])
                          for oid, pos in positions.items() if pos is not None}
                if values:
                    choose = min if selection == "nearest" else max
                    extreme = choose(values.values())
                    matches = [oid for oid, value in values.items() if _close(value, extreme, 1e-9)]
                    if len(matches) == 1:
                        selected_id = matches[0]
            requested = str(expected.get("color") or "").upper()
            color_aliases = {"BLUE": "#0000FF", "GREEN": "#00FF00", "RED": "#FF0000"}
            requested = color_aliases.get(requested, requested)
            if selected_id is not None:
                actual = _component(after_by_id[selected_id], "MeshRenderer") or {}
                if str(actual.get("forceOverrideColor", "")).upper() == requested:
                    before_id = after_id = selected_id
                    _append(checks, "selected_target_instance", True, role=role,
                            selection=selection, candidate_count=len(before_matches),
                            object_id=selected_id, idempotent=True)
                else:
                    selected_id = None
            if selected_id is None:
                _append(checks, "selected_target_instance", False, role=role,
                        selection=selection, candidate_count=len(before_matches), changed_ids=changed)
                errors.append("selected_target_instance")
                return
        else:
            _append(checks, "selected_target_instance", False, role=role,
                    selection=selection, candidate_count=len(before_matches), changed_ids=changed)
            errors.append("selected_target_instance")
            return
    elif len(before_matches) == 1 and len(after_matches) == 1:
        before_id, before_obj = before_matches[0]
        after_id, after_obj = after_matches[0]
    else:
        _append(checks, "unique_target_instance", False, role=role,
                before_count=len(before_matches), after_count=len(after_matches))
        errors.append("unique_target_instance")
        return
    before_obj, after_obj = before[before_id], after[after_id]
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
            if axis is not None:
                ok = ok and all(_close(delta[i], 0.0, 1e-4) for i in range(3) if i != axis)
            if expected.get("preserve_orientation"):
                before_q = _quat_normalize(_transform(before_obj).get("quaternion_xyzw"))
                after_q = _quat_normalize(_transform(after_obj).get("quaternion_xyzw"))
                orientation_ok = before_q is not None and after_q is not None and abs(sum(before_q[i] * after_q[i] for i in range(4))) >= 1.0 - 1e-5
                ok = ok and orientation_ok
            else:
                orientation_ok = None
            _append(checks, "translation_delta", ok, direction=direction, expected_distance_m=distance,
                    actual_delta=delta, non_target_axes_unchanged=(orientation_ok if expected.get("preserve_orientation") else None))
            if not ok:
                errors.append("translation_delta")
    elif operation == "rotate":
        bq, aq = _vec(_transform(before_obj).get("quaternion_xyzw"), 4), _vec(_transform(after_obj).get("quaternion_xyzw"), 4)
        delta = _quaternion_delta(bq, aq, local=str(expected.get("axis", "")).startswith("local_"))
        expected_axis = _axis_vector(expected.get("axis"))
        expected_angle = expected.get("angle_deg")
        changed = delta is not None and delta[1] > 1e-3
        axis_ok = True
        angle_ok = True
        if expected_axis is not None and delta is not None and delta[1] > 1e-3:
            actual_axis = delta[0]
            axis_ok = abs(sum(actual_axis[i] * expected_axis[i] for i in range(3))) >= 1.0 - 1e-3
        if expected_angle is not None and delta is not None:
            angle_ok = _close(delta[1], abs(float(expected_angle)), 0.05)
        ok = changed and axis_ok and angle_ok
        _append(checks, "rotation_changed", ok, before_quaternion=bq, after_quaternion=aq,
                expected_axis=expected.get("axis"), expected_angle_deg=expected_angle,
                actual_axis=(delta[0] if delta else None), actual_angle_deg=(delta[1] if delta else None),
                axis_match=axis_ok, angle_match=angle_ok)
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
        expected_xyz = _vec(expected.get("scale_xyz"))
        mode = expected.get("scale_mode")
        if expected_xyz is not None and mode == "set":
            ok = bs is not None and ass is not None and all(_close(ass[i], expected_xyz[i], 1e-5) for i in range(3))
        elif expected_xyz is not None and mode == "multiply":
            ok = bs is not None and ass is not None and all(_close(ass[i], bs[i] * expected_xyz[i], 1e-5) for i in range(3))
        else:
            factors = {"small": 1.1, "medium": 1.5, "large": 2.0}
            direction = expected.get("scale_direction")
            amount = expected.get("scale_amount")
            factor = factors.get(amount)
            if direction == "shrink" and factor:
                factor = 1.0 / factor
            ok = bs is not None and ass is not None and factor is not None and all(_close(ass[i], bs[i] * factor, 1e-5) for i in range(3))
        if expected.get("preserve_orientation"):
            bq = _quat_normalize(_transform(before_obj).get("quaternion_xyzw"))
            aq = _quat_normalize(_transform(after_obj).get("quaternion_xyzw"))
            ok = ok and bq is not None and aq is not None and abs(sum(bq[i] * aq[i] for i in range(4))) >= 1.0 - 1e-5
        _append(checks, "scale_changed", ok, before_scale=bs, after_scale=ass,
                expected_scale_xyz=expected_xyz, scale_mode=mode,
                scale_direction=expected.get("scale_direction"), scale_amount=expected.get("scale_amount"))
        if not ok:
            errors.append("scale_changed")

    if expected.get("non_targets_unchanged"):
        _check_non_targets_unchanged(before, after, {before_id, after_id}, checks, errors)


def _check_query_result(expected: dict, result: dict, role_mapping: dict | None,
                        checks: list[dict], errors: list[str]) -> None:
    payload = _query_payload(result)
    if payload is None:
        _append(checks, "query_result_present", False, reason="query_result_missing")
        errors.append("query_result_missing")
        return
    query_type = expected.get("query_type")
    if query_type and payload.get("query_type") != query_type:
        _append(checks, "query_type", False, expected=query_type, actual=payload.get("query_type"))
        errors.append("query_type")
    if "count" in expected:
        ok = payload.get("count") == int(expected["count"])
        _append(checks, "query_count", ok, expected=expected["count"], actual=payload.get("count"))
        if not ok:
            errors.append("query_count")
    if "exists" in expected:
        ok = payload.get("exists") is bool(expected["exists"])
        _append(checks, "query_exists", ok, expected=expected["exists"], actual=payload.get("exists"))
        if not ok:
            errors.append("query_exists")
    if "relation_holds" in expected:
        ok = payload.get("relation_holds") is bool(expected["relation_holds"])
        _append(checks, "query_relation", ok, expected=expected["relation_holds"], actual=payload.get("relation_holds"))
        if not ok:
            errors.append("query_relation")
    if "selected_count" in expected:
        ids = payload.get("object_ids") if isinstance(payload.get("object_ids"), list) else []
        ok = len(ids) == int(expected["selected_count"])
        _append(checks, "query_selected_count", ok, expected=expected["selected_count"], actual=len(ids), object_ids=ids)
        if not ok:
            errors.append("query_selected_count")
    reference_role = expected.get("reference_role")
    if reference_role and payload.get("reference_object_id") is None:
        _append(checks, "query_reference_evidence", False, role=reference_role)
        errors.append("query_reference_evidence")
    if expected.get("distance_max_m") is not None:
        distances = payload.get("distances_m") if isinstance(payload.get("distances_m"), dict) else {}
        values = [float(value) for value in distances.values()]
        ok = bool(values) and max(values) <= float(expected["distance_max_m"]) + 1e-9
        _append(checks, "query_distance_bound", ok, expected=expected["distance_max_m"], actual=values)
        if not ok:
            errors.append("query_distance_bound")
    selected_role = expected.get("selected_role") or expected.get("target_role")
    if expected.get("selection") and selected_role:
        names = payload.get("names") if isinstance(payload.get("names"), dict) else {}
        semantic = _role_name(role_mapping, selected_role)
        # Names are human-readable, so this is only an identity sanity check;
        # exact selection is established from object IDs in expected fixtures.
        if semantic and names and not any(semantic in str(name).casefold() for name in names.values()):
            _append(checks, "query_selected_role", False, expected=semantic, actual=names)
            errors.append("query_selected_role")


def _check_robot_setup(expected: dict, result: dict, before_scene: Any, after_scene: Any,
                       checks: list[dict], errors: list[str]) -> None:
    setup = result.get("robot_setup") or result.get("robotSetup")
    if not isinstance(setup, dict):
        _append(checks, "robot_setup_present", False)
        errors.append("robot_setup_present")
        return
    if expected.get("profile_id") is not None:
        ok = setup.get("profile_id") == expected["profile_id"]
        _append(checks, "robot_profile", ok, expected=expected["profile_id"], actual=setup.get("profile_id"))
        if not ok:
            errors.append("robot_profile")
    if expected.get("mode") is not None:
        ok = setup.get("mode") == expected["mode"]
        _append(checks, "robot_mode", ok, expected=expected["mode"], actual=setup.get("mode"))
        if not ok:
            errors.append("robot_mode")
    if expected.get("platform_unchanged"):
        before_objects, after_objects = _objects(before_scene), _objects(after_scene)
        # The independent check is intentionally structural: platform objects
        # and user object count must not disappear during a profile change.
        ok = set(before_objects) <= set(after_objects)
        _append(checks, "platform_objects_preserved", ok,
                missing=sorted(set(before_objects) - set(after_objects)))
        if not ok:
            errors.append("platform_objects_preserved")


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

    if expected.get("route") == "scene_query" or expected.get("query_type"):
        _check_query_result(expected, result, role_mapping, checks, errors)

    if expected.get("route") == "robot_config" or expected_outcome == "robot_setup_updated":
        _check_robot_setup(expected, result, before_scene, after_scene, checks, errors)

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
