"""Success-gated runner for the brain-semantic-matrix.v2 format.

The compiler is deliberately pure and deterministic; this module adds the
optional service execution layer.  A child case is executed only from a
parent turn that produced a real scene snapshot.  No parent success is
simulated when a service, browser, or screenshot is unavailable.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from .batch_matrix_v2 import compile_semantic_matrix_v2, read_semantic_matrix_v2
from .batch_service import ServiceBatchRunner


def run_semantic_campaign(*, matrix, asset_roles, asset_catalog=None, seed=0,
                          agent_url="http://127.0.0.1:8500",
                          gateway_url="http://127.0.0.1:8099", browser_id=None,
                          task_timeout=300, screenshot_required=True,
                          output_dir="var/batch-campaigns", run_profile="default"):
    output = Path(output_dir).resolve()
    root = output / ("campaign-" + time.strftime("%Y%m%d-%H%M%S") + "-" + str(seed))
    root.mkdir(parents=True, exist_ok=False)
    document, compile_manifest = compile_semantic_matrix_v2(
        matrix, kind="generated_edit", asset_roles=asset_roles,
        asset_catalog=asset_catalog, seed=seed, strict_counts=True,
        run_profile=run_profile)
    compiled = document["sessions"]
    spec = read_semantic_matrix_v2(matrix, strict_counts=True)
    ordered_cases = [str(row["case_id"]) for row in spec["cases"]]
    by_case = {case_id: [item for item in compiled if item.get("test_id") == case_id]
               for case_id in ordered_cases}
    completed = {}
    stages = []
    for case_id in ordered_cases:
        rows = by_case.get(case_id, [])
        parent = spec["cases_by_id"][case_id].get("parent_case_id")
        if parent and not completed.get(parent):
            stages.append({"test_id": case_id, "status": "skipped_parent_failed",
                           "parent_test_id": parent, "sessions": []})
            completed[case_id] = False
            continue
        stage_rows = []
        for row in rows:
            value = dict(row)
            if parent:
                parent_rows = [item for item in completed[parent]
                               if item.get("status") == "passed"]
                if not parent_rows:
                    continue
                wanted = row.get("parent_variant_id")
                parent_row = next((item for item in parent_rows
                                   if not wanted or item.get("variant_id") == wanted), parent_rows[0])
                parent_root = Path(parent_row["root"])
                parent_name = parent_row["name"]
                parent_turns = len(parent_row.get("instructions") or [])
                scene_path = parent_root / "sessions" / parent_name / "turns" / f"{parent_turns:04d}" / "scene.json"
                if not scene_path.is_file():
                    continue
                # The parent snapshot is now the setup world; execute only the
                # child expression instead of replaying the prefix a second time.
                value["instructions"] = [value["instructions"][-1]]
                value["scene"] = str(scene_path)
                value["name"] = f"{value['name']}-from-{parent_name}"
            stage_rows.append(value)
        if not stage_rows:
            stages.append({"test_id": case_id, "status": "skipped_parent_scene_missing",
                           "parent_test_id": parent, "sessions": []})
            completed[case_id] = False
            continue
        stage_input = root / f"{case_id}.json"
        stage_input.write_text(json.dumps({"sessions": stage_rows}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        runner = ServiceBatchRunner(agent_url=agent_url, gateway_url=gateway_url,
                                    browser_id=browser_id, task_timeout=task_timeout,
                                    screenshot_required=screenshot_required,
                                    output_dir=root / "stages")
        try:
            summary, stage_root = runner.run(stage_input)
            passed = []
            for row in stage_rows:
                result = next((item for item in summary.get("sessions", [])
                               if item.get("name") == row["name"]), {})
                if result.get("status") == "passed":
                    passed.append({**row, "status": "passed", "root": str(stage_root)})
            status = "passed" if passed and len(passed) == len(stage_rows) else "failed"
            stages.append({"test_id": case_id, "parent_test_id": parent,
                           "status": status, "root": str(stage_root),
                           "sessions": summary.get("sessions", [])})
            completed[case_id] = passed
        except Exception as exc:
            stages.append({"test_id": case_id, "parent_test_id": parent,
                           "status": "blocked", "error": str(exc), "sessions": []})
            completed[case_id] = False
    result = {"schema": "brain-semantic-matrix.v2", "kind": "semantic_campaign",
              "seed": seed, "matrix": str(Path(matrix).resolve()),
              "compile_manifest": compile_manifest, "stages": stages}
    (root / "campaign_manifest.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result, root
