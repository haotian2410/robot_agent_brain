import json

from robot_agent_brain.batch import load_batch_input, run_batch
from robot_agent_brain.application import BrainApplication
from robot_agent_brain.config import BrainConfig
from robot_agent_brain.contracts.turn import BrainTurn, SessionControlIntent


class Provider:
    def understand_turn(self, request):
        action = "resume" if request.instruction == "resume" else "pause"
        return BrainTurn(status="accepted", turn_kind="session_control", instruction=action,
                         session_control=SessionControlIntent(action=action))


def test_simple_sessions_input_and_direct_continuity(tmp_path):
    cases = tmp_path / "sessions.json"
    cases.write_text(json.dumps({"sessions": [{"name": "demo", "scene": None,
        "instructions": ["pause", "resume"]}]}, ensure_ascii=False), encoding="utf-8")
    loaded = load_batch_input(cases)
    assert loaded["kind"] == "sessions"
    assert loaded["sessions"][0].name == "demo"
    app = BrainApplication(BrainConfig(provider="replay", output_dir=str(tmp_path / "out")), provider=Provider())
    summary, path = run_batch(app, cases)
    assert summary["totals"] == {"passed": 2, "failed": 0, "skipped": 0}
    assert path.is_file()


def test_simple_sessions_auto_names_and_duplicate_names(tmp_path):
    cases = tmp_path / "sessions.json"
    cases.write_text(json.dumps({"sessions": [
        {"scene": None, "instructions": ["pause"]},
        {"name": "named", "scene": None, "instructions": ["pause"]}]}, ensure_ascii=False), encoding="utf-8")
    loaded = load_batch_input(cases)
    assert [s.name for s in loaded["sessions"]] == ["session-001", "named"]
    cases.write_text(json.dumps({"sessions": [
        {"name": "same", "instructions": ["pause"]},
        {"name": "same", "instructions": ["pause"]}]}, ensure_ascii=False), encoding="utf-8")
    try:
        load_batch_input(cases)
    except ValueError as exc:
        assert str(exc) == "batch_duplicate_session_name"
    else:
        raise AssertionError("duplicate session names must be rejected")


def test_simple_sessions_reject_blank_instruction(tmp_path):
    cases = tmp_path / "sessions.json"
    cases.write_text(json.dumps({"sessions": [{"instructions": ["  "]}]}), encoding="utf-8")
    try:
        load_batch_input(cases)
    except ValueError as exc:
        assert "batch_instruction_required" in str(exc)
    else:
        raise AssertionError("blank instructions must be rejected")
