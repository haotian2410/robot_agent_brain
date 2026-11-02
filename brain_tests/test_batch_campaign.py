import json

import pytest

openpyxl = pytest.importorskip("openpyxl")

from robot_agent_brain import batch_campaign


def test_campaign_skips_child_when_parent_has_no_success(tmp_path, monkeypatch):
    headers = ["enabled", "flow_id", "parent_flow_id", "difficulty", "stage", "round_index",
               "category", "sample_count", "role_a", "role_b", "placement_1", "placement_2",
               "instruction_template", "variants", "branch_policy", "notes"]
    book = openpyxl.Workbook()
    sheet = book.active
    sheet.title = "matrix"
    sheet.append(headers)
    sheet.append([1, "parent", "", "L1", "generate", 1, "add", 1, "object_a", "", "", "", "增加一个{object_a}", "{object_a}", "seed_parent", ""])
    sheet.append([1, "child", "parent", "L2", "edit", 2, "color", 1, "object_a", "", "", "", "把{object_a}改成蓝色", "把{object_a}改成蓝色", "seed_parent", ""])
    matrix = tmp_path / "matrix.xlsx"
    book.save(matrix)
    roles = tmp_path / "roles.json"
    roles.write_text(json.dumps({"object_a": {"kind": "pickable", "candidates": ["apple"]}}), encoding="utf-8")

    class FakeRunner:
        def __init__(self, **kwargs):
            self.output = kwargs["output_dir"]

        def run(self, case_path):
            payload = json.loads(case_path.read_text(encoding="utf-8"))
            root = self.output / f"stage-{len(payload['sessions'])}"
            root.mkdir(parents=True)
            # Parent deliberately fails, so its child must be skipped.
            return {"sessions": [{"session": payload["sessions"][0]["name"], "status": "failed"}]}, root

    monkeypatch.setattr(batch_campaign, "ServiceBatchRunner", FakeRunner)
    result, _ = batch_campaign.run_campaign(matrix=str(matrix), asset_roles=str(roles), seed=1,
                                             agent_url="http://agent", gateway_url="http://gateway",
                                             output_dir=tmp_path / "out", screenshot_required=False)
    assert any(item.get("status") == "skipped_parent_failed" for item in result["stages"])
