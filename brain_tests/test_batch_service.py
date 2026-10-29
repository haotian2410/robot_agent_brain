import json
import base64

from robot_agent_brain.batch_service import ServiceBatchRunner


def test_service_batch_activates_each_session_before_loading_its_scene(tmp_path):
    """A shared browser must not be loaded with session B's scene while A is active."""
    scenes = tmp_path / "scenes"
    scenes.mkdir()
    first = {"scene_schema_version": 1, "scene_version": 1, "scene_id": 11,
             "scene_name": "first", "objects": []}
    second = {"scene_schema_version": 1, "scene_version": 1, "scene_id": 12,
              "scene_name": "second", "objects": []}
    (scenes / "first.json").write_text(json.dumps(first), encoding="utf-8")
    (scenes / "second.json").write_text(json.dumps(second), encoding="utf-8")
    cases = tmp_path / "cases.json"
    cases.write_text(json.dumps({"sessions": [
        {"name": "a", "scene": "scenes/first.json", "instructions": ["one"]},
        {"name": "b", "scene": "scenes/second.json", "instructions": ["two"]},
    ]}), encoding="utf-8")

    runner = ServiceBatchRunner(agent_url="http://127.0.0.1:8500",
                                gateway_url="http://127.0.0.1:8099",
                                output_dir=tmp_path / "out",
                                screenshot_required=False)
    calls = []
    active = {"world": None, "session": 0}

    runner._resolve_browser = lambda: ("browser-1", {"agent": {}, "gateway": {}})

    def activate(browser_id, world):
        calls.append(("activate", world["scene_id"]))
        active["session"] += 1
        return {"sessionID": f"session-{active['session']}", "camera_id": None}

    runner._activate = activate

    def load_preset(scene_path, browser_id):
        world = json.loads(scene_path.read_text(encoding="utf-8"))
        calls.append(("load", world["scene_id"]))
        active["world"] = world
        return world

    runner._load_preset = load_preset
    runner._start_task = lambda session_id, browser_id, instruction, world: (
        calls.append(("task", session_id, world["scene_id"])) or ("request", {"taskID": len(calls)}))
    runner._wait_task = lambda task_id: ({"terminal": True}, {
        "outcome": "answered", "executed": False, "reply": "ok", "artifacts": []})
    runner._world = lambda browser_id: active["world"]
    runner._download_artifacts = lambda result, turn_root: {}

    summary, root = runner.run(cases)
    assert summary["totals"] == {"passed": 2, "failed": 0, "blocked": 0, "skipped": 0}
    assert (root / "sessions" / "a" / "session_summary.json").is_file()
    assert (root / "sessions" / "b" / "session_summary.json").is_file()
    assert calls[:4] == [
        ("activate", 11), ("load", 11), ("task", "session-1", 11),
        ("activate", 12),
    ]
    assert calls[4:] == [("load", 12), ("task", "session-2", 12)]


def test_service_batch_capture_uses_rgbd_and_validates_wire_identity(tmp_path):
    world = {"scene_schema_version": 1, "scene_version": 1, "scene_id": 11,
             "scene_name": "sorting", "objects": [{
                 "object_id_in_scene": 5, "object_name_in_scene": "camera",
                 "components": [{"component_type": "Camera", "properties": {
                     "type": "rgbd", "resolution": [2, 1]}}]}]}
    # A minimal PNG header is sufficient for the batch runner's framing check;
    # the Gateway itself performs full chunk/CRC validation.
    png = b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\x0dIHDR" + (2).to_bytes(4, "big") + (1).to_bytes(4, "big")

    class Response:
        def json(self):
            from robot_agent_brain.web.protocol import digest
            return {"id": 5, "scene_id": 11, "scene_version": 1, "scene_sub_version": 0,
                    "sceneDigest": digest(world), "width": 2, "height": 1,
                    "image_encoding": "png", "image_base64": base64.b64encode(png).decode()}

    runner = ServiceBatchRunner(agent_url="http://127.0.0.1:8500",
                                gateway_url="http://127.0.0.1:8099", output_dir=tmp_path)
    seen = {}
    runner._request = lambda method, url, **kwargs: seen.update(kwargs) or Response()
    destination = tmp_path / "frame.png"
    metadata = runner._capture("browser-1", world, destination, "5")
    assert seen["params"]["type"] == "rgbd"
    assert metadata["status"] == "captured"
    assert destination.read_bytes() == png
