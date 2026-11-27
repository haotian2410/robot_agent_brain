"""Run with a freshly installed wheel's Python, from outside the checkout."""
import json
import os
import subprocess
import sys
import tempfile
import importlib.util
from importlib.resources import files
from pathlib import Path

import robot_agent_brain
from jsonschema import Draft202012Validator
from robot_agent_brain.config import BrainConfig
from robot_agent_brain.contracts.commands import CommandsFile
from robot_agent_brain.contracts.commands_atomic import AtomicCommandsFile
from robot_agent_brain.contracts.scene import SceneConfig
from robot_agent_brain.scene.component_access import SceneIndex
from robot_agent_brain.models.prompts import TASK_UNDERSTANDING_PROMPT, SKILL_PLANNING_PROMPT
from robot_agent_brain.models.prompts import DUAL_SKILL_PLANNING_PROMPT
from robot_agent_brain.contracts.commands_sequence_v41 import CommandsFileV41
from robot_agent_brain.skills.registry import REGISTRY


def main():
    checkout = Path(__file__).resolve().parents[1]
    installed = Path(robot_agent_brain.__file__).resolve()
    assert not installed.is_relative_to(checkout), installed
    assert not Path.cwd().resolve().is_relative_to(checkout), Path.cwd()
    assert installed.is_relative_to(Path(sys.prefix).resolve()), installed
    assert not (installed.parent / ".idea").exists()
    assert not (installed.parent / "robot_agent.md").exists()
    assert TASK_UNDERSTANDING_PROMPT
    assert SKILL_PLANNING_PROMPT and REGISTRY.prompt_catalog()
    assert DUAL_SKILL_PLANNING_PROMPT
    from robot_agent_brain.models.prompts import LAYOUT_PLANNING_PROMPT, ARM_ASSIGNMENT_PROMPT
    from robot_agent_brain.contracts.arrangement import ArrangementSpec, LayoutPlan, LayoutResolution
    from robot_agent_brain.contracts.commands_dag_v4 import CommandsFileV4
    from robot_agent_brain.planning.layout_planner import plan_arrangement
    assert LAYOUT_PLANNING_PROMPT and ARM_ASSIGNMENT_PROMPT
    for name, model in {
        "arrangement_spec": ArrangementSpec, "layout_plan": LayoutPlan,
        "layout_resolution": LayoutResolution, "commands_dag_v4": CommandsFileV4,
        "commands_sequence_v41": CommandsFileV4,
    }.items():
        resource = files("robot_agent_brain").joinpath("schemas", name + ".schema.json")
        packaged = json.loads(resource.read_text(encoding="utf-8"))
        expected = {"$schema": "https://json-schema.org/draft/2020-12/schema",
                    "$id": name + ".schema.json", **model.model_json_schema()}
        assert packaged == expected, name
    arrangement = ArrangementSpec(arrangement_id="arr-installed", pattern={"kind": "grid", "rows": 2, "cols": 3},
        items={"assets": [{"alias": "apple"}], "requested_count": 6},
        region={"surface_ref": "table"}, spacing={"mode": "center", "value_m": .1})
    assert len(plan_arrangement(arrangement).slots) == 6
    from robot_agent_brain.models.understanding_wire import encode, decode
    layout_wire = encode({"protocol_version": "task_understanding.v3.1", "status": "accepted",
        "turn_kind": "scene_layout", "arrangement_spec": arrangement.model_dump(mode="json")})
    assert decode(layout_wire)["arrangement_spec"]["items"]["requested_count"] == 6
    from robot_agent_brain.planning.layout_quantity import quantity_candidates
    bounded = arrangement.model_dump(mode="json")
    bounded["pattern"] = {"kind": "line"}
    bounded["items"].update(count_mode="auto", auto_count=True, min_count=2, max_count=8)
    bounded = ArrangementSpec.model_validate(bounded)
    assert [value.items.requested_count for value in quantity_candidates(bounded)] == [6, 5, 7, 4, 8, 3, 2]
    bounded_wire = encode({"status": "accepted", "turn_kind": "scene_layout",
                           "arrangement_spec": bounded.model_dump(mode="json")})
    restored = ArrangementSpec.model_validate(decode(bounded_wire)["arrangement_spec"])
    assert restored == bounded
    from robot_agent_brain.planning.layout_constraints import validate_explicit_layout_constraints
    circle = arrangement.model_copy(update={"pattern": arrangement.pattern.model_validate(
        {"kind": "circle", "radius_m": .2})})
    validate_explicit_layout_constraints("半径固定为20厘米", circle)
    try:
        validate_explicit_layout_constraints("半径固定为30厘米", circle)
    except ValueError as error:
        assert "explicit_dimension_mismatch" in str(error)
    else:
        raise AssertionError("installed wheel silently accepted changed radius")
    from robot_agent_brain.application import BrainApplication
    contract = {"revision": "wheel-fixture-only", "supported_protocols": ["4.1"],
        "expansion_level": "task", "skills": {"pick": {"expansion_level": "task",
        "parameters_schema": {"type": "object"}}}}
    app = BrainApplication(BrainConfig(provider="replay",
        output_dir=tempfile.mkdtemp(prefix="brain-wheel-contract-")),
        provider=object(), control_skill_contract=contract)
    contract["supported_protocols"].clear()
    assert app.pipeline.control_skill_contract.supported_protocols == ["4.1"]
    assert files("robot_agent_brain.resources").joinpath("config.json").is_file()
    config = BrainConfig()
    assert config.planner == "qwen"
    assert config.load_assets() and config.load_defaults()
    environment = {key:value for key,value in os.environ.items() if key != "PYTHONPATH" and not key.startswith("ROBOT_BRAIN_")}
    executable = Path(sys.executable).parent / "robot-brain"
    directory = Path(tempfile.mkdtemp(prefix="brain-wheel-smoke-"))
    def run(*args):
        result = subprocess.run([str(executable), *args], cwd=directory, env=environment,
                                capture_output=True, text=True, timeout=30)
        assert result.returncode == 0, (result.returncode, result.stdout, result.stderr)
        return result.stdout
    assert "run" in run("--help")
    assert "camera-id" in run("serve", "--help")
    web_tested = importlib.util.find_spec('aiohttp') is not None and importlib.util.find_spec('rfc8785') is not None
    if web_tested:
        from robot_agent_brain.web.service import AgentService, create_http_app
        from robot_agent_brain.web.protocol import digest
        from robot_agent_brain.web.task_store import TaskStore
        assert digest({'x':1.0}) == digest({'x':1})
        service = AgentService(BrainConfig(model='wheel-smoke-no-network',scene_id_bits=32,output_dir=str(directory/'web')))
        assert any(route.resource.canonical=='/startTask' for route in create_http_app(service).router.routes())
        service.tasks.close()
    run("schemas", "--output-dir", str(directory / "schemas"))
    schema = json.loads((directory / "schemas" / "commands.schema.json").read_text(encoding="utf-8"))
    assert schema == CommandsFile.model_json_schema()
    assert json.loads((directory / "schemas" / "commands_v41.schema.json").read_text(encoding="utf-8")) == CommandsFileV41.model_json_schema()
    scene_schema = json.loads((directory / "schemas" / "scene_config.schema.json").read_text(encoding="utf-8"))
    assert scene_schema == SceneConfig.model_json_schema()
    instruction = "把两个苹果放进篮子"
    fixture = [{"instruction":instruction, "turn":{"status":"accepted", "turn_kind":"robot_task", "instruction":instruction,
        "task_intent":{"instruction":instruction,
            "entities":[{"entity_id":"a", "semantic_name":"apple", "category":"fruit", "count":2, "quantity_mode":"all"},
                        {"entity_id":"b", "semantic_name":"basket", "category":"container"}],
            "operations":[{"operation_id":"op-1", "task_type":"pick_and_place", "source":"a", "destination":"b",
                "placement_target":{"kind":"container_interior", "reference":"b", "relation":"inside"}}]}}}]
    plural = "它们有几个？"
    fixture.append({"instruction": plural + " [dialogue_ref_set=apple]", "turn": {
        "status":"accepted", "turn_kind":"scene_query", "instruction":plural,
        "scene_query":{"query_type":"count", "entities":[{"entity_id":"a", "semantic_name":"apple", "category":"fruit",
            "dialogue_ref_set":True, "quantity_mode":"all", "all_available":True}], "relations":[], "target":"a"}}})
    add = "增加一个香蕉"
    fixture.append({"instruction":add, "turn":{"status":"accepted", "turn_kind":"scene_edit", "instruction":add,
        "scene_edit":{"entities":[{"entity_id":"banana", "semantic_name":"banana", "category":"fruit"}],
            "relations":[], "operations":[{"operation":"add", "target":"banana"}]}}})
    replay = directory / "replay.json"
    replay.write_text(json.dumps(fixture, ensure_ascii=False), encoding="utf-8")
    common = ["--provider", "replay", "--planner", "recipe", "--replay-file", str(replay), "--output-dir", str(directory / "out"), "--session", "wheel-session", "--json"]
    first = json.loads(run("run", instruction, *common))
    assert first["run_status"] == "success" and first["scene_source"] == "generated"
    assert first["provider"] == "replay" and first["executed"] is False
    assert first["metrics"]["understanding_calls"] == 1
    assert first["metrics"]["skill_planning_calls"] == 0
    assert first["metrics"]["planner_used"] == "recipe"
    commands = json.loads(Path(first["artifacts"]["commands"]).read_text(encoding="utf-8"))
    scene = json.loads(Path(first["artifacts"]["scene_config"]).read_text(encoding="utf-8"))
    AtomicCommandsFile.model_validate(commands)
    Draft202012Validator(AtomicCommandsFile.model_json_schema()).validate(commands)
    assert (commands["scene_id"], commands["scene_version"]) == (scene["scene_id"],scene["scene_version"])
    parsed_scene = SceneConfig.model_validate(scene)
    Draft202012Validator(scene_schema).validate(scene)
    index = SceneIndex(parsed_scene)
    assert sum(index.semantic(o.object_id_in_scene).semantic_name == "apple" for o in index.semantic_objects()) == 2
    assert type(scene["scene_id"]) is int
    assert all(type(command["parameters"]["target"]) is int for command in commands["commands"]
               if command["skill_name"] in {"approach", "pick", "put"})
    assert index.robot_driver(1) is not None
    second = json.loads(run("run", instruction, *common))
    assert second["scene_source"] == "session" and second["scene_id"] == first["scene_id"]
    assert second["scene_version"] == first["scene_version"]
    assert second["run_status"] == "success" and second["request_id"] != first["request_id"]
    third = json.loads(run("run", plural, *common))
    assert third["run_status"] == "success" and "commands" not in third["artifacts"]
    query = json.loads(Path(third["artifacts"]["query_result"]).read_text(encoding="utf-8"))
    assert query["count"] == 2 and len(query["object_ids"]) == 2
    # No-reference additions use defaults only on initial scene creation;
    # existing sessions must supply a placement reference.
    add_options = list(common)
    add_options[add_options.index("--session") + 1] = "wheel-add"
    fourth = json.loads(run("run", add, *add_options))
    assert fourth["run_status"] == "success" and "commands" not in fourth["artifacts"]
    # A new session's first no-reference scene edit bootstraps its generated
    # scene at version 1. Version 2 is reserved for a subsequent edit in the
    # same session; this assertion must not depend on another session's state.
    assert fourth["scene_source"] == "generated" and fourth["scene_version"] == 1
    edited = json.loads(Path(fourth["artifacts"]["scene_config"]).read_text(encoding="utf-8"))
    index = SceneIndex(SceneConfig.model_validate(edited))
    assert sum(index.semantic(o.object_id_in_scene).semantic_name == "banana" for o in index.semantic_objects()) == 1
    print(json.dumps({"wheel_smoke":"passed", "installed_module":str(installed), "artifacts":str(directory),
                      "provider":"replay", "real_qwen_tested":False,"web_import_and_routes_tested":web_tested}, ensure_ascii=False))


if __name__ == "__main__":
    main()
