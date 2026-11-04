"""Success-gated runner for the brain-semantic-matrix.v2 format.

The compiler is deliberately pure and deterministic; this module adds the
optional service execution layer.  A child case is executed only from a
parent turn that produced a real scene snapshot.  No parent success is
simulated when a service, browser, or screenshot is unavailable.
"""
from __future__ import annotations

import json
import hashlib
import re
import time
import uuid
from pathlib import Path

from .batch_matrix_v2 import compile_semantic_matrix_v2, read_semantic_matrix_v2, _stable_index
from .batch_service import ServiceBatchRunner
from .web.protocol import digest


_BUILTIN_FIXTURES = {"workspace_empty", "center_empty"}


def _safe_name(value: str) -> str:
    """Match the service runner's directory-safe session name convention."""
    import re
    result = re.sub(r"[^A-Za-z0-9_-]+", "-", str(value)).strip("-")
    return result[:80] or "session"


def _fixture_path(fixture_dir, fixture_id):
    if not fixture_id or fixture_id in _BUILTIN_FIXTURES or not fixture_dir:
        return None
    candidate = (Path(fixture_dir) / f"{fixture_id}.json").resolve()
    return candidate if candidate.is_file() else None


def _file_sha256(path: Path | None) -> str | None:
    if path is None:
        return None
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def _sample_index(run: dict) -> int | None:
    """Extract the compiler's stable asset-sample axis from a run name.

    The sample axis is part of the campaign contract: a child using sample 2
    must inherit the sample-2 parent baseline, rather than whichever parent
    variant happened to be encountered first.  Older hand-written runners may
    not use the compiler name convention; those runs return ``None`` and are
    matched by the deterministic fallback below.
    """
    value = str(run.get("name") or run.get("outputName") or run.get("output_name") or "")
    match = re.search(r"-a(\d+)(?:-r|$)", value)
    return int(match.group(1)) if match else None


def _eligible_parent_runs(completed: list[dict] | None) -> list[dict]:
    """Return only parent executions with a verified, usable snapshot."""
    values = []
    for item in completed or []:
        snapshot = item.get("parent_snapshot")
        if item.get("status") != "passed" or not isinstance(snapshot, dict):
            continue
        if not snapshot.get("path") or not Path(snapshot["path"]).is_file():
            continue
        values.append(item)
    # Never depend on execution order, Excel row order, or filesystem order
    # when selecting a seed/all parent branch.
    return sorted(values, key=lambda item: (
        str(item.get("variant_id") or ""),
        int(item.get("asset_seed") or 0),
        str(item.get("name") or ""),
    ))


def _select_parent_runs(*, policy: str, row: dict, completed: list[dict] | None,
                        seed: int, case_id: str) -> list[dict]:
    """Select qualified parent snapshots according to the v2 contract.

    ``seed`` is deliberately resolved *after* the parent stage has run.  The
    old implementation selected a variant from the workbook before knowing
    which parent runs passed, so one failed seeded variant incorrectly blocked
    a child even when another qualified parent existed.  ``all`` likewise
    expands only successful, snapshot-bearing parent runs.
    """
    candidates = _eligible_parent_runs(completed)
    if not candidates:
        return []
    policy = str(policy or "none").casefold()
    wanted = str(row.get("parent_variant_id") or "").strip()
    if policy == "fixed":
        candidates = [item for item in candidates if str(item.get("variant_id") or "") == wanted]
    elif policy == "seed":
        # Prefer the same asset-sample axis as the child.  If a legacy runner
        # omitted that axis, use all qualified candidates, still in stable ID
        # order.  Parent selection is one branch for all child variants in a
        # sample, preserving semantic-variant comparability.
        sample = _sample_index(row)
        same_sample = [item for item in candidates if sample is not None and _sample_index(item) == sample]
        pool = same_sample or candidates
        if pool:
            index = _stable_index(seed, case_id, "parent_variant", str(sample or 0), size=len(pool))
            candidates = [pool[index]]
    elif policy == "all":
        pass
    elif policy in {"none", ""}:
        return []
    else:
        return []
    return candidates


def _last_scene_for_run(stage_root: Path, run: dict, summary: dict):
    """Return the final scene evidence for a passed parent run.

    A status string alone is not a usable parent: the child must receive a
    real, digestable snapshot written by the service runner.  This helper also
    avoids guessing a turn number from the compiled prefix length.
    """
    output_name = run.get("outputName") or run.get("output_name") or _safe_name(run.get("name", "session"))
    session_root = stage_root / "sessions" / output_name
    summary_path = session_root / "session_summary.json"
    if not summary_path.is_file():
        return None
    try:
        session = json.loads(summary_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if session.get("status") != "passed":
        return None
    if session.get("expected_outcome") in {
        "clarification_required", "safe_rejection", "capability_unsupported", "blocked"
    }:
        return None
    turns = session.get("turns") or []
    # A parent is qualified only when every executed turn was passed and a
    # final scene file exists.  Skips/blocked screenshots cannot be a baseline.
    if not turns or any(item.get("status") != "passed" or item.get("classification", "passed") != "passed"
                        for item in turns):
        return None
    # A passing historical status is not enough for a semantic parent.  A
    # correct clarification, safe rejection or capability boundary has no
    # generated object state for a child to inherit.  Keep those outcomes in
    # the report, but never promote them to a baseline snapshot.
    usable_classes = {"passed"}
    if any(item.get("classification", "passed") not in usable_classes for item in turns):
        return None
    turn_numbers = sorted(int(item.get("turn", 0) or 0) for item in turns)
    for turn_number in reversed(turn_numbers):
        candidate = session_root / "turns" / f"{turn_number:04d}" / "scene.json"
        if not candidate.is_file():
            continue
        try:
            scene = json.loads(candidate.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        # The sidecar identity is authoritative for lineage.  If a runner
        # recorded a digest, reject a tampered or stale scene instead of
        # recomputing a new baseline silently.
        recorded = next((item for item in turns if int(item.get("turn", 0) or 0) == turn_number), {})
        recorded_scene = recorded.get("scene") if isinstance(recorded.get("scene"), dict) else {}
        recorded_digest = recorded_scene.get("sceneDigest")
        if recorded_digest and recorded_digest != digest(scene):
            continue
        return {
            # Keep the manifest JSON-serializable.  ``Path`` was harmless
            # while selecting a parent but caused every successful campaign
            # to fail while writing campaign_manifest.json.
            "path": str(candidate),
            "digest": digest(scene),
            "scene": scene,
            "session_root": str(session_root),
            # ServiceBatchRunner stores explicit campaign sidecar bindings when
            # present; root compiler sessions carry the same information under
            # asset_role_mapping.  Preserve it in the parent snapshot instead
            # of emitting an empty lineage map.
            "role_bindings": (session.get("role_bindings")
                               or run.get("role_bindings")
                               or run.get("asset_role_mapping")
                               or {}),
            "output_name": output_name,
            "turn": turn_number,
        }
    return None


def run_semantic_campaign(*, matrix, asset_roles, asset_catalog=None, seed=0,
                          kind="generated_edit",
                          agent_url="http://127.0.0.1:8500",
                          gateway_url="http://127.0.0.1:8099", browser_id=None,
                          task_timeout=300, screenshot_required=True,
                          output_dir="var/batch-campaigns", run_profile="default",
                          fixture_dir=None):
    output = Path(output_dir).resolve()
    # The campaign run is an evidence namespace, not a deterministic output
    # artifact.  Include a short nonce so two invocations with the same seed
    # in one second cannot overwrite or abort on the previous run's directory.
    root = output / ("campaign-" + time.strftime("%Y%m%d-%H%M%S") + "-" + str(seed)
                     + "-" + uuid.uuid4().hex[:8])
    root.mkdir(parents=True, exist_ok=False)
    if kind not in {"generated_edit", "known_scene"}:
        raise ValueError(f"semantic_campaign_kind_invalid:{kind}")
    document, compile_manifest = compile_semantic_matrix_v2(
        matrix, kind=kind, asset_roles=asset_roles,
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
        if not parent and fixture_id and fixture_id not in _BUILTIN_FIXTURES:
            fixture_path = _fixture_path(fixture_dir, fixture_id)
            if fixture_path is None:
                stages.append({"test_id": case_id, "status": "blocked_fixture",
                               "classification": "blocked_fixture",
                               "fixture_id": fixture_id, "sessions": [],
                               "reason": "fixture_not_supplied"})
                completed[case_id] = False
                continue
            rows = [dict(item, scene=str(fixture_path)) for item in rows]
        stage_rows = []
        if parent:
            # Parent selection must happen after the parent stage has run.  A
            # workbook's ``seed`` policy is not allowed to select a failed
            # variant before qualification, and ``all`` must expand only
            # successful snapshot-bearing runs.
            parent_runs = completed.get(parent) if isinstance(completed.get(parent), list) else []
            if not _eligible_parent_runs(parent_runs):
                stages.append({"test_id": case_id, "status": "skipped_parent_failed",
                               "classification": "skipped_parent_not_satisfied",
                               "parent_test_id": parent, "sessions": []})
                completed[case_id] = False
                continue

            # Compiler output contains one row per child variant.  For a
            # ``seed`` campaign it may contain only the workbook's provisional
            # parent variant; rebuild the child rows from variant/sample
            # templates after the qualified parent is known.  This keeps the
            # compiler pure while making campaign selection evidence-driven.
            templates = []
            seen_templates = set()
            for row in rows:
                sample_key = (_sample_index(row), row.get("variant_id"), row.get("repeat_index"))
                if sample_key in seen_templates:
                    continue
                seen_templates.add(sample_key)
                templates.append(row)
            policy = spec["cases_by_id"][case_id].get("parent_variant_policy") or "none"
            for row in templates:
                selected = _select_parent_runs(policy=policy, row=row,
                                               completed=parent_runs, seed=seed,
                                               case_id=case_id)
                for parent_row in selected:
                    value = dict(row)
                    parent_snapshot = parent_row["parent_snapshot"]
                    scene_path = Path(parent_snapshot["path"])
                    if not scene_path.is_file():
                        continue
                    # The parent snapshot is now the setup world; execute only
                    # this child expression instead of replaying its prefix.
                    value["instructions"] = [value["instructions"][-1]]
                    value["scene"] = str(scene_path)
                    parent_name = parent_row.get("name")
                    value["name"] = f"{value['name']}-from-{parent_name}"
                    value["parent_run_id"] = parent_name
                    value["parent_variant_id"] = parent_row.get("variant_id")
                    value["parent_scene_path"] = str(scene_path)
                    value["parent_scene_digest"] = parent_snapshot.get("digest")
                    value["baseline_digest"] = parent_snapshot.get("digest")
                    # Role bindings are inherited from the actual parent run;
                    # this prevents a child from silently redrawing object A
                    # when the parent's selected branch differs.
                    value["role_bindings"] = parent_snapshot.get("role_bindings") or parent_row.get("role_bindings") or value.get("asset_role_mapping", {})
                    value["asset_role_mapping"] = value["role_bindings"]
                    value["parent_snapshot_turn"] = parent_snapshot.get("turn")
                    stage_rows.append(value)
        else:
            for row in rows:
                value = dict(row)
                # An explicit fixture is a declared baseline, not a hidden
                # replay of a prior Qwen turn.  The service runner may resolve
                # a concrete fixture path in a future campaign profile; until
                # then retain the ID in the manifest so missing fixtures are
                # reported as evidence rather than model success.
                value["fixture_id"] = value.get("fixture_id")
                stage_rows.append(value)
        if not stage_rows:
            stages.append({"test_id": case_id,
                           "status": "skipped_parent_failed" if parent else "skipped_parent_scene_missing",
                           "classification": "skipped_parent_not_satisfied",
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
                               if (item.get("name") or item.get("session") or item.get("outputName")) == row["name"]), {})
                status = result.get("status")
                # Session summary is the authoritative result; additionally
                # require a persisted final scene and successful turns before
                # making this row available as a child baseline.
                run = {**row, **result, "root": str(stage_root)}
                snapshot = _last_scene_for_run(Path(stage_root), run, summary)
                if status == "passed" and snapshot is not None:
                    run["parent_snapshot"] = snapshot
                    run["parent_scene_digest"] = snapshot["digest"]
                    run["baseline_digest"] = snapshot["digest"]
                    run["role_bindings"] = snapshot.get("role_bindings") or row.get("role_bindings") or row.get("asset_role_mapping", {})
                    passed.append(run)
            # A stage can legitimately have no usable parent snapshot (for
            # example a root row whose expected outcome is a clarification or
            # safe rejection).  That is still a passing *test stage* when all
            # service sessions passed their own expectation; it simply cannot
            # feed a child.  Keep stage status and parent eligibility separate.
            session_results = summary.get("sessions", [])
            result_by_name = {
                str(item.get("name") or item.get("session") or item.get("outputName")): item
                for item in session_results
            }
            expected_names = {str(row.get("name")) for row in stage_rows}
            all_sessions_passed = (
                set(result_by_name) == expected_names
                and all(item.get("status") == "passed" for item in result_by_name.values())
            )
            status = "passed" if all_sessions_passed else "failed"
            stages.append({"test_id": case_id, "parent_test_id": parent,
                           "status": status, "root": str(stage_root),
                           "fixture_id": spec["cases_by_id"][case_id].get("fixture_id"),
                           "fixture_sha256": _file_sha256(_fixture_path(fixture_dir, fixture_id)),
                           "sessions": summary.get("sessions", []),
                           "parent_runs": [{"name": item.get("name"),
                                            "variant_id": item.get("variant_id"),
                                            "parent_variant_id": item.get("parent_variant_id"),
                                            "parent_scene_digest": item.get("parent_scene_digest"),
                                            "baseline_digest": item.get("baseline_digest"),
                                            "parent_scene_path": (item.get("parent_snapshot") or {}).get("path"),
                                            "role_bindings": item.get("role_bindings", {})}
                                           for item in passed]})
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
