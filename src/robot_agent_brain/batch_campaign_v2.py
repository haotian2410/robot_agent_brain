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
from .web.protocol import digest


def run_semantic_campaign(*, matrix, asset_roles, asset_catalog=None, seed=0,
                          agent_url="http://127.0.0.1:8500",
                          gateway_url="http://127.0.0.1:8099", browser_id=None,
                          task_timeout=300, screenshot_required=True,
                          output_dir="var/batch-campaigns", run_profile="default",
                          fixture_dir=None):
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
    # case_id -> list of *successful* parent runs.  A failed/blocked parent is
    # intentionally not represented as a usable snapshot.
    completed = {}
    stages = []
    for case_id in ordered_cases:
        rows = by_case.get(case_id, [])
        parent = spec["cases_by_id"][case_id].get("parent_case_id")
        fixture_id = spec["cases_by_id"][case_id].get("fixture_id")
        # ``workspace_empty`` is the built-in empty-table baseline.  Every
        # other root fixture must be supplied explicitly; never run a Qwen
        # expression against an unrelated empty world and call it a pass.
        if not parent and fixture_id and fixture_id != "workspace_empty":
            fixture_path = None
            if fixture_dir:
                candidate = Path(fixture_dir) / f"{fixture_id}.json"
                if candidate.is_file():
                    fixture_path = candidate.resolve()
            if fixture_path is None:
                stages.append({"test_id": case_id, "status": "blocked_fixture",
                               "fixture_id": fixture_id, "sessions": [],
                               "reason": "fixture_not_supplied"})
                completed[case_id] = False
                continue
            rows = [dict(item, scene=str(fixture_path)) for item in rows]
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
                value["parent_run_id"] = parent_name
                value["parent_scene_path"] = str(scene_path)
                try:
                    parent_scene = json.loads(scene_path.read_text(encoding="utf-8"))
                    value["parent_scene_digest"] = digest(parent_scene)
                except (OSError, ValueError):
                    value["parent_scene_digest"] = None
                value["baseline_digest"] = value["parent_scene_digest"]
                value["role_bindings"] = value.get("asset_role_mapping", {})
            else:
                # An explicit fixture is a declared baseline, not a hidden
                # replay of a prior Qwen turn.  The service runner may resolve
                # a concrete fixture path in a future campaign profile; until
                # then retain the ID in the manifest so a missing fixture is
                # reported as fixture evidence rather than model success.
                value["fixture_id"] = value.get("fixture_id")
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
                           "fixture_id": spec["cases_by_id"][case_id].get("fixture_id"),
                           "sessions": summary.get("sessions", []),
                           "parent_runs": [{"name": item.get("name"),
                                            "parent_scene_digest": item.get("parent_scene_digest"),
                                            "baseline_digest": item.get("baseline_digest"),
                                            "role_bindings": item.get("role_bindings", {})}
                                           for item in stage_rows]})
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
