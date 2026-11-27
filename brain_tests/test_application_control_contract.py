"""Application boundary tests; advertised contracts here are fixtures, not live Control."""
import json
from pathlib import Path
import pytest

from robot_agent_brain.application import BrainApplication
from robot_agent_brain.config import BrainConfig
from robot_agent_brain.contracts.control_skill_contract import ControlSkillContract
from test_application_artifacts import Provider, robot
from test_control_skill_contract import contract
from test_dual_v4_pipeline import setup
from test_dual_session_pipeline import task


def test_application_default_does_not_infer_control_contract(tmp_path):
    app = BrainApplication(BrainConfig(provider="replay", output_dir=str(tmp_path)),
                           provider=Provider(robot()))
    assert app.pipeline.control_skill_contract is None


@pytest.mark.parametrize("as_model", [False, True])
def test_adapter_contract_is_defensive_validated_snapshot(tmp_path, as_model):
    raw = contract()
    advertised = ControlSkillContract.model_validate(raw) if as_model else raw
    app = BrainApplication(BrainConfig(provider="replay", output_dir=str(tmp_path)),
                           provider=Provider(robot()), control_skill_contract=advertised)
    snapshot = app.pipeline.control_skill_contract
    if as_model:
        advertised.skills["pick"].parameters_schema["required"].append("changed")
        advertised.supported_protocols.clear()
    else:
        advertised["skills"]["pick"]["parameters_schema"]["required"].append("changed")
        advertised["supported_protocols"].clear()
    assert snapshot.supported_protocols == ["4.0"]
    assert snapshot.skills["pick"].parameters_schema["required"] == ["source"]


def test_invalid_contract_rejected_before_provider_or_asset_initialization(tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("invalid contract must fail before loading assets")
    monkeypatch.setattr(BrainConfig, "load_assets", forbidden)
    raw = contract()
    raw["supports_sync"] = "true"
    with pytest.raises(ValueError, match="bool_type"):
        BrainApplication(BrainConfig(output_dir=str(tmp_path)), control_skill_contract=raw)


@pytest.mark.parametrize("advertised,code", [(None, "control_dual_arm_not_ready"),
    ({**contract(), "supported_protocols": ["3.0"]}, "unsupported_protocol_version")])
def test_public_dual_request_without_v4_contract_has_no_bootstrap_side_effects(tmp_path, advertised, code):
    fixture = setup("qwen")
    provider = Provider(task())
    app = BrainApplication(BrainConfig(provider="replay", planner="qwen", output_dir=str(tmp_path),
                                       robot_profiles=fixture.robot_profiles),
                           provider=provider, control_skill_contract=advertised)
    report = app.handle("用右臂抓起苹果")
    assert report.error.code == code
    assert not report.executed
    assert "commands" not in report.artifacts
    assert app.get_session(report.session_id).scene is None
    assert provider.count == 1
    assert not (tmp_path / report.session_id / "original_scene.json").exists()


def test_application_session_can_plan_with_explicit_contract_without_dispatch(tmp_path):
    fixture = setup("qwen")
    class Planner(Provider):
        def plan(self, request):
            raise AssertionError("legacy skill planner must not be used")

        def plan_dual_operations(self, request):
            return {"operations": [{"operation_id": op.operation_id,
                "steps": [{"skill_name": "pick", "parameters": {"source": op.source_object_id}}]}
                for op in request.operations]}

    app = BrainApplication(BrainConfig(provider="replay", planner="qwen", output_dir=str(tmp_path),
                                       robot_profiles=fixture.robot_profiles),
                           provider=Planner(task()),
                           control_skill_contract=fixture.pipeline.control_skill_contract)
    session = app.get_session("contract-fixture")
    session.initialize_scene(fixture.scene)
    session.bind_imported_profile(fixture.robot_profiles.profiles["fixture_only"])
    result = session.process_turn("explicit-contract", task())
    assert result.commands.schema_version == "4.0"
    assert result.commands.skill_contract_revision == "fixture-reviewed-v1"
    assert result.commands.commands[0].parameters == {"source": 7}
    with pytest.raises(ValueError, match="unsupported_protocol_version"):
        session.mark_dispatched(result.commands)
    assert session.pending_execution_request is None

    # Exercise the public application orchestration/artifact path, rather than
    # treating a successful direct Session call as proof that reports work.
    before = session.scene.raw_document()
    report = app.handle("用右臂抓起苹果", session_id="contract-fixture")
    assert report.run_status == "success", report.error
    assert report.executed is False
    assert report.metrics["understanding_calls"] == 1
    assert report.metrics["skill_planning_calls"] == 1
    commands = json.loads(Path(report.artifacts["commands"]).read_text())
    scene = json.loads(Path(report.artifacts["scene_config"]).read_text())
    from robot_agent_brain.web.protocol import digest
    assert commands["schema_version"] == "4.0"
    assert commands["scene_digest"] == digest(scene) == digest(before)
    assert commands["skill_contract_revision"] == "fixture-reviewed-v1"
    assert session.scene.raw_document() == before
    assert session.arm_states.arms["right"].holding_object is None
    assert session.pending_execution_request is None
