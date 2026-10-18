from robot_agent_brain.application import BrainApplication
from robot_agent_brain.config import BrainConfig
from robot_agent_brain.contracts.turn import BrainTurn
from test_application_artifacts import Provider
from test_robot_config_turns import session
from test_dual_session_pipeline import task


def test_same_profile_reports_unchanged_and_preserves_session_state(tmp_path):
    current = session()
    current.process_turn("old", task())
    current.dialogue.last_entity_id = 7
    current.dialogue.last_entity_ids = [7]
    before = (current.scene, current.robot_setup_revision, dict(current.exported_commands), current.dialogue.model_copy(deep=True))
    turn = BrainTurn(status="accepted", turn_kind="robot_config", instruction="换成双臂",
                     robot_setup_request={"mode": "dual"})
    app = BrainApplication(BrainConfig(provider="replay", output_dir=str(tmp_path), robot_profiles=current.robot_profiles), provider=Provider(turn))
    app.sessions["s"] = current
    report = app.handle("换成双臂", session_id="s")
    assert report.run_status == "success"
    assert report.scene_commit_status == "unchanged"
    assert "已是" in report.reply
    assert (current.scene, current.robot_setup_revision, current.exported_commands, current.dialogue) == before


def test_different_profile_reports_actual_commit(tmp_path):
    current = session()
    turn = BrainTurn(status="accepted", turn_kind="robot_config", instruction="改回单臂",
                     robot_setup_request={"mode": "single"})
    app = BrainApplication(BrainConfig(provider="replay", output_dir=str(tmp_path), robot_profiles=current.robot_profiles), provider=Provider(turn))
    app.sessions["s"] = current
    report = app.handle("改回单臂", session_id="s")
    assert report.run_status == "success" and report.scene_commit_status == "committed"
    assert current.robot_setup_revision == 2
