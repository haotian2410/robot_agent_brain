import pytest
from test_dual_v4_pipeline import setup


def test_unique_active_driver_profile_resolves_without_task_text():
    current = setup()
    profile = current.robot_profiles.resolve_scene(current.scene)
    assert profile.setup.mode == "dual"
    assert profile.setup.profile_id == "fixture_only"


def test_multiple_matching_profiles_require_explicit_scene_selection():
    current = setup()
    alternate = current.robot_profiles.profiles["fixture_only"].model_copy(deep=True)
    alternate.setup.profile_id = "alternative"
    current.robot_profiles.profiles["alternative"] = alternate
    with pytest.raises(ValueError, match="robot_scene_profile_ambiguous"):
        current.robot_profiles.resolve_scene(current.scene)


def test_missing_active_driver_does_not_guess_dual_profile():
    current = setup()
    scene = current.scene
    scene.objects = [obj for obj in scene.objects if obj.object_id_in_scene != 3]
    assert current.robot_profiles.resolve_scene(scene) is None


def test_scene_setup_declaration_selects_profile_among_matching_candidates():
    from robot_agent_brain.contracts.scene import parse_scene_document
    current = setup()
    alternate = current.robot_profiles.profiles["fixture_only"].model_copy(deep=True)
    alternate.setup.profile_id = "alternative"
    current.robot_profiles.profiles["alternative"] = alternate
    raw = current.scene.raw_document()
    raw["robot_setup"] = alternate.setup.model_dump(mode="json")
    scene = parse_scene_document(raw).view
    resolved = current.robot_profiles.resolve_scene(scene)
    assert resolved.setup.profile_id == "alternative"


def test_scene_declaration_mode_conflict_is_not_overridden_by_profile():
    from robot_agent_brain.contracts.scene import parse_scene_document
    current = setup()
    raw = current.scene.raw_document()
    raw["robot_setup"] = {"mode": "single", "profile_id": "fixture_only",
                          "arms": {"single": current.robot_setup.arms["left"].model_dump(mode="json")}}
    scene = parse_scene_document(raw).view
    with pytest.raises(ValueError, match="robot_setup_profile_mode_mismatch"):
        current.robot_profiles.resolve_scene(scene)


def test_import_rejects_global_profile_conflicting_with_scene_declaration(tmp_path):
    from types import SimpleNamespace
    from robot_agent_brain.application import BrainApplication
    from robot_agent_brain.config import BrainConfig
    from robot_agent_brain.contracts.scene import parse_scene_document
    current = setup()
    raw = current.scene.raw_document()
    raw["robot_setup"] = {**current.robot_setup.model_dump(mode="json"), "profile_id": "scene-profile"}
    scene = parse_scene_document(raw).view
    app = BrainApplication(BrainConfig(provider="replay", output_dir=str(tmp_path),
        robot_profiles=current.robot_profiles, scene_robot_profile="fixture_only"), provider=object())
    app.robot_assembly = SimpleNamespace(ensure_scene_robot_config=lambda scene: (scene, None))
    with pytest.raises(ValueError, match="robot_profile_scene_mode_mismatch"):
        app._load_scene_object("conflict", scene)
    assert app.get_session("conflict").scene is None
