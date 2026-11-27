from pathlib import Path
import pytest
from robot_agent_brain.planning.layout_planner import plan_arrangement
from robot_agent_brain.contracts.arrangement import ArrangementSpec
from test_layout_transaction import setup


def text_spec(count=12):
    _, spec, _ = setup()
    data = spec.model_dump()
    data["pattern"] = {"kind": "text", "text": "A"}
    data["items"]["requested_count"] = count
    return ArrangementSpec.model_validate(data)


def registered_fonts():
    pytest.importorskip("fontTools")
    path = Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")
    if not path.exists():
        pytest.skip("DejaVu acceptance font is not installed")
    return {"default": str(path)}


def test_font_outline_is_deterministic_bounded_and_fingerprinted():
    fonts = registered_fonts()
    spec = text_spec()
    plan = plan_arrangement(spec, font_registry=fonts)
    assert plan == plan_arrangement(spec, font_registry=fonts)
    assert len(plan.slots) == 12
    assert all(.09 <= slot.u <= .91 and .09 <= slot.v <= .91 for slot in plan.slots)
    assert plan.planner_revision.startswith("font-outline-v1:")
    assert plan.planner_source == "deterministic"


def test_model_font_is_registry_key_not_path():
    with pytest.raises(ValueError):
        text_spec().pattern.model_validate({"kind": "text", "text": "A", "font": "/etc/passwd"})
    with pytest.raises(ValueError, match="font_unregistered"):
        plan_arrangement(text_spec())


def test_missing_and_corrupt_registered_fonts_are_explicit_errors(tmp_path):
    pytest.importorskip("fontTools")
    missing = tmp_path / "missing.ttf"
    with pytest.raises(ValueError, match="scene_layout_font_unavailable"):
        plan_arrangement(text_spec(), font_registry={"default": str(missing)})
    invalid = tmp_path / "invalid.ttf"
    invalid.write_bytes(b"not a font")
    with pytest.raises(ValueError, match="scene_layout_font_invalid"):
        plan_arrangement(text_spec(), font_registry={"default": str(invalid)})


def test_font_fingerprint_and_sampling_use_same_snapshot(monkeypatch, tmp_path):
    import hashlib
    from robot_agent_brain.planning.text_layout import text_slots
    source = Path(registered_fonts()["default"])
    registered = tmp_path / "registered.ttf"
    original = source.read_bytes()
    registered.write_bytes(original)
    expected, _ = text_slots("A", 12, source)
    read_bytes = Path.read_bytes

    def replaced_after_read(path):
        data = read_bytes(path)
        if path == registered:
            path.write_bytes(b"replacement is not a font")
        return data

    monkeypatch.setattr(Path, "read_bytes", replaced_after_read)
    actual, fingerprint = text_slots("A", 12, registered)
    assert actual == expected
    assert fingerprint == hashlib.sha256(original).hexdigest()


def test_missing_glyph_and_empty_outline_are_not_invented():
    fonts = registered_fonts()
    spec = text_spec()
    for text, error in [("\U0010ffff", "glyph_missing"), (" ", "empty_outline")]:
        changed = spec.model_copy(update={"pattern": spec.pattern.model_copy(update={"text": text})})
        with pytest.raises(ValueError, match=error):
            plan_arrangement(changed, font_registry=fonts)


def test_text_plan_reaches_real_scene_resolver():
    from robot_agent_brain.pipeline import BrainPipeline
    from robot_agent_brain.contracts.turn import BrainTurn
    fonts = registered_fonts()
    scene, _, editor = setup()
    pipeline = BrainPipeline(None, editor.assets, scene_editor=editor, layout_fonts=fonts)
    turn = BrainTurn(status="accepted", turn_kind="scene_layout", instruction="字母A",
                     arrangement_spec=text_spec(3))
    result = pipeline.process_turn("text", turn, scene)
    assert len(result.scene_patch.operations) == 3
    assert result.layout_plan.planner_revision.startswith("font-outline-v1:")


@pytest.mark.parametrize("orientation", ["fixed", "follow_pattern"])
def test_text_world_mapping_preserves_font_proportions(orientation):
    from robot_agent_brain.scene.scene_manager import SceneManager
    from robot_agent_brain.scene.component_access import SceneIndex
    scene, _, editor = setup()
    spec = text_spec(3)
    data = spec.model_dump()
    data["orientation"] = {"mode": orientation}
    spec = ArrangementSpec.model_validate(data)
    plan = plan_arrangement(spec, font_registry=registered_fonts())
    before = scene.raw_document()
    result = editor.layout_result(spec, plan, scene)
    candidate = SceneManager(scene).apply_patch(result.patch)
    positions = [SceneIndex(candidate).transform(i).position for i in result.created_object_ids]
    # Same affine scale for both axes, not just a visually plausible outline.
    scales = []
    for axis, field in enumerate(("u", "v")):
        for i in range(1, len(positions)):
            delta = getattr(plan.slots[i], field) - getattr(plan.slots[0], field)
            if abs(delta) > 1e-9:
                scales.append((positions[i][axis] - positions[0][axis]) / delta)
    assert len(scales) >= 2
    assert min(scales) > 0
    assert max(scales) == pytest.approx(min(scales))
    assert scene.raw_document() == before
    assert len(result.created_object_ids) == 3
