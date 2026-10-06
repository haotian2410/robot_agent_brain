import json
from robot_agent_brain.application import BrainApplication
from robot_agent_brain.batch import run_batch
from robot_agent_brain.config import BrainConfig
from robot_agent_brain.contracts.turn import BrainTurn, SceneQueryIntent, SessionControlIntent


class Provider:
    def understand_turn(self, request):
        if request.instruction == "query":
            return BrainTurn(status="accepted", turn_kind="scene_query", instruction="query",
                             scene_query=SceneQueryIntent(query_type="count", semantic_name="apple"))
        return BrainTurn(status="accepted", turn_kind="session_control", instruction="pause",
                         session_control=SessionControlIntent(action="pause"))


def test_failed_dependency_skips_but_independent_group_continues(tmp_path):
    cases = tmp_path / "cases.jsonl"
    cases.write_text("\n".join(json.dumps(c) for c in [
        {"case_id":"fail","session_group":"a","instruction":"query"},
        {"case_id":"skip","session_group":"a","instruction":"pause"},
        {"case_id":"independent","session_group":"b","instruction":"pause",
         "expected":{"turn_kind":"session_control","run_status":"success","absent_artifacts":["commands"],
                     "assertions":{"executed":False}}}]))
    app = BrainApplication(BrainConfig(provider="replay",output_dir=str(tmp_path / "out")),provider=Provider())
    summary, path = run_batch(app, cases)
    assert summary["totals"] == {"passed":1,"failed":1,"skipped":1}
    assert json.loads(path.read_text()) == summary
