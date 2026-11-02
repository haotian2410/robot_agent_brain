"""Seeded, success-gated campaign runner for generated/edit matrices.

Each child flow is started from a successful parent's last scene snapshot.  A
child is never run against a failed or ambiguous parent, and the campaign
manifest records the exact reason whenever a branch is skipped.
"""
from __future__ import annotations

import json
import tempfile
import time
from pathlib import Path
from typing import Any

from .batch_matrix import compile_matrix
from .batch_service import ServiceBatchRunner


def _write_cases(directory: Path, sessions: list[dict[str, Any]]) -> Path:
    path = directory / "cases.json"
    path.write_text(json.dumps({"sessions": sessions}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def _final_scene(root: Path, session: dict[str, Any]) -> Path | None:
    turns = session.get("instructions") or []
    if not turns:
        return None
    path = root / "sessions" / session["name"] / "turns" / f"{len(turns):04d}" / "scene.json"
    return path if path.is_file() else None


def run_campaign(*, matrix: str, asset_roles: str | None, seed: int,
                 agent_url: str, gateway_url: str, output_dir: str | Path,
                 browser_id: str | None = None, task_timeout: float = 300,
                 screenshot_required: bool = True) -> tuple[dict[str, Any], Path]:
    output = Path(output_dir).resolve()
    root = output / ("campaign-" + time.strftime("%Y%m%d-%H%M%S") + "-" + str(seed))
    root.mkdir(parents=True, exist_ok=False)
    compiled, manifest = compile_matrix(matrix, kind="generated_edit", asset_roles=asset_roles,
                                        seed=seed, output=None)
    sessions = compiled.get("sessions", [])
    by_flow: dict[str, list[dict[str, Any]]] = {}
    for session in sessions:
        by_flow.setdefault(session.get("flow_id") or session["name"], []).append(session)
    parent_of = {flow: next((item.get("parent_flow_id") for item in items if item.get("parent_flow_id")), None)
                 for flow, items in by_flow.items()}
    pending = set(by_flow)
    completed: set[str] = set()
    stages: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="robot-brain-campaign-") as temp_name:
        temp = Path(temp_name)
        while pending:
            ready = sorted(flow for flow in pending if parent_of.get(flow) in completed or parent_of.get(flow) is None)
            if not ready:
                raise ValueError("batch_campaign_flow_cycle_or_missing_parent")
            for flow in ready:
                pending.remove(flow)
                candidates = by_flow[flow]
                parent_flow = parent_of.get(flow)
                selected_parent = None
                if parent_flow:
                    parent_runs = [item for item in stages if item.get("flow_id") == parent_flow and item.get("status") == "passed"]
                    if not parent_runs:
                        stages.append({"flow_id": flow, "status": "skipped_parent_failed",
                                       "parent_flow_id": parent_flow, "sessions": []})
                        completed.add(flow)
                        continue
                    selected_parent = parent_runs[(seed + len(stages)) % len(parent_runs)]
                stage_sessions = []
                for session in candidates:
                    value = dict(session)
                    if selected_parent:
                        parent_session = selected_parent["passed_defs"][(seed + len(stage_sessions)) % len(selected_parent["passed_defs"])]
                        parent_instructions = parent_session.get("instructions", [])
                        value["instructions"] = value.get("instructions", [])[len(parent_instructions):] or ["查询当前场景"]
                        scene = _final_scene(selected_parent["root"], parent_session)
                        if scene is None:
                            continue
                        value["scene"] = str(scene)
                        value["name"] = f"{session['name']}-from-{parent_session['name']}"
                    stage_sessions.append(value)
                if not stage_sessions:
                    stages.append({"flow_id": flow, "status": "skipped_parent_scene_missing",
                                   "parent_flow_id": parent_flow, "sessions": []})
                    completed.add(flow)
                    continue
                case_path = _write_cases(temp, stage_sessions)
                runner = ServiceBatchRunner(agent_url=agent_url, gateway_url=gateway_url,
                                            browser_id=browser_id, task_timeout=task_timeout,
                                            screenshot_required=screenshot_required,
                                            output_dir=root / "stages")
                summary, stage_root = runner.run(case_path)
                passed = [item for item in stage_sessions
                          if next((s for s in summary.get("sessions", []) if s.get("session") == item["name"]), {}).get("status") == "passed"]
                stages.append({"flow_id": flow, "parent_flow_id": parent_flow,
                               "status": "passed" if passed else "failed",
                               "root": str(stage_root), "sessions": summary.get("sessions", []),
                               "passed_sessions": [item["name"] for item in passed],
                               "passed_defs": passed, "_session_defs": stage_sessions})
                completed.add(flow)
    # Remove internal definitions from the public manifest while retaining the
    # paths needed to audit every stage.
    for item in stages:
        item.pop("_session_defs", None)
        item.pop("passed_defs", None)
    result = {"kind": "generated_edit_campaign", "seed": seed,
              "matrix": str(Path(matrix).resolve()), "compile_manifest": manifest,
              "stages": stages}
    (root / "campaign_manifest.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result, root
