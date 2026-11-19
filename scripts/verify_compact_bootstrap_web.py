"""Five real empty browser sessions; no presets and no Control execution."""
import argparse
import json
import math
from pathlib import Path

from robot_agent_brain.batch_service import ServiceBatchRunner
from robot_agent_brain.config import BrainConfig
from robot_agent_brain.web.protocol import digest


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def components(obj):
    return {c["component_type"]: c["properties"] for c in obj["components"]}


def instances(scene, model_id):
    return [o for o in scene["objects"] if components(o).get("MetadataRef") ==
            {"type": "model", "path": f"$LIBRARY_SERVER/{model_id}"}]


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--runtime", type=Path, required=True)
    p.add_argument("--browser-id", required=True)
    p.add_argument("--label", default="c5")
    args = p.parse_args()
    config = BrainConfig.load(args.runtime / "brain.json")
    assert config.execution_enabled is False and config.understanding_wire_format == "compact_v1"
    root = args.runtime / args.label
    root.mkdir(exist_ok=False)
    runner = ServiceBatchRunner(agent_url="http://127.0.0.1:8503", gateway_url="http://127.0.0.1:8096",
                                output_dir=root, browser_id=args.browser_id, task_timeout=600)
    runner.client.headers["X-WebEditor-Browser-ID"] = args.browser_id
    rows = []
    try:
        for run in range(1, 6):
            directory = root / f"session-{run}"
            directory.mkdir()
            empty = {"scene_schema_version": 1, "scene_version": 1, "scene_id": 0,
                     "scene_name": "empty", "objects": []}
            activation = runner._activate(args.browser_id, empty)
            save(directory / "activation.json", activation)
            world = runner._load_empty(args.browser_id)
            save(directory / "initial_world.json", world)
            state = runner._request("GET", runner.agent_url + "/sessionState",
                                    params={"browser_id": args.browser_id}).json()
            save(directory / "initial_brain_state.json", state)
            assert world["scene_id"] == 0 and not world["objects"]
            assert state["scene_id"] in (None, 0), "brain_already_initialized"
            for turn, instruction in enumerate(("在桌面增加两个苹果和一个托盘", "把最左边的苹果绕世界Z轴旋转九十度"), 1):
                evidence = directory / f"turn-{turn}"
                evidence.mkdir()
                before = world
                save(evidence / "scene_before.json", before)
                (evidence / "instruction.txt").write_text(instruction)
                request_id, accepted = runner._start_task(activation["sessionID"], args.browser_id, instruction, before)
                save(evidence / "accepted.json", accepted)
                state, result = runner._wait_task(accepted["taskID"])
                save(evidence / "task_state.json", state)
                save(evidence / "task_result.json", result)
                world = runner._world(args.browser_id)
                save(evidence / "scene_after.json", world)
                runner._download_artifacts(result, evidence)
                checks = {"outcome": result.get("outcome") == "scene_updated", "no_execution": result.get("executed") is False,
                          "object_counts": len(instances(world, 1)) == 2 and len(instances(world, 17)) == 1}
                if turn == 1:
                    checks["bootstrap_version"] = world["scene_version"] == 1 and world["scene_id"] != 0
                    checks["no_invented_rotation"] = all(components(o)["Transform"]["quaternion_xyzw"] == [0, 0, 0, 1]
                                                         for o in instances(world, 1) + instances(world, 17))
                elif len(instances(before, 1)) == 2:
                    apples = sorted(instances(before, 1), key=lambda o: components(o)["Transform"]["position"][0])
                    target = apples[0]["object_id_in_scene"]
                    checks["unique_leftmost"] = components(apples[0])["Transform"]["position"][0] < components(apples[1])["Transform"]["position"][0]
                    old = {o["object_id_in_scene"]: o for o in before["objects"]}
                    new = {o["object_id_in_scene"]: o for o in world["objects"]}
                    checks["non_targets_unchanged"] = old.keys() == new.keys() and all(new[k] == v for k, v in old.items() if k != target)
                    t0, t1 = components(old[target])["Transform"], components(new[target])["Transform"]
                    checks["position_scale_parent_unchanged"] = all(t0.get(k) == t1.get(k) for k in ("position", "scale", "parent"))
                    q = t1["quaternion_xyzw"]
                    expected = [0, 0, math.sqrt(.5), math.sqrt(.5)]
                    checks["world_z_90"] = min(max(abs(a-sign*b) for a,b in zip(q,expected)) for sign in (1,-1)) < 1e-6
                    checks["one_version"] = world["scene_version"] == before["scene_version"] + 1
                try:
                    camera = result.get("camera_id") or activation.get("camera_id")
                    if camera is None:
                        current = runner._request("GET", runner.gateway_url + "/api/sessionState", params={"browser_id": args.browser_id}).json()
                        save(evidence / "session_state.json", current)
                        camera = current.get("camera_id")
                    assert camera is not None, "camera_not_bound"
                    capture = runner._capture(args.browser_id, world, evidence / "screenshot.png", camera)
                    checks["screenshot"] = capture.get("status") == "captured"
                except Exception as exc:
                    capture = {"status": "blocked", "reason": str(exc)}
                    checks["screenshot"] = False
                save(evidence / "screenshot_metadata.json", capture)
                row = {"run": run, "turn": turn, "session_id": activation["sessionID"], "task_id": accepted["taskID"],
                       "client_request_id": request_id, "checks": checks, "passed": all(checks.values()),
                       "digest": digest(world), "evidence": str(evidence)}
                rows.append(row)
                save(root / "audit.json", {"total": len(rows), "passed": sum(r["passed"] for r in rows), "rows": rows})
                print(json.dumps(row, ensure_ascii=False), flush=True)
                if result.get("outcome") != "scene_updated":
                    break
    finally:
        runner.client.close()


if __name__ == "__main__":
    main()
