"""Capture the exact published Scene from an idle, isolated browser session.

Requires explicit session/task paths and browser ID. Never loads a scene or
clears uncertainty. A mismatch or refused lease is a failed evidence capture.
"""
import argparse
import json
from pathlib import Path

from robot_agent_brain.batch_service import ServiceBatchRunner
from robot_agent_brain.web.protocol import digest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task-dir", type=Path, required=True)
    parser.add_argument("--browser-id", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--agent-url", default="http://127.0.0.1:8503")
    parser.add_argument("--gateway-url", default="http://127.0.0.1:8096")
    parser.add_argument("--camera-id", type=int, help="Optional assertion against the session's bound camera")
    args = parser.parse_args()
    expected = json.loads((args.task_dir / "scene_config.json").read_text())
    report = json.loads((args.task_dir / "result.json").read_text())
    if report["run_status"] != "success":
        raise ValueError("capture_requires_successful_publication")
    state = json.loads((args.task_dir.parent / "session_state.json").read_text())
    camera_id = state.get("camera_id")
    if type(camera_id) is not int:
        raise ValueError("capture_bound_camera_missing")
    if args.camera_id is not None and args.camera_id != camera_id:
        raise ValueError("capture_bound_camera_mismatch")
    args.output_dir.mkdir(parents=True, exist_ok=False)
    runner = ServiceBatchRunner(agent_url=args.agent_url, gateway_url=args.gateway_url,
                               output_dir=args.output_dir, browser_id=args.browser_id)
    runner.client.headers.update({"X-WebEditor-Browser-ID": args.browser_id,
                                  "X-Brain-Session": args.task_dir.parent.name})
    try:
        health = runner._request("GET", args.agent_url + "/health").json()
        if health["tasks"]["active_task_id"] or health["tasks"]["queued"]:
            raise ValueError("capture_requires_idle_brain")
        if health.get("control_reason") != "execution_disabled":
            raise ValueError("capture_requires_isolated_plan_only_brain")
        world = runner._world(args.browser_id)
        if digest(world) != digest(expected):
            raise ValueError("published_scene_readback_mismatch")
        (args.output_dir / "scene.json").write_text(json.dumps(world, ensure_ascii=False, indent=2))
        lease = runner._request("POST", args.gateway_url + "/acquireSceneLease", json={
            "taskID": 0, "browserID": args.browser_id, "sceneDigest": digest(world),
            "scene_id": world["scene_id"], "scene_version": world["scene_version"],
            "scene_sub_version": world.get("scene_sub_version", 0),
        }).json()
        runner.client.headers["X-Brain-Lease"] = lease["leaseToken"]
        try:
            capture = runner._capture(args.browser_id, world, args.output_dir / "screenshot.png", camera_id)
            capture.update(task_id=args.task_dir.name, session_id=args.task_dir.parent.name,
                           published_digest_matches=True)
            (args.output_dir / "capture.json").write_text(json.dumps(capture, ensure_ascii=False, indent=2))
            print(json.dumps(capture, ensure_ascii=False))
        finally:
            runner._request("POST", args.gateway_url + "/releaseSceneLease", json={
                "browserID": args.browser_id, "leaseToken": lease["leaseToken"], "keepLocked": False})
    except Exception as error:
        (args.output_dir / "error.json").write_text(json.dumps({"error": str(error)}, ensure_ascii=False, indent=2))
        raise
    finally:
        runner.client.close()


if __name__ == "__main__":
    main()
