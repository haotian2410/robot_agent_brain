"""C6 campaign-v2 contract tests.

These tests use a deterministic ServiceBatchRunner substitute.  They exercise
the campaign's lineage/qualification logic without claiming a browser or Qwen
run: the real C7 run is reported separately when those services are available.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from robot_agent_brain import batch_campaign_v2 as campaign
from robot_agent_brain.batch_service import _result_classification, _semantic_result_classification
from robot_agent_brain.batch import BatchSession
from robot_agent_brain.web.protocol import digest


def _spec(cases, variants_by_case):
    rows = []
    for case_id, parent, policy in cases:
        rows.append({
            "case_id": case_id, "parent_case_id": parent,
            "parent_variant_policy": policy, "parent_variant_id": None,
            "fixture_id": "workspace_empty" if parent is None else None,
        })
    by_id = {row["case_id"]: row for row in rows}
    return {
        "cases": rows, "cases_by_id": by_id,
        "variants_by_case": variants_by_case,
        "variants": [item for values in variants_by_case.values() for item in values],
    }


def _compiled(spec):
    sessions = []
    for case in spec["cases"]:
        case_id = case["case_id"]
        for variant in spec["variants_by_case"][case_id]:
            # The compiler's provisional seed parent is intentionally V01;
            # the campaign must replace it with a qualified run after stage
            # execution if V01 fails.
            parent_variant = variant.get("parent_variant_id") or "V01"
            sessions.append({
                "name": f"{case_id}-{variant['variant_id']}-a01-r01",
                "test_id": case_id, "variant_id": variant["variant_id"],
                "parent_variant_id": parent_variant,
                "instructions": [variant["instruction_template"]],
                "asset_role_mapping": {"object_a": {"semantic_name": "apple"}},
                "asset_seed": 1,
            })
    return {"sessions": sessions}


class _FakeRunner:
    """Write the same evidence shape used by ServiceBatchRunner."""

    calls = []
    fail_parent_variant = None
    expected_clarification = False

    def __init__(self, **kwargs):
        self.output = Path(kwargs["output_dir"])

    def run(self, input_path):
        payload = json.loads(Path(input_path).read_text(encoding="utf-8"))
        _FakeRunner.calls.append(payload)
        stage_root = self.output / f"stage-{len(_FakeRunner.calls)}"
        sessions_root = stage_root / "sessions"
        sessions_root.mkdir(parents=True)
        summaries = []
        for row in payload["sessions"]:
            name = row["name"]
            is_failed = self.fail_parent_variant and row.get("test_id") == "T01" and row.get("variant_id") == self.fail_parent_variant
            status = "failed" if is_failed else "passed"
            scene = {"scene_schema_version": 1, "scene_id": 100 + len(summaries),
                     "scene_version": 1, "scene_sub_version": 0,
                     "scene_name": "fixture", "objects": []}
            session_dir = sessions_root / name
            turn_dir = session_dir / "turns" / "0001"
            turn_dir.mkdir(parents=True)
            (turn_dir / "scene.json").write_text(json.dumps(scene), encoding="utf-8")
            turn = {"turn": 1, "status": "passed" if status == "passed" else "failed",
                    "classification": "passed" if status == "passed" else "failed_protocol/runtime",
                    "scene": {"sceneDigest": digest(scene)}}
            summary = {"name": name, "outputName": name, "sessionID": name,
                       "status": status, "role_bindings": row.get("asset_role_mapping", {}),
                       "turns": [turn]}
            (session_dir / "session_summary.json").write_text(json.dumps(summary), encoding="utf-8")
            summaries.append({"session": name, "status": status})
        return {"sessions": summaries}, stage_root


@pytest.fixture(autouse=True)
def _reset_fake():
    _FakeRunner.calls = []
    _FakeRunner.fail_parent_variant = None
    yield


def _patch_campaign(monkeypatch, spec):
    monkeypatch.setattr(campaign, "compile_semantic_matrix_v2", lambda *args, **kwargs: (_compiled(spec), {"case_count": len(spec["cases"])}))
    monkeypatch.setattr(campaign, "read_semantic_matrix_v2", lambda *args, **kwargs: spec)
    monkeypatch.setattr(campaign, "ServiceBatchRunner", _FakeRunner)


def test_seed_selects_a_qualified_parent_after_parent_execution(tmp_path, monkeypatch):
    variants = {
        "T01": [{"variant_id": "V01", "instruction_template": "add A"},
                {"variant_id": "V02", "instruction_template": "add A differently"}],
        "T02": [{"variant_id": "C01", "instruction_template": "move A"},
                {"variant_id": "C02", "instruction_template": "color A"}],
    }
    spec = _spec([("T01", None, "none"), ("T02", "T01", "seed")], variants)
    _FakeRunner.fail_parent_variant = "V01"
    _patch_campaign(monkeypatch, spec)
    result, _ = campaign.run_semantic_campaign(
        matrix=tmp_path / "matrix.xlsx", asset_roles=None, seed=7,
        output_dir=tmp_path / "out", screenshot_required=False)
    child_stage = next(item for item in result["stages"] if item["test_id"] == "T02")
    assert child_stage["status"] == "passed"
    assert len(child_stage["sessions"]) == 2
    # V02 is the only qualified parent; the campaign must not remain pinned
    # to the compiler's provisional V01 choice.
    assert all(item["parent_variant_id"] == "V02" for item in child_stage["parent_runs"])
    assert len(_FakeRunner.calls[1]["sessions"]) == 2


def test_all_expands_only_qualified_parent_runs_and_isolates_children(tmp_path, monkeypatch):
    variants = {
        "T01": [{"variant_id": "V01", "instruction_template": "add A"},
                {"variant_id": "V02", "instruction_template": "add A differently"}],
        "T02": [{"variant_id": "C01", "instruction_template": "move A"},
                {"variant_id": "C02", "instruction_template": "color A"}],
    }
    spec = _spec([("T01", None, "none"), ("T02", "T01", "all")], variants)
    _patch_campaign(monkeypatch, spec)
    result, _ = campaign.run_semantic_campaign(
        matrix=tmp_path / "matrix.xlsx", asset_roles=None, seed=11,
        output_dir=tmp_path / "out", screenshot_required=False)
    child_stage = next(item for item in result["stages"] if item["test_id"] == "T02")
    assert child_stage["status"] == "passed"
    assert len(_FakeRunner.calls[1]["sessions"]) == 4
    assert {item["parent_variant_id"] for item in child_stage["parent_runs"]} == {"V01", "V02"}
    # Every child is a fresh branch rooted at a parent snapshot; no child
    # receives the previous child session's scene path.
    paths = [item["parent_scene_path"] for item in child_stage["parent_runs"]]
    assert len(paths) == len(set(paths)) == 4


def test_fixed_parent_variant_failure_skips_child_without_fallback(tmp_path, monkeypatch):
    variants = {
        "T01": [{"variant_id": "V01", "instruction_template": "add A"},
                {"variant_id": "V02", "instruction_template": "add A differently"}],
        "T02": [{"variant_id": "C01", "instruction_template": "move A"}],
    }
    spec = _spec([("T01", None, "none"), ("T02", "T01", "fixed")], variants)
    spec["cases_by_id"]["T02"]["parent_variant_id"] = "V01"
    _patch_campaign(monkeypatch, spec)
    _FakeRunner.fail_parent_variant = "V01"
    result, _ = campaign.run_semantic_campaign(
        matrix=tmp_path / "matrix.xlsx", asset_roles=None, seed=13,
        output_dir=tmp_path / "out", screenshot_required=False)
    child_stage = next(item for item in result["stages"] if item["test_id"] == "T02")
    assert child_stage["status"] == "skipped_parent_failed"
    assert len(_FakeRunner.calls) == 1


def test_root_expected_non_success_can_pass_but_cannot_feed_child(tmp_path, monkeypatch):
    variants = {
        "T01": [{"variant_id": "V01", "instruction_template": "ask"}],
        "T02": [{"variant_id": "C01", "instruction_template": "move A"}],
    }
    spec = _spec([("T01", None, "none"), ("T02", "T01", "fixed")], variants)
    # The fake stage still reports a passed session; its lack of an explicitly
    # valid scene can be represented by removing the scene after execution.
    _patch_campaign(monkeypatch, spec)
    original = _FakeRunner.run

    class NoParentSnapshotRunner(_FakeRunner):
        def run(self, input_path):
            summary, root = original(self, input_path)
            if json.loads(Path(input_path).read_text())["sessions"][0]["test_id"] == "T01":
                for path in (root / "sessions").glob("*/session_summary.json"):
                    value = json.loads(path.read_text())
                    value["turns"][0]["classification"] = "expected_clarification"
                    path.write_text(json.dumps(value))
            return summary, root

    monkeypatch.setattr(campaign, "ServiceBatchRunner", NoParentSnapshotRunner)
    result, _ = campaign.run_semantic_campaign(
        matrix=tmp_path / "matrix.xlsx", asset_roles=None, seed=2,
        output_dir=tmp_path / "out", screenshot_required=False)
    parent_stage = next(item for item in result["stages"] if item["test_id"] == "T01")
    child_stage = next(item for item in result["stages"] if item["test_id"] == "T02")
    assert parent_stage["status"] == "passed"
    assert child_stage["status"] == "skipped_parent_failed"


def test_missing_root_fixture_blocks_and_cascades_without_running_qwen(tmp_path, monkeypatch):
    variants = {
        "T01": [{"variant_id": "V01", "instruction_template": "add A"}],
        "T02": [{"variant_id": "C01", "instruction_template": "move A"}],
    }
    spec = _spec([("T01", None, "none"), ("T02", "T01", "fixed")], variants)
    spec["cases_by_id"]["T01"]["fixture_id"] = "fixture_required"
    _patch_campaign(monkeypatch, spec)
    result, _ = campaign.run_semantic_campaign(
        matrix=tmp_path / "matrix.xlsx", asset_roles=None, seed=3,
        output_dir=tmp_path / "out", screenshot_required=False)
    assert result["stages"][0]["status"] == "blocked_fixture"
    assert result["stages"][1]["status"] == "skipped_parent_failed"
    assert _FakeRunner.calls == []


def test_parent_snapshot_turn_is_preserved_in_batch_session_contract():
    """Campaign lineage metadata must survive strict BatchSession parsing."""
    session = BatchSession.model_validate({
        "name": "child",
        "instructions": ["move A"],
        "parent_snapshot_turn": 1,
    })
    assert session.parent_snapshot_turn == 1


def test_semantic_clarification_is_preserved_when_screenshot_is_blocked():
    """Separate a correct semantic result from missing browser evidence."""
    class Spec:
        expected_outcome = "clarification_required"

    result = {"outcome": "clarification_required", "executed": False}
    oracle = {"status": "expected_clarification"}
    semantic = _semantic_result_classification(
        session_spec=Spec(), result=result, assertion_result="passed",
        oracle=oracle, semantic_ok=True)
    envelope = _result_classification(
        session_spec=Spec(), result=result, assertion_result="passed",
        oracle=oracle, screenshot_ok=False, ok=False)
    assert semantic == "expected_clarification"
    assert envelope == "blocked"
