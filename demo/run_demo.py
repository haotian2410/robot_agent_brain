"""Real Qwen demonstrations. Export plans/edit metadata, never execute a robot."""
import argparse
import json
import math
import os
from collections import Counter
from datetime import datetime
from pathlib import Path
import uuid

import httpx

from robot_agent_brain.application import BrainApplication
from robot_agent_brain.config import BrainConfig
from robot_agent_brain.models.qwen_http import QwenHTTPProvider
from robot_agent_brain.contracts.scene import SceneConfig
from robot_agent_brain.scene.component_access import SceneIndex
from robot_agent_brain.scene.scene_graph import world_transform


ROOT = Path(__file__).resolve().parent


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")


def verify(report, expected, previous_scene):
    errors = []
    def check(condition, message):
        if not condition:
            errors.append(message)
    check(report.run_status == "success", f"run_status={report.run_status}")
    for field in ("turn_kind", "scene_source"):
        check(getattr(report, field) == expected[field], field)
    check(report.executed is False, "Brain must not claim execution")
    check(report.metrics["understanding_calls"] == 1, "understanding_calls")
    check(report.metrics["skill_planning_calls"] == expected["skill_planning_calls"], "skill_planning_calls")
    artifacts = {name: json.loads(Path(path).read_text(encoding="utf-8"))
                 for name, path in report.artifacts.items() if path.endswith(".json")}
    scene = artifacts.get("scene_config")
    if report.run_status != "success":
        return errors, scene
    if "object_counts" in expected and scene:
        index = SceneIndex(SceneConfig.model_validate(scene))
        counts = Counter(index.semantic(o.object_id_in_scene).semantic_name for o in index.semantic_objects()
                         if index.semantic(o.object_id_in_scene).category != "surface")
        check(dict(counts) == expected["object_counts"], f"object_counts={dict(counts)}")
    if expected["turn_kind"] == "robot_task":
        commands = artifacts.get("commands", {})
        check(len(commands.get("commands", [])) >= expected["min_commands_count"], "min_commands_count")
        if scene:
            check((commands.get("scene_id"), commands.get("scene_version")) ==
                  (scene["scene_id"], scene["scene_version"]), "commands scene identity")
            if previous_scene:
                check(scene == previous_scene, "planning must not move scene objects")
        if "distance_m" in expected:
            distances = [c["parameters"]["distance_m"] for c in commands.get("commands", []) if "distance_m" in c["parameters"]]
            check(distances == [expected["distance_m"]], f"distances={distances}")
    else:
        check("commands" not in artifacts, "nonrobot turn must not publish commands")
    if "query_count" in expected:
        check(artifacts.get("query_result", {}).get("count") == expected["query_count"], "query_count")
    if "apple_delta_x" in expected and scene and previous_scene:
        current = SceneConfig.model_validate(scene)
        previous = SceneConfig.model_validate(previous_scene)
        index, before = SceneIndex(current), SceneIndex(previous)
        check(scene["scene_version"] == previous_scene["scene_version"] + 1, "one atomic edit version")
        check({o.object_id_in_scene for o in current.objects} == {o.object_id_in_scene for o in previous.objects},
              "edit preserves object identities")
        for obj in current.objects:
            identifier = obj.object_id_in_scene
            semantic = index.semantic(identifier)
            if semantic is None:
                check(obj == before.object(identifier), "nonsemantic components preserved")
                continue
            world, prior = world_transform(current, identifier), world_transform(previous, identifier)
            if semantic.semantic_name == "apple":
                check(math.isclose(world.position[0] - prior.position[0], expected["apple_delta_x"], abs_tol=1e-9), "apple x displacement")
                check(world.position[1:] == prior.position[1:], "apple y/z preserved")
                check(world.linear == prior.linear, "apple rotation/scale preserved")
            elif semantic.semantic_name == "banana":
                angle = math.radians(expected["banana_yaw_degrees"]) / 2
                check(all(math.isclose(a, b, abs_tol=1e-9) for a, b in zip(
                    world.to_local_properties().quaternion_xyzw, (0, 0, math.sin(angle), math.cos(angle)))), "banana world-Z rotation")
                check(world.position == prior.position, "banana position preserved")
            else:
                check(obj == before.object(identifier), "unmodified scene object preserved")
    return errors, scene


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", choices=["all", "robot_operation", "scene_edit"], default="all")
    parser.add_argument("--base-url", default="http://127.0.0.1:8080/v1")
    parser.add_argument("--model", help="Omit only when /models exposes exactly one model")
    parser.add_argument("--timeout", type=float, default=180)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "results")
    args = parser.parse_args()
    run_dir = args.output_dir.resolve() / (datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6])
    key = os.environ.get("ROBOT_BRAIN_API_KEY", "")
    # Direct connection avoids accidentally proxying a local Qwen service.
    with httpx.Client(trust_env=False, headers={"Authorization": f"Bearer {key}"} if key else {}) as client:
        response = client.get(args.base_url.rstrip("/") + "/models", timeout=10)
        response.raise_for_status()
        models = response.json()
        ids = [item["id"] for item in models.get("data", [])]
        if not args.model and len(ids) != 1:
            parser.error("Specify --model; /models did not return exactly one model")
        model = args.model or ids[0]
        save(run_dir / "service_models.json", models)
        summary = {"model": model, "base_url": args.base_url, "real_qwen_tested": False,
                   "robot_executed": False, "planner": "qwen", "cases": []}
        names = ["robot_operation", "scene_edit"] if args.case == "all" else [args.case]
        for name in names:
            cases = json.loads((ROOT / name / "instructions.json").read_text(encoding="utf-8"))
            provider = QwenHTTPProvider(args.base_url, model, api_key=key, timeout=args.timeout, client=client)
            app = BrainApplication(BrainConfig(provider="qwen", planner="qwen", model=model,
                base_url=args.base_url, timeout=args.timeout, api_key=key or None,
                output_dir=str(run_dir / name), debug=True, seed=0), provider=provider)
            previous_scene = None
            failed = False
            for case in cases:
                entry = {"demo": name, "case_id": case["id"], "instruction": case["instruction"]}
                if failed:
                    entry["status"] = "skipped"
                    entry["reason"] = "Previous turn failed; not substituting a fake response"
                else:
                    print(f"[{name}/{case['id']}] {case['instruction']}", flush=True)
                    report = app.handle(case["instruction"], session_id=name)
                    errors, scene = verify(report, case["expected"], previous_scene)
                    failed = bool(errors)
                    entry.update(status="failed" if failed else "passed", checks_failed=errors,
                        error=report.error.model_dump(mode="json") if report.error else None,
                        metrics=report.metrics, scene_id=report.scene_id, scene_version=report.scene_version,
                        artifacts={k: str(Path(v).relative_to(run_dir)) for k, v in report.artifacts.items()})
                    previous_scene = scene
                    summary["real_qwen_tested"] |= bool(provider.calls)
                    print(f"  {entry['status']} scene_version={report.scene_version} "
                          f"understanding={report.metrics['understanding_calls']} skill_planning={report.metrics['skill_planning_calls']}", flush=True)
                    if errors:
                        print(f"  {errors}; {report.error}", flush=True)
                summary["cases"].append(entry)
                save(run_dir / "summary.json", summary)
        summary["totals"] = dict(Counter(item["status"] for item in summary["cases"]))
        save(run_dir / "summary.json", summary)
        print(f"Summary: {run_dir / 'summary.json'}", flush=True)
        return 0 if all(item["status"] == "passed" for item in summary["cases"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
