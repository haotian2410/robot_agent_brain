import pytest

from robot_agent_brain.config import BrainConfig
from robot_agent_brain.contracts.arrangement import ArrangementSpec
from robot_agent_brain.planning.layout_planner import plan_arrangement
from robot_agent_brain.scene.editor import SceneEditor
from robot_agent_brain.scene.scene_manager import SceneManager
from robot_agent_brain.scene.component_access import SceneIndex
from test_query_scene_continuity import supported_scene


def setup(spacing=.12):
    scene = supported_scene()
    scene = scene.model_copy(update={"objects": scene.objects[:1]})
    spec = ArrangementSpec(arrangement_id="arr-grid", pattern={"kind": "grid", "rows": 2, "cols": 3},
        items={"assets": [{"alias": "apple"}], "requested_count": 6},
        region={"surface_ref": "table"}, spacing={"mode": "center", "value_m": spacing})
    return scene, spec, SceneEditor(BrainConfig().load_assets())


def test_grid_applies_exact_spacing_and_one_version():
    scene, spec, editor = setup()
    before = scene.model_dump()
    result = editor.layout_result(spec, plan_arrangement(spec), scene)
    assert scene.model_dump() == before
    manager = SceneManager(scene)
    manager.apply_patch(result.patch)
    positions = [SceneIndex(manager.scene).transform(i).position for i in result.created_object_ids]
    assert sorted({round(p[0], 6) for p in positions}) == [-.12, 0, .12]
    assert sorted({round(p[1], 6) for p in positions}) == [-.06, .06]
    assert len(positions) == 6
    assert manager.scene.scene_version == scene.scene_version + 1


def test_count_only_grid_commits_exact_members_without_filling_extra_cells():
    scene, spec, editor = setup(.15)
    data = spec.model_dump()
    data["pattern"] = {"kind": "grid"}
    data["items"]["requested_count"] = 5
    spec = ArrangementSpec.model_validate(data)
    result = editor.layout_result(spec, plan_arrangement(spec), scene)
    candidate = SceneManager(scene).apply_patch(result.patch)
    positions = [SceneIndex(candidate).transform(i).position for i in result.created_object_ids]
    assert len(positions) == 5
    assert len({round(p[0], 6) for p in positions}) == 3
    assert len({round(p[1], 6) for p in positions}) == 2
    assert len(candidate.objects) == len(scene.objects) + 5
    assert candidate.scene_version == scene.scene_version + 1


@pytest.mark.parametrize("kind", ["grid", "checker"])
def test_explicit_grid_at_least_uses_all_declared_cells_and_records_adjustment(kind):
    scene, base, editor = setup(.15)
    data = base.model_dump()
    data["pattern"]["kind"] = kind
    data["items"].update(requested_count=5, count_mode="at_least")
    spec = ArrangementSpec.model_validate(data)
    plan = plan_arrangement(spec)
    assert len(plan.slots) == 6
    result = editor.layout_result(spec, plan, scene)
    candidate = SceneManager(scene).apply_patch(result.patch)
    assert len(result.created_object_ids) == 6
    assert len(candidate.objects) == len(scene.objects) + 6
    assert candidate.scene_version == scene.scene_version + 1
    assert "layout_count_requested=5" in result.assumptions
    assert "layout_count_resolved=6" in result.assumptions
    from robot_agent_brain.scene.layout_resolver import LayoutResolver
    resolution = LayoutResolver().resolve(spec, plan, scene_id=scene.scene_id,
        scene_version=candidate.scene_version, instance_ids=result.created_object_ids)
    assert len(resolution.slot_assets) == len(resolution.slot_bindings) == 6


def test_at_least_grid_cannot_drop_lower_bound_or_invent_mixed_asset_allocation():
    _, base, _ = setup()
    data = base.model_dump()
    data["items"].update(requested_count=7, count_mode="at_least")
    with pytest.raises(ValueError, match="scene_layout_count_conflict"):
        plan_arrangement(ArrangementSpec.model_validate(data))
    data["items"].update(mode="counts", requested_count=5,
                         assets=[{"alias": "apple", "count": 3}, {"alias": "banana", "count": 2}])
    with pytest.raises(ValueError, match="scene_layout_count_conflict"):
        plan_arrangement(ArrangementSpec.model_validate(data))


def test_at_least_grid_session_reserves_and_remembers_actual_members():
    from robot_agent_brain.adapters.local_scene_platform import LocalScenePlatform
    from robot_agent_brain.contracts.turn import BrainTurn
    from robot_agent_brain.pipeline import BrainPipeline
    from robot_agent_brain.session.brain_session import BrainSession
    scene, base, editor = setup(.15)
    data = base.model_dump()
    data["items"].update(requested_count=5, count_mode="at_least")
    turn = BrainTurn(status="accepted", turn_kind="scene_layout", instruction="至少5个苹果，两行三列",
                     arrangement_spec=ArrangementSpec.model_validate(data))
    session = BrainSession(scene, BrainPipeline(None, editor.assets, scene_editor=editor), LocalScenePlatform())
    result = session.process_turn("minimum-grid", turn)
    record = session.arrangement_index.get(base.arrangement_id)
    assert len(record.slot_bindings) == len(result.layout_resolution.instance_ids) == 6
    before = session.scene.raw_document()
    assert session.process_turn("minimum-grid", turn) == result
    assert session.scene.raw_document() == before


def test_at_least_mixed_assets_commit_declared_counts_and_report_source():
    scene, base, editor = setup(.25)
    data = base.model_dump()
    data["pattern"] = {"kind": "grid"}
    data["items"] = {"mode": "counts", "requested_count": 5, "count_mode": "at_least",
                     "assets": [{"alias": "apple", "count": 3}, {"alias": "banana", "count": 3}]}
    spec = ArrangementSpec.model_validate(data)
    result = editor.layout_result(spec, plan_arrangement(spec), scene)
    candidate = SceneManager(scene).apply_patch(result.patch)
    index = SceneIndex(candidate)
    names = [index.semantic(oid).semantic_name for oid in result.created_object_ids]
    assert names.count("apple") == names.count("banana") == 3
    assert "layout_count_adjustment=explicit_assets_at_least" in result.assumptions
    assert candidate.scene_version == scene.scene_version + 1


@pytest.mark.parametrize("count", [1, 2, 5, 8])
def test_circle_auto_radius_is_derived_and_repeatable(count):
    import math
    scene, spec, editor = setup()
    data = spec.model_dump()
    data.update(pattern={"kind": "circle"}, spacing={"mode": "auto", "auto": True})
    data["items"]["requested_count"] = count
    spec = ArrangementSpec.model_validate(data)
    before = scene.raw_document()
    plan = plan_arrangement(spec)
    result = editor.layout_result(spec, plan, scene)
    repeated = editor.layout_result(spec, plan, scene)
    assert result.patch == repeated.patch
    assert result.assumptions == repeated.assumptions
    assert scene.raw_document() == before
    radius = float(next(a.split("=", 1)[1] for a in result.assumptions if a.startswith("layout_radius_m=")))
    assert radius > 0
    candidate = SceneManager(scene).apply_patch(result.patch)
    assert len(result.created_object_ids) == count
    for oid in result.created_object_ids:
        position = SceneIndex(candidate).transform(oid).position
        assert math.hypot(position[0], position[1]) == pytest.approx(radius)
    assert candidate.scene_version == scene.scene_version + 1
    assert "layout_radius_search=authorized_auto" in result.assumptions


def test_circle_missing_radius_without_auto_is_rejected():
    _, spec, _ = setup()
    data = spec.model_dump()
    data["pattern"] = {"kind": "circle"}
    with pytest.raises(ValueError, match="circle_radius_missing"):
        ArrangementSpec.model_validate(data)


def test_circle_auto_radius_exact_count_does_not_shrink_to_fit():
    scene, spec, editor = setup()
    data = spec.model_dump()
    data.update(pattern={"kind": "circle"}, spacing={"mode": "auto", "auto": True})
    data["items"]["requested_count"] = 100
    spec = ArrangementSpec.model_validate(data)
    before = scene.raw_document()
    with pytest.raises(ValueError, match="capacity_exceeded"):
        editor.layout_result(spec, plan_arrangement(spec), scene)
    assert scene.raw_document() == before


def test_resolver_owns_candidate_without_mutating_input():
    from robot_agent_brain.scene.layout_resolver import LayoutResolver
    scene, spec, editor = setup()
    before = scene.model_dump()
    plan = plan_arrangement(spec)
    candidate = LayoutResolver(editor=editor).resolve_candidate(spec, plan, scene)
    assert scene.model_dump() == before
    assert candidate.patch == editor.layout_result(spec, plan, scene).patch
    with pytest.raises(ValueError, match="resolver_not_configured"):
        LayoutResolver().resolve_candidate(spec, plan, scene)


@pytest.mark.parametrize("value", [float("inf"), float("nan"), True])
def test_layout_projection_refuses_invalid_bounds(value):
    from robot_agent_brain.scene.layout_resolver import LayoutResolver
    _, spec, _ = setup()
    with pytest.raises(ValueError, match="surface_bounds_invalid"):
        LayoutResolver.project_world_slots(plan_arrangement(spec), ((0, 0), (value, 1)))


def test_capacity_failure_leaves_input_unchanged():
    scene, spec, editor = setup(spacing=2)
    before = scene.model_dump()
    with pytest.raises(ValueError, match="scene_layout_capacity_exceeded"):
        editor.layout_result(spec, plan_arrangement(spec), scene)
    assert scene.model_dump() == before


def test_authorized_auto_spacing_search_avoids_center_obstacle_without_publishing_trials():
    scene, spec, editor = setup()
    data = spec.model_dump()
    data.update(arrangement_id="arr-obstacle", pattern={"kind": "line"})
    data["items"]["requested_count"] = 1
    obstacle = ArrangementSpec.model_validate(data)
    manager = SceneManager(scene)
    manager.apply_patch(editor.layout_result(obstacle, plan_arrangement(obstacle), scene).patch)
    scene = manager.scene
    before = scene.model_dump()
    data.update(arrangement_id="arr-auto")
    data["items"]["requested_count"] = 2
    data["spacing"] = {"mode": "auto", "auto": True}
    adaptive = ArrangementSpec.model_validate(data)
    result = editor.layout_result(adaptive, plan_arrangement(adaptive), scene)
    repeat = editor.layout_result(adaptive, plan_arrangement(adaptive), scene)
    assert result.patch == repeat.patch
    assert result.assumptions == repeat.assumptions
    assert scene.model_dump() == before
    attempts = next(int(a.split("=")[1]) for a in result.assumptions
                    if a.startswith("layout_spacing_search_attempts="))
    assert attempts > 1
    assert result.adjusted_layout_spacing_m is not None
    manager.apply_patch(result.patch)
    assert len(result.created_object_ids) == 2
    assert len(manager.scene.objects) == 4
    assert manager.scene.scene_version == scene.scene_version + 1


def test_session_records_resolved_auto_spacing_not_unset_request_value(tmp_path):
    session, turn = original_layout_session(tmp_path)
    data = turn.arrangement_spec.model_dump()
    data.update(basis="current", pattern={"kind": "line"})
    data["items"]["requested_count"] = 2
    data["spacing"] = {"mode": "auto", "auto": True}
    result = session.process_turn("auto-spacing-metadata", turn.model_copy(update={
        "arrangement_spec": ArrangementSpec.model_validate(data)}))
    resolution = result.layout_resolution
    positions = list(resolution.world_positions.values())
    import math
    assert resolution.adjusted_spacing_m == pytest.approx(math.dist(*positions))
    assert resolution.adjusted_spacing_m > 0
    assert resolution.assumptions == result.assumptions


def test_fixed_spacing_collision_is_not_silently_expanded():
    scene, spec, editor = setup()
    data = spec.model_dump()
    data.update(pattern={"kind": "line"})
    data["items"]["requested_count"] = 1
    obstacle = ArrangementSpec.model_validate(data)
    manager = SceneManager(scene)
    manager.apply_patch(editor.layout_result(obstacle, plan_arrangement(obstacle), scene).patch)
    before = manager.scene.model_dump()
    data["items"]["requested_count"] = 2
    data["spacing"] = {"mode": "center", "value_m": .08}
    fixed = ArrangementSpec.model_validate(data)
    with pytest.raises(ValueError, match="scene_layout_collision"):
        editor.layout_result(fixed, plan_arrangement(fixed), manager.scene)
    assert manager.scene.model_dump() == before


def test_auto_spacing_does_not_reduce_count_or_escape_declared_region():
    scene, spec, editor = setup()
    data = spec.model_dump()
    data["spacing"] = {"mode": "auto", "auto": True}
    data["region"].update(width_m=.09, depth_m=.09)
    constrained = ArrangementSpec.model_validate(data)
    before = scene.model_dump()
    with pytest.raises(ValueError, match="scene_layout_capacity_exceeded"):
        editor.layout_result(constrained, plan_arrangement(constrained), scene)
    assert scene.model_dump() == before
    assert constrained.items.requested_count == 6


def original_layout_session(tmp_path, spacing=.12):
    from robot_agent_brain.pipeline import BrainPipeline
    from robot_agent_brain.contracts.turn import BrainTurn
    from robot_agent_brain.session.brain_session import BrainSession
    from robot_agent_brain.session.original_scene_store import OriginalSceneStore
    from robot_agent_brain.adapters.local_scene_platform import LocalScenePlatform
    scene, spec, editor = setup(spacing)
    session = BrainSession(scene, BrainPipeline(None, editor.assets, scene_editor=editor), LocalScenePlatform())
    session.original_store = OriginalSceneStore(tmp_path)
    session.original_scene_manifest = session.original_store.capture_once(
        scene, platform_object_ids=set(), request_id="original", source="fixture")
    session.scene_reset_allowed = True
    turn = BrainTurn(status="accepted", turn_kind="scene_layout", instruction="原始场景两行三列苹果",
                     arrangement_spec=spec.model_copy(update={"basis": "original"}))
    return session, turn


def test_original_layout_repeated_derivation_remaps_bindings_and_preserves_snapshot(tmp_path):
    session, turn = original_layout_session(tmp_path)
    original = (tmp_path / "original_scene.json").read_bytes()
    first = session.process_turn("original-layout-1", turn)
    second = session.process_turn("original-layout-2", turn)
    assert first.scene_replacement.scene_id != second.scene_replacement.scene_id
    assert first.scene_patch is second.scene_patch is None
    assert len(session.scene.objects) == 7
    assert not set(first.layout_resolution.instance_ids) & set(second.layout_resolution.instance_ids)
    assert set(second.layout_resolution.instance_ids) <= {o.object_id_in_scene for o in session.scene.objects}
    record = session.arrangement_index.get(turn.arrangement_spec.arrangement_id)
    assert record.slot_bindings == second.layout_resolution.slot_bindings
    assert record.scene_id == session.scene.scene_id
    assert record.scene_version == session.scene.scene_version
    assert (tmp_path / "original_scene.json").read_bytes() == original
    # Also validate the result, not only model_copy's unchecked update.
    type(second).model_validate(second.model_dump())


def test_original_layout_failure_does_not_publish_or_record(tmp_path):
    session, turn = original_layout_session(tmp_path, spacing=2)
    before = session.scene.model_dump()
    next_id = session.next_scene_object_id
    with pytest.raises(ValueError, match="scene_layout_capacity_exceeded"):
        session.process_turn("bad-layout", turn)
    assert session.scene.model_dump() == before
    assert session.next_scene_object_id == next_id + turn.arrangement_spec.items.requested_count
    assert session.layout_id_reservations["bad-layout"] == [next_id, session.next_scene_object_id]
    assert session.arrangement_index.snapshot() == []


def test_append_keeps_existing_ids_and_records_all_slots(tmp_path):
    session, original_turn = original_layout_session(tmp_path)
    turn = original_turn.model_copy(update={"arrangement_spec":
        original_turn.arrangement_spec.model_copy(update={"basis": "current"})})
    first = session.process_turn("create", turn)
    previous = {o.object_id_in_scene: o.model_dump() for o in session.scene.objects}
    data = turn.arrangement_spec.model_dump()
    data.update(operation="append", pattern={"kind": "grid", "rows": 1, "cols": 1})
    data["items"]["requested_count"] = 1
    data["region"]["side"] = "right_half"
    append = turn.model_copy(update={"arrangement_spec": ArrangementSpec.model_validate(data)})
    second = session.process_turn("append", append)
    assert len(session.scene.objects) == 8
    assert len(second.scene_patch.operations) == 1
    assert len(second.layout_resolution.slot_bindings) == 7
    assert set(first.layout_resolution.slot_bindings) <= set(second.layout_resolution.slot_bindings)
    for obj in session.scene.objects:
        if obj.object_id_in_scene in previous:
            assert obj.model_dump() == previous[obj.object_id_in_scene]
    assert session.arrangement_index.get(data["arrangement_id"]).slot_bindings == second.layout_resolution.slot_bindings
    # A colliding append must not alter either the scene or durable membership.
    before = session.scene.model_dump()
    records = session.arrangement_index.snapshot()
    with pytest.raises(ValueError, match="scene_layout_collision"):
        session.process_turn("append-collision", append)
    assert session.scene.model_dump() == before
    assert session.arrangement_index.snapshot() == records


def test_append_requires_current_branch_membership_and_create_cannot_overwrite(tmp_path):
    session, original_turn = original_layout_session(tmp_path)
    spec = original_turn.arrangement_spec.model_copy(update={"basis": "current"})
    turn = original_turn.model_copy(update={"arrangement_spec": spec})
    append = turn.model_copy(update={"arrangement_spec": spec.model_copy(update={"operation": "append"})})
    with pytest.raises(ValueError, match="scene_layout_arrangement_missing"):
        session.process_turn("append-missing", append)
    session.process_turn("create", turn)
    before = session.scene.model_dump()
    with pytest.raises(ValueError, match="scene_layout_arrangement_exists"):
        session.process_turn("duplicate-create", turn)
    assert session.scene.model_dump() == before


def test_append_index_survives_serialization_but_rejects_deleted_members_and_other_branch(tmp_path):
    from robot_agent_brain.scene.arrangement_index import ArrangementIndex, ArrangementRecord
    session, original_turn = original_layout_session(tmp_path)
    spec = original_turn.arrangement_spec.model_copy(update={"basis": "current"})
    session.process_turn("create", original_turn.model_copy(update={"arrangement_spec": spec}))
    restored = ArrangementIndex()
    for data in session.arrangement_index.snapshot():
        restored.put(ArrangementRecord.model_validate(data))
    append = spec.model_copy(update={"operation": "append"})
    record = restored.validate_operation(append, session.scene)
    removed = next(iter(record.slot_bindings.values()))
    missing = session.scene.model_copy(update={"objects": [o for o in session.scene.objects
                                                           if o.object_id_in_scene != removed]})
    with pytest.raises(ValueError, match="scene_layout_arrangement_members_missing"):
        restored.validate_operation(append, missing)
    other_branch = session.scene.model_copy(update={"scene_id": session.scene.scene_id + 1})
    with pytest.raises(ValueError, match="scene_layout_arrangement_missing"):
        restored.validate_operation(append, other_branch)


def test_rearrange_keeps_identity_components_and_allocator(tmp_path):
    from robot_agent_brain.contracts.scene import ScenePatch, ScenePatchOperation, SceneComponent
    session, original_turn = original_layout_session(tmp_path)
    spec = original_turn.arrangement_spec.model_copy(update={"basis": "current"})
    turn = original_turn.model_copy(update={"arrangement_spec": spec})
    result = session.process_turn("create", turn)
    oid = result.layout_resolution.instance_ids[0]
    transform = SceneIndex(session.scene).component(oid, "Transform").model_copy(deep=True)
    transform.properties["scale"] = [1.1, 1.1, 1.1]
    session.apply_scene_patch(ScenePatch(scene_id=session.scene.scene_id, base_scene_version=session.scene.scene_version,
        operations=[ScenePatchOperation(action="upsert_component", object_id_in_scene=oid, component=transform),
                    ScenePatchOperation(action="upsert_component", object_id_in_scene=oid,
                        component=SceneComponent(component_type="MeshRenderer", properties={"forceOverrideColor": "#0000FF"}))]))
    before = session.scene.model_copy(deep=True)
    next_id = session.next_scene_object_id
    data = spec.model_dump()
    data.update(operation="rearrange", pattern={"kind": "grid", "rows": 3, "cols": 2})
    changed = session.process_turn("rearrange", turn.model_copy(update={"arrangement_spec": ArrangementSpec.model_validate(data)}))
    assert changed.layout_resolution.slot_bindings == result.layout_resolution.slot_bindings
    assert session.next_scene_object_id == next_id
    assert session.scene.scene_version == before.scene_version + 1
    assert all(op.action == "upsert_component" for op in changed.scene_patch.operations)
    for old, new in zip(before.objects, session.scene.objects):
        assert old.object_id_in_scene == new.object_id_in_scene
        assert old.object_name_in_scene == new.object_name_in_scene
        assert [c for c in old.components if c.component_type not in {"Transform", "Semantic"}] == [
            c for c in new.components if c.component_type not in {"Transform", "Semantic"}]
    assert SceneIndex(session.scene).transform(oid).scale == (1.1, 1.1, 1.1)
    assert SceneIndex(session.scene).transform(oid).position != SceneIndex(before).transform(oid).position


def test_rearrange_capacity_failure_preserves_scene_and_membership(tmp_path):
    session, original_turn = original_layout_session(tmp_path)
    spec = original_turn.arrangement_spec.model_copy(update={"basis": "current"})
    turn = original_turn.model_copy(update={"arrangement_spec": spec})
    session.process_turn("create", turn)
    before, records = session.scene.model_dump(), session.arrangement_index.snapshot()
    data = spec.model_dump()
    data.update(operation="rearrange")
    data["spacing"]["value_m"] = 2
    with pytest.raises(ValueError, match="scene_layout_capacity_exceeded"):
        session.process_turn("bad-rearrange", turn.model_copy(update={"arrangement_spec": ArrangementSpec.model_validate(data)}))
    assert session.scene.model_dump() == before
    assert session.arrangement_index.snapshot() == records


def test_rearrange_cannot_silently_replace_assets(tmp_path):
    session, original_turn = original_layout_session(tmp_path)
    spec = original_turn.arrangement_spec.model_copy(update={"basis": "current"})
    turn = original_turn.model_copy(update={"arrangement_spec": spec})
    session.process_turn("create", turn)
    before = session.scene.model_dump()
    data = spec.model_dump()
    data.update(operation="rearrange")
    data["items"]["assets"][0]["alias"] = "banana"
    with pytest.raises(ValueError, match="scene_layout_rearrange_asset_mismatch"):
        session.process_turn("wrong-assets", turn.model_copy(update={"arrangement_spec": ArrangementSpec.model_validate(data)}))
    assert session.scene.model_dump() == before


def test_layout_replace_allocates_new_ids_and_commits_once(tmp_path):
    session, original_turn = original_layout_session(tmp_path)
    data = original_turn.arrangement_spec.model_dump()
    data.update(basis="current", pattern={"kind": "grid", "rows": 1, "cols": 2})
    data["items"]["requested_count"] = 2
    data["spacing"]["value_m"] = .25
    turn = original_turn.model_copy(update={"arrangement_spec": ArrangementSpec.model_validate(data)})
    first = session.process_turn("create", turn)
    before_version = session.scene.scene_version
    data.update(operation="replace")
    data["items"]["assets"][0]["alias"] = "banana"
    result = session.process_turn("replace", turn.model_copy(update={"arrangement_spec": ArrangementSpec.model_validate(data)}))
    assert session.scene.scene_version == before_version + 1
    assert set(result.deleted_object_ids) == set(first.layout_resolution.instance_ids)
    assert not set(result.layout_resolution.instance_ids) & set(result.deleted_object_ids)
    assert set(result.layout_resolution.slot_bindings) == set(first.layout_resolution.slot_bindings)
    assert len(session.scene.objects) == 3
    for oid in result.layout_resolution.instance_ids:
        assert SceneIndex(session.scene).semantic(oid).semantic_name == "banana"
        assert SceneIndex(session.scene).semantic(oid).support == 0
    assert session.arrangement_index.get(data["arrangement_id"]).slot_bindings == result.layout_resolution.slot_bindings


def test_layout_replace_failure_preserves_objects_but_retires_reserved_ids(tmp_path):
    session, original_turn = original_layout_session(tmp_path)
    data = original_turn.arrangement_spec.model_dump()
    data.update(basis="current")
    turn = original_turn.model_copy(update={"arrangement_spec": ArrangementSpec.model_validate(data)})
    session.process_turn("create", turn)
    before, records, next_id = session.scene.model_dump(), session.arrangement_index.snapshot(), session.next_scene_object_id
    data.update(operation="replace")
    data["items"]["assets"][0]["alias"] = "banana"
    data["spacing"]["value_m"] = 2
    with pytest.raises(ValueError, match="scene_layout_capacity_exceeded"):
        session.process_turn("bad-replace", turn.model_copy(update={"arrangement_spec": ArrangementSpec.model_validate(data)}))
    assert session.scene.model_dump() == before
    assert session.arrangement_index.snapshot() == records
    assert session.next_scene_object_id == next_id + data["items"]["requested_count"]
    assert session.layout_id_reservations["bad-replace"] == [next_id, session.next_scene_object_id]


@pytest.mark.parametrize("basis", ["current", "original"])
def test_layout_request_replay_is_side_effect_free(tmp_path, basis):
    session, original_turn = original_layout_session(tmp_path)
    turn = original_turn.model_copy(update={"arrangement_spec":
        original_turn.arrangement_spec.model_copy(update={"basis": basis})})
    first = session.process_turn("same-request", turn)
    before = session.scene.model_dump()
    allocator, focus = session.next_scene_object_id, session.dialogue.model_dump()
    repeated = session.process_turn("same-request", turn)
    assert repeated.model_dump() == first.model_dump()
    assert session.scene.model_dump() == before
    assert session.next_scene_object_id == allocator
    assert session.dialogue.model_dump() == focus
    with pytest.raises(ValueError, match="scene_layout_request_conflict"):
        session.process_turn("same-request", turn.model_copy(update={"instruction": "different request"}))
    assert session.scene.model_dump() == before


def test_layout_request_receipt_survives_session_store_and_rejects_stale_replay(tmp_path):
    from robot_agent_brain.session.store import SessionStore
    from robot_agent_brain.session.brain_session import BrainSession
    from robot_agent_brain.adapters.local_scene_platform import LocalScenePlatform
    session, original_turn = original_layout_session(tmp_path / "original")
    # This test checkpoints a normal current-basis session without an external
    # original file dependency; original receipts are covered above.
    session.original_scene_manifest = None
    turn = original_turn.model_copy(update={"arrangement_spec":
        original_turn.arrangement_spec.model_copy(update={"basis": "current"})})
    result = session.process_turn("persisted-request", turn)
    store = SessionStore(tmp_path / "sessions")
    with store.lock("layout-replay"):
        store.save("layout-replay", session, revision=1)
        state = store.load("layout-replay")
    restored = BrainSession(None, session.pipeline, LocalScenePlatform())
    store.restore(state, restored)
    assert restored.process_turn("persisted-request", turn).model_dump() == result.model_dump()
    data = turn.arrangement_spec.model_dump()
    data.update(operation="rearrange", pattern={"kind": "grid", "rows": 3, "cols": 2})
    restored.process_turn("later-request", turn.model_copy(update={"arrangement_spec": ArrangementSpec.model_validate(data)}))
    before = restored.scene.model_dump()
    with pytest.raises(ValueError, match="scene_layout_request_stale"):
        restored.process_turn("persisted-request", turn)
    assert restored.scene.model_dump() == before


@pytest.mark.parametrize("kind,pattern,radius", [
    ("circle", {"radius_m": .22}, .22),
    ("arc", {"radius_m": .22, "angle_span_deg": 180}, .22),
    ("ring", {"inner_radius_m": .18, "outer_radius_m": .26}, .22),
])
def test_round_patterns_preserve_physical_radius(kind, pattern, radius):
    import math
    scene, original, editor = setup()
    data = original.model_dump()
    data["pattern"] = {"kind": kind, **pattern}
    data["items"]["requested_count"] = 4
    spec = ArrangementSpec.model_validate(data)
    result = editor.layout_result(spec, plan_arrangement(spec), scene)
    assert result.assumptions == [f"layout_radius_m={radius}"]
    manager = SceneManager(scene)
    manager.apply_patch(result.patch)
    for oid in result.created_object_ids:
        x, y, z = SceneIndex(manager.scene).transform(oid).position
        assert math.hypot(x, y) == pytest.approx(radius)
        assert z > 0


def test_pipeline_layout_uses_exact_transaction_without_commands():
    from robot_agent_brain.pipeline import BrainPipeline
    from robot_agent_brain.contracts.turn import BrainTurn
    scene, spec, editor = setup()
    pipeline = BrainPipeline(None, editor.assets, scene_editor=editor)
    turn = BrainTurn(status="accepted", turn_kind="scene_layout", instruction="两行三列苹果",
                     arrangement_spec=spec)
    result = pipeline.process_turn("layout-test", turn, scene)
    assert result.commands is None
    assert len(result.scene_patch.operations) == 6
    assert len(result.layout_resolution.slot_bindings) == 6
    manager = SceneManager(scene)
    manager.apply_patch(result.scene_patch)
    for slot, oid in result.layout_resolution.slot_bindings.items():
        actual = SceneIndex(manager.scene).transform(oid).position[:2]
        assert result.layout_resolution.world_positions[slot] == actual


def test_circle_uses_anchor_center_not_table_center():
    import math
    scene = supported_scene()
    # Keep the off-centre apple as an explicitly named anchor.
    scene = scene.model_copy(update={"objects": scene.objects[:2]})
    _, base, editor = setup()
    data = base.model_dump()
    data["pattern"] = {"kind": "circle", "radius_m": .13}
    data["items"]["requested_count"] = 4
    data["region"].update(kind="around", anchor_ref="apple")
    spec = ArrangementSpec.model_validate(data)
    result = editor.layout_result(spec, plan_arrangement(spec), scene)
    manager = SceneManager(scene)
    manager.apply_patch(result.patch)
    for oid in result.created_object_ids:
        x, y, _ = SceneIndex(manager.scene).transform(oid).position
        assert math.hypot(x + .25, y) == pytest.approx(.13)


@pytest.mark.parametrize("side,axis,positive", [
    ("left_half", 0, False), ("right_half", 0, True),
    ("front_half", 1, True), ("back_half", 1, False),
])
def test_relative_region_respects_anchor_footprint_and_table(side, axis, positive):
    from robot_agent_brain.scene.geometry import world_bounds
    from robot_agent_brain.scene.scene_graph import world_transform
    scene = supported_scene()
    scene = scene.model_copy(update={"objects": scene.objects[:2]})
    _, base, editor = setup()
    data = base.model_dump()
    data["pattern"] = {"kind": "line", "axis": "y" if axis == 0 else "x"}
    data["items"]["requested_count"] = 2
    data["region"].update(kind="relative", anchor_ref="apple", side=side)
    arrangement = ArrangementSpec.model_validate(data)
    before = scene.model_dump()
    result = editor.layout_result(arrangement, plan_arrangement(arrangement), scene)
    manager = SceneManager(scene)
    manager.apply_patch(result.patch)
    facts = editor._facts(None)
    anchor = scene.objects[1]
    low, high = world_bounds(facts.asset(anchor, scene),
                            world_transform(scene, anchor.object_id_in_scene))
    for oid in result.created_object_ids:
        obj = SceneIndex(manager.scene).object(oid)
        a, b = world_bounds(facts.asset(obj, manager.scene), world_transform(manager.scene, oid))
        if positive:
            assert a[axis] >= high[axis] + arrangement.constraints.min_clearance_m
        else:
            assert b[axis] <= low[axis] - arrangement.constraints.min_clearance_m
        assert facts.footprint_contains(obj, scene.objects[0], manager.scene)
    assert scene.model_dump() == before
    assert manager.scene.scene_version == scene.scene_version + 1


def test_relative_region_insufficient_side_capacity_is_atomic():
    scene = supported_scene()
    scene = scene.model_copy(update={"objects": scene.objects[:2]})
    _, base, editor = setup()
    data = base.model_dump()
    data["region"].update(kind="relative", anchor_ref="apple", side="left_half", width_m=1.)
    arrangement = ArrangementSpec.model_validate(data)
    before = scene.model_dump()
    with pytest.raises(ValueError, match="scene_layout_capacity_exceeded"):
        editor.layout_result(arrangement, plan_arrangement(arrangement), scene)
    assert scene.model_dump() == before


def test_fixed_yaw_is_written_and_support_is_explicit():
    import math
    scene, base, editor = setup(spacing=.16)
    data = base.model_dump()
    data["orientation"] = {"mode": "fixed", "yaw_deg": 90}
    spec = ArrangementSpec.model_validate(data)
    result = editor.layout_result(spec, plan_arrangement(spec), scene)
    manager = SceneManager(scene)
    manager.apply_patch(result.patch)
    index = SceneIndex(manager.scene)
    for oid in result.created_object_ids:
        assert index.transform(oid).quaternion_xyzw == pytest.approx((0, 0, math.sqrt(.5), math.sqrt(.5)))
        assert index.semantic(oid).support == 0


def test_custom_normalized_path_is_mapped_to_surface():
    scene, base, editor = setup()
    data = base.model_dump()
    data["pattern"] = {"kind": "custom", "description": "A", "path": [[.2, .2], [.8, .8]]}
    data["items"]["requested_count"] = 2
    spec = ArrangementSpec.model_validate(data)
    result = editor.layout_result(spec, plan_arrangement(spec), scene)
    manager = SceneManager(scene)
    manager.apply_patch(result.patch)
    positions = [SceneIndex(manager.scene).transform(i).position for i in result.created_object_ids]
    assert positions[0][0] < positions[1][0]
    assert positions[0][1] < positions[1][1]


def test_sampled_custom_path_creates_exact_count_in_one_patch():
    scene, base, editor = setup()
    data = base.model_dump()
    data["pattern"] = {"kind": "custom", "path": [[.2, .5], [.8, .5]]}
    data["items"]["requested_count"] = 5
    spec = ArrangementSpec.model_validate(data)
    result = editor.layout_result(spec, plan_arrangement(spec), scene)
    manager = SceneManager(scene)
    manager.apply_patch(result.patch)
    positions = [SceneIndex(manager.scene).transform(i).position for i in result.created_object_ids]
    assert len(positions) == 5
    gaps = [b[0] - a[0] for a, b in zip(positions, positions[1:])]
    assert gaps == pytest.approx([gaps[0]] * 4)
    assert manager.scene.scene_version == scene.scene_version + 1


@pytest.mark.parametrize("orientation", ["fixed", "follow_pattern"])
def test_full_normalized_path_endpoints_include_footprint_and_margin(orientation):
    from robot_agent_brain.scene.geometry import world_bounds
    from robot_agent_brain.scene.scene_graph import world_transform
    scene, base, editor = setup()
    data = base.model_dump()
    data["pattern"] = {"kind": "custom", "path": [[0, 0], [1, 1]]}
    data["items"]["requested_count"] = 3
    data["orientation"] = {"mode": orientation, "yaw_deg": 0}
    spec = ArrangementSpec.model_validate(data)
    before = scene.model_dump()
    result = editor.layout_result(spec, plan_arrangement(spec), scene)
    assert result.assumptions[0].startswith("layout_origin_bounds_xy_m=")
    manager = SceneManager(scene)
    manager.apply_patch(result.patch)
    facts = editor._facts(None)
    support = scene.objects[0]
    low, high = world_bounds(facts.asset(support, scene), world_transform(scene, support.object_id_in_scene))
    positions = []
    for oid in result.created_object_ids:
        obj = SceneIndex(manager.scene).object(oid)
        pose = world_transform(manager.scene, oid)
        a, b = world_bounds(facts.asset(obj, manager.scene), pose)
        assert all(a[i] >= low[i] + spec.region.margin_m for i in (0, 1))
        assert all(b[i] <= high[i] - spec.region.margin_m for i in (0, 1))
        positions.append(pose.position)
    assert positions[1][:2] == pytest.approx(tuple((positions[0][i] + positions[2][i]) / 2 for i in (0, 1)))
    assert scene.model_dump() == before
    assert manager.scene.scene_version == scene.scene_version + 1


def test_circle_follow_pattern_writes_tangent_yaws():
    import math
    scene, base, editor = setup()
    data = base.model_dump()
    data["pattern"] = {"kind": "circle", "radius_m": .22}
    data["items"]["requested_count"] = 4
    data["orientation"] = {"mode": "follow_pattern"}
    spec = ArrangementSpec.model_validate(data)
    plan = plan_arrangement(spec)
    result = editor.layout_result(spec, plan, scene)
    manager = SceneManager(scene)
    manager.apply_patch(result.patch)
    for oid, yaw in zip(result.created_object_ids, plan.orientation_hints):
        q = SceneIndex(manager.scene).transform(oid).quaternion_xyzw
        assert q == pytest.approx((0, 0, math.sin(math.radians(yaw)/2), math.cos(math.radians(yaw)/2)))
