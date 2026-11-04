import json
import base64
import pytest

from robot_agent_brain.batch_service import ServiceBatchRunner, _write_results_workbook, _RESULT_COLUMNS, _classify_batch_error


def test_capability_boundary_is_classified_as_expected_unsupported():
    status, outcome, error = _classify_batch_error(RuntimeError("http_422: web_platform_profile_unsupported"))
    assert (status, outcome) == ("passed", "unsupported")
    assert error["failure_class"] == "capability_unsupported"
    assert error["executed"] is False


def test_service_batch_preflight_rejects_missing_qwen_assets_or_running_task(tmp_path):
    runner = ServiceBatchRunner(agent_url="http://agent", gateway_url="http://gateway",
                                output_dir=tmp_path, screenshot_required=False)

    class Response:
        def __init__(self, value):
            self.value = value
        def json(self):
            return self.value

    cases = [
        ({"qwen": "unavailable", "asset_detail": {"matched": True}, "tasks": {}},
         "batch_qwen_unavailable"),
        ({"qwen": "ready", "asset_detail": {"matched": False}, "tasks": {}},
         "batch_assets_unavailable"),
        ({"qwen": "ready", "asset_detail": {"matched": True},
          "tasks": {"active_task_id": 9, "queued": 0}}, "batch_tasks_already_running"),
    ]
    for agent, expected in cases:
        runner._request = lambda method, url, agent=agent: Response(
            agent if url.endswith("/health") else {"protocol": "brain-web/2"})
        with pytest.raises(RuntimeError, match=expected):
            runner._health()


@pytest.mark.parametrize(
    ("runtime_revision", "expected_error"),
    [("sha256:actual", "batch_catalog_revision_mismatch"),
     (None, "batch_catalog_revision_unavailable")],
)
def test_service_batch_preflight_fails_closed_on_catalog_revision_drift(
    tmp_path, runtime_revision, expected_error
):
    """A compiled matrix must not run against a different/unknown OLS snapshot."""
    runner = ServiceBatchRunner(agent_url="http://agent", gateway_url="http://gateway",
                                output_dir=tmp_path, screenshot_required=False)
    runner.expected_catalog_revision = "sha256:expected"

    class Response:
        def __init__(self, value):
            self.value = value

        def json(self):
            return self.value

    agent = {"qwen": "ready", "asset_detail": {"matched": True},
             "tasks": {"active_task_id": None, "queued": 0}}
    if runtime_revision is not None:
        agent["asset_detail"]["catalog_revision"] = runtime_revision
    runner._request = lambda method, url, agent=agent: Response(
        agent if url.endswith("/health") else {"protocol": "brain-web/2"})
    with pytest.raises(RuntimeError, match=expected_error):
        runner._health()


def test_service_batch_preflight_records_matching_runtime_catalog_revision(tmp_path):
    runner = ServiceBatchRunner(agent_url="http://agent", gateway_url="http://gateway",
                                output_dir=tmp_path, screenshot_required=False)
    runner.expected_catalog_revision = runner_revision = "sha256:matching"

    class Response:
        def __init__(self, value):
            self.value = value

        def json(self):
            return self.value

    agent = {"qwen": "ready", "asset_detail": {"matched": True,
                                                   "catalog_revision": runner_revision},
             "tasks": {"active_task_id": None, "queued": 0}}
    runner._request = lambda method, url: Response(
        agent if url.endswith("/health") else {"protocol": "brain-web/2"})
    health = runner._health()
    assert health["agent"]["asset_detail"]["catalog_revision"] == runner.runtime_catalog_revision == runner_revision


def test_service_batch_rejects_mixed_catalog_revision_provenance(tmp_path):
    cases = tmp_path / "mixed_catalog_revision.json"
    cases.write_text(json.dumps({"sessions": [
        {"name": "v2", "instructions": ["one"], "catalog_revision": "sha256:expected"},
        {"name": "v1", "instructions": ["two"]},
    ]}), encoding="utf-8")
    runner = ServiceBatchRunner(agent_url="http://agent", gateway_url="http://gateway",
                                output_dir=tmp_path, screenshot_required=False)
    with pytest.raises(ValueError, match="batch_catalog_revision_missing"):
        runner.run(cases)


def test_service_batch_preflight_rejects_connected_browser_without_camera(tmp_path):
    runner = ServiceBatchRunner(agent_url="http://agent", gateway_url="http://gateway",
                                output_dir=tmp_path, screenshot_required=False)
    runner._health = lambda: {"agent": {}, "gateway": {
        "browser": {"connected": True, "browser_id": "browser-1"}}}
    runner._world = lambda browser_id: {"objects": []}
    with pytest.raises(RuntimeError, match="batch_browser_camera_unavailable"):
        runner._resolve_browser()


def test_explicit_browser_id_does_not_bypass_camera_preflight(tmp_path):
    runner = ServiceBatchRunner(agent_url="http://agent", gateway_url="http://gateway",
                                output_dir=tmp_path, browser_id="browser-1",
                                screenshot_required=False)
    runner._health = lambda: {"agent": {}, "gateway": {
        "browser": {"connected": True, "browser_id": "browser-1"}}}
    runner._world = lambda browser_id: {"objects": []}
    with pytest.raises(RuntimeError, match="batch_browser_camera_unavailable"):
        runner._resolve_browser()


def test_empty_bootstrap_can_select_connected_browser_before_camera_exists(tmp_path):
    runner = ServiceBatchRunner(agent_url="http://agent", gateway_url="http://gateway",
                                output_dir=tmp_path, browser_id="browser-1",
                                screenshot_required=True)
    runner._health = lambda: {"agent": {}, "gateway": {
        "browser": {"connected": True, "browser_id": "browser-1"}}}
    runner._world = lambda browser_id: {"objects": []}
    browser, _ = runner._resolve_browser(require_camera=False)
    assert browser == "browser-1"


def test_batch_preflights_all_preset_scene_documents_before_browser(tmp_path):
    scenes = tmp_path / "scenes"
    scenes.mkdir()
    valid = {"scene_schema_version": 1, "scene_id": 1, "scene_version": 1,
             "scene_sub_version": 0, "scene_name": "valid", "objects": []}
    (scenes / "valid.json").write_text(json.dumps(valid), encoding="utf-8")
    cases = tmp_path / "cases.json"
    cases.write_text(json.dumps({"sessions": [
        {"name": "first", "scene": "scenes/valid.json", "instructions": ["one"]},
        {"name": "later", "scene": "scenes/missing.json", "instructions": ["two"]},
    ]}), encoding="utf-8")
    runner = ServiceBatchRunner(agent_url="http://agent", gateway_url="http://gateway",
                                output_dir=tmp_path / "out", screenshot_required=False)
    called = {"resolve": False}
    runner._resolve_browser = lambda **kwargs: called.__setitem__("resolve", True)
    with pytest.raises(RuntimeError, match="batch_preset_scene_missing:2"):
        runner.run(cases)
    assert called["resolve"] is False


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

    runner._resolve_browser = lambda **kwargs: ("browser-1", {"agent": {}, "gateway": {}})

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


def test_batch_results_workbook_has_required_columns_and_screenshot_link(tmp_path):
    evidence = tmp_path / "sessions" / "s" / "turns" / "0001"
    evidence.mkdir(parents=True)
    (evidence / "screenshot.png").write_bytes(b"png")
    output = _write_results_workbook(tmp_path, [{
        "session": "s", "turn": 1, "instruction": "增加一个苹果",
        "status": "passed", "outcome": "scene_updated", "terminal": True,
        "executed": False, "evidence_directory": str(evidence),
        "screenshot": {"status": "captured", "camera_id": 5},
        "scene": {"scene_id": 1, "scene_version": 2, "scene_sub_version": 0,
                  "sceneDigest": "abc"}, "result": {"outcome": "scene_updated"},
    }])
    if output is None:
        pytest.skip("optional openpyxl dependency is not installed")
    import openpyxl
    workbook = openpyxl.load_workbook(output)
    sheet = workbook["results"]
    assert [cell.value for cell in sheet[1]][:3] == _RESULT_COLUMNS[:3]
    assert sheet.cell(2, 2).hyperlink is not None
    assert sheet.cell(2, 3).value
