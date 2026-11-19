"""Read-only differential check against the pre-extraction tracked validator."""
import json
import subprocess
import sys
import types
from pathlib import Path

from pydantic import ValidationError
from robot_agent_brain.contracts.turn import SceneEditIntent


def main():
    source = subprocess.check_output(["git", "show", "HEAD:src/robot_agent_brain/contracts/turn.py"], text=True)
    module = types.ModuleType("robot_agent_brain.contracts._baseline_turn")
    sys.modules[module.__name__] = module
    exec(compile(source, "<baseline-turn>", "exec"), module.__dict__)
    old = module.SceneEditIntent
    seeds = [dict(operation=op, target="apple") for op in
             ("add", "remove", "replace", "translate", "rotate", "orient", "move_relative", "update_properties", "update", "scale")]
    seeds += [dict(operation="rotate", target="apple", axis="z", angle_deg=90),
              dict(operation="scale", target="apple", scale_mode="multiply", scale_xyz=[1.1]*3),
              dict(operation="add", target="apple", relation="on", reference="table"),
              dict(operation="translate", target="apple", direction="right", distance_m=.01)]
    values = [None, 0, "any", "center", "right", "z", "banana", "on", "table", "object_local",
              "upright", "multiply", "enlarge", "small", [1.1]*3, {}, {"color": "blue"}, {"position_hint": "center"}]
    cases = seeds + [{**seed, field: value} for seed in seeds for field in SceneEditIntent.model_fields
                     if field not in {"operation", "target"} for value in values]
    def result(cls, data):
        try:
            return cls.model_validate(data).model_dump(mode="json")
        except ValidationError as error:
            return [(e["type"], e["loc"], e["msg"]) for e in error.errors()]
        except Exception as error:
            return {"exception": type(error).__name__, "message": str(error)}
    differences = [{"input": data, "before": result(old, data), "after": result(SceneEditIntent, data)}
                   for data in cases if result(old, data) != result(SceneEditIntent, data)]
    report = {"cases": len(cases), "differences": differences,
              "full_json_schema_unchanged": old.model_json_schema() == SceneEditIntent.model_json_schema()}
    Path(sys.argv[1]).write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps({k: v if k != "differences" else len(v) for k, v in report.items()}))
    assert not differences and report["full_json_schema_unchanged"]


if __name__ == "__main__":
    main()
