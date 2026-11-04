"""Full-stack batch runner for AgentService + WebEditor Gateway.

This module deliberately stops at Brain's plan boundary.  It never talks to
Control and treats a missing or stale browser screenshot as evidence failure,
not as a successful test.
"""
from __future__ import annotations

import base64
import json
import re
import struct
import time
import uuid
from pathlib import Path
from urllib.parse import urljoin

import httpx

from .batch import load_batch_input
from .web.protocol import digest


_SAFE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,79}$")
_ARTIFACTS = {"scene_config", "scene_patch", "commands", "query_result"}

_RESULT_COLUMNS = [
    "用户指令", "真实浏览器场景截图", "系统返回的任务结果",
    "session", "difficulty", "category", "round", "taskID",
    "scene_id", "scene_version", "scene_sub_version", "sceneDigest",
    "camera_id", "outcome", "terminal", "executed", "error_code",
    "diagnostic_id", "artifacts", "evidence_directory",
    "asset_role_mapping", "parent_flow_id", "random_seed",
    "test_id", "parent_test_id", "coverage_tag", "expected_outcome", "expected_error_codes",
    "expected_scene_change", "assertion_profile", "assertion_result",
]


def _write_results_workbook(root: Path, rows: list[dict]) -> Path | None:
    """Write the reader-facing batch result workbook when the optional extra is installed.

    The service must keep producing JSON evidence even on minimal installations,
    so a missing ``openpyxl`` dependency is recorded instead of turning a
    completed batch into a transport failure.  ``pip install -e '.[batch]'``
    enables the workbook export.
    """
    try:
        from openpyxl import Workbook
        from openpyxl.styles import Alignment, Font, PatternFill
    except ImportError as exc:
        (root / "batch_test_results.error.json").write_text(
            json.dumps({"code": "batch_results_requires_openpyxl",
                        "message": "Install the optional batch extra: pip install -e '.[batch]'",
                        "detail": str(exc)}, ensure_ascii=False, indent=2), encoding="utf-8")
        return None

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "results"
    sheet.append(_RESULT_COLUMNS)
    header_fill = PatternFill("solid", fgColor="1F4E78")
    for cell in sheet[1]:
        cell.font = Font(color="FFFFFF", bold=True)
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    for row in rows:
        scene = row.get("scene") if isinstance(row.get("scene"), dict) else {}
        screenshot = row.get("screenshot") if isinstance(row.get("screenshot"), dict) else {}
        evidence = row.get("evidence_directory")
        if not evidence:
            session = row.get("output_name") or _safe(str(row.get("session", "session")), "session")
            turn = int(row.get("turn", 0) or 0)
            evidence = str(root / "sessions" / session / "turns" / f"{turn:04d}")
        screenshot_path = Path(evidence) / "screenshot.png"
        screenshot_value = ""
        if screenshot.get("status") == "captured" and screenshot_path.is_file():
            screenshot_value = str(screenshot_path)
        artifacts = row.get("artifacts", {})
        system_result = row.get("result") or row.get("error") or {
            "outcome": row.get("outcome"), "status": row.get("status"),
            "executed": row.get("executed", False),
        }
        values = [
            row.get("instruction", ""), screenshot_value,
            json.dumps(system_result, ensure_ascii=False, separators=(",", ":")),
            row.get("session", ""), row.get("difficulty", ""), row.get("category", ""),
            row.get("turn", ""), row.get("taskID", ""), scene.get("scene_id", ""),
            scene.get("scene_version", ""), scene.get("scene_sub_version", 0),
            scene.get("sceneDigest", ""), screenshot.get("camera_id", row.get("camera_id", "")),
            row.get("outcome", ""), row.get("terminal", ""), row.get("executed", False),
            row.get("error_code", ""), row.get("diagnostic_id", ""),
            json.dumps(artifacts, ensure_ascii=False), evidence,
            json.dumps(row.get("asset_role_mapping", {}), ensure_ascii=False),
            row.get("parent_flow_id", ""), row.get("random_seed", ""),
            row.get("test_id", ""), row.get("parent_test_id", ""), row.get("coverage_tag", ""),
            row.get("expected_outcome", ""), "|".join(row.get("expected_error_codes", []) or []),
            row.get("expected_scene_change", ""), row.get("assertion_profile", ""), row.get("assertion_result", "not_checked"),
        ]
        sheet.append(values)
        current = sheet.max_row
        if screenshot_value:
            cell = sheet.cell(current, 2)
            cell.hyperlink = Path(screenshot_value).as_uri() if Path(screenshot_value).is_absolute() else screenshot_value
            cell.style = "Hyperlink"
        sheet.cell(current, 3).alignment = Alignment(wrap_text=True, vertical="top")
    widths = {1: 34, 2: 42, 3: 60, 4: 24, 5: 10, 6: 24, 7: 8,
              8: 16, 9: 12, 10: 14, 11: 16, 12: 70, 13: 12, 14: 24,
              15: 10, 16: 10, 17: 30, 18: 24, 19: 36, 20: 50,
              21: 36, 22: 24, 23: 14}
    for index, width in widths.items():
        sheet.column_dimensions[chr(64 + index) if index <= 26 else "A"].width = width
    sheet.freeze_panes = "A2"
    sheet.auto_filter.ref = sheet.dimensions
    output = root / "batch_test_results.xlsx"
    workbook.save(output)
    return output


def _safe(value: str, fallback: str) -> str:
    value = re.sub(r"[^A-Za-z0-9_-]+", "-", value).strip("-")
    return value[:80] or fallback


def _classify_batch_error(error: Exception) -> tuple[str, str, dict]:
    """Classify expected capability boundaries without hiding real failures."""
    text = str(error)
    if "web_platform_profile_unsupported" in text:
        return "passed", "unsupported", {
            "code": "web_platform_profile_unsupported",
            "failure_class": "capability_unsupported",
            "message": "当前场景可展示，但该机器人平台暂不支持 Agent 任务规划或执行。",
            "executed": False,
        }
    return "failed", "failed", {"message": text, "executed": False}


def _check_expectation(session_spec, result: dict, state: dict) -> tuple[str, str | None]:
    expected = session_spec.expected_outcome
    if not expected:
        return "not_checked", None
    actual = result.get("outcome") or result.get("failure_class")
    if expected == "capability_unsupported":
        ok = result.get("failure_class") == "capability_unsupported" or result.get("error_code") == "web_platform_profile_unsupported"
    elif expected == "safe_rejection":
        ok = actual in {"failed", "rejected", "safe_rejection", "clarification_required"}
    elif expected == "query_answered":
        ok = actual in {"answered", "query_answered"}
    elif expected == "semantic_accepted":
        # ``semantic_accepted`` is a matrix-layer label.  The service may
        # expose the accepted turn as a scene update, answer, or an explicit
        # accepted outcome depending on the route; all are valid only when
        # the task did not fail and no payload error was returned.
        ok = actual in {"accepted", "scene_updated", "answered", "robot_setup_updated"}
    else:
        ok = actual == expected or (expected == "success" and actual not in {"failed", "clarification_required", "unsupported"})
    allowed = set(session_spec.expected_error_codes or [])
    if allowed:
        code = result.get("error_code") or (result.get("failure_reason") or {}).get("code")
        ok = ok and (code in allowed)
    return ("passed" if ok else "failed", None if ok else f"expected={expected},actual={actual}")


class ServiceBatchRunner:
    def __init__(self, *, agent_url: str, gateway_url: str, output_dir: str | Path,
                 browser_id: str | None = None, poll_interval: float = .25,
                 task_timeout: float = 300, screenshot_required: bool = True):
        self.agent_url = agent_url.rstrip("/")
        self.gateway_url = gateway_url.rstrip("/")
        self.output = Path(output_dir).resolve()
        self.browser_id = browser_id
        self.poll_interval = poll_interval
        self.task_timeout = task_timeout
        self.screenshot_required = screenshot_required
        self.client = httpx.Client(timeout=httpx.Timeout(20, connect=5), trust_env=False)

    def _request(self, method, url, **kwargs):
        response = self.client.request(method, url, **kwargs)
        if response.status_code >= 400:
            try:
                body = response.json()
            except ValueError:
                body = response.text[:1000]
            raise RuntimeError(f"http_{response.status_code}: {body}")
        return response

    def _health(self):
        agent = self._request("GET", self.agent_url + "/health").json()
        gateway = self._request("GET", self.gateway_url + "/api/health").json()
        if agent.get("qwen") not in {"ready", "unavailable"}:
            raise RuntimeError("batch_agent_health_invalid")
        if gateway.get("protocol") not in {None, "brain-web/2"}:
            raise RuntimeError("batch_gateway_protocol_invalid")
        return {"agent": agent, "gateway": gateway}

    def _resolve_browser(self):
        health = self._health()
        # AgentService can retain the last Brain binding after the browser has
        # disconnected.  That ID is useful for diagnostics, but it is not a
        # writable/live browser.  Gateway is the source of truth for whether
        # captureScene/updateWorld/session writes can succeed.
        gateway_browser = health["gateway"].get("browser") or {}
        connected = gateway_browser.get("connected") is True
        live_browser = gateway_browser.get("browser_id") if connected else None
        if self.browser_id:
            if not connected or live_browser != self.browser_id:
                raise RuntimeError("batch_browser_not_connected")
            return self.browser_id, health
        if not live_browser:
            stale = health["agent"].get("browser_id")
            if stale:
                raise RuntimeError("batch_browser_stale_binding")
            raise RuntimeError("batch_browser_not_bound")
        return live_browser, health

    def _world(self, browser_id):
        response = self._request("GET", self.gateway_url + "/getWorld", params={"browser_id": browser_id})
        world = response.json()
        if response.headers.get("X-World-Source") not in {None, "live"}:
            raise RuntimeError("batch_gateway_world_not_live")
        return world

    def _wait_world(self, browser_id, predicate, timeout=5.0):
        deadline = time.monotonic() + timeout
        last = None
        while time.monotonic() < deadline:
            last = self._world(browser_id)
            if predicate(last):
                return last
            time.sleep(.1)
        return last

    def _identity(self, world):
        return {
            "scene_id": world.get("scene_id", 0),
            "scene_version": world.get("scene_version", 0),
            "scene_sub_version": world.get("scene_sub_version", 0),
            "sceneDigest": digest(world),
        }

    def _load_preset(self, scene_path: Path, browser_id: str):
        world = json.loads(scene_path.read_text(encoding="utf-8"))
        self._request("POST", self.gateway_url + "/updateWorld", json=world,
                      headers={"X-Browser-ID": browser_id})
        current = self._wait_world(browser_id, lambda value: value.get("scene_id") == world.get("scene_id")
                                   and value.get("scene_name") == world.get("scene_name"))
        # WebEditor is authoritative for scene_version and may assign a fresh
        # version when setup loads a document.  Compare semantic scene identity,
        # not the source file's stale version/digest.
        if current.get("scene_id") != world.get("scene_id") or current.get("scene_name") != world.get("scene_name"):
            raise RuntimeError("batch_preset_scene_readback_mismatch")
        return current

    def _load_empty(self, browser_id: str):
        """Reset the bound browser to the protocol's legal empty document.

        A batch file with ``scene: null`` means an empty starting world, not
        "whatever world happened to be open in the browser".  The service
        preflight guarantees that no task is running before this setup write.
        """
        world = {"scene_schema_version": 1, "scene_version": 1,
                 "scene_id": 0, "scene_name": "empty", "objects": []}
        self._request("POST", self.gateway_url + "/updateWorld", json=world,
                      headers={"X-Browser-ID": browser_id})
        current = self._wait_world(browser_id, lambda value: value.get("scene_id") == 0
                                   and not value.get("objects"))
        if current.get("scene_id") != 0 or current.get("objects"):
            raise RuntimeError("batch_empty_scene_readback_mismatch")
        return current

    def _activate(self, browser_id, world):
        # The Gateway owns the browser/session binding.  Calling AgentService
        # directly would create a Brain row without updating Gateway's active
        # session, and the first lease would then be rejected as not granted.
        response = self._request("POST", self.gateway_url + "/sessions", json={
            "browserID": browser_id,
            "expectedScene": world, "allowActiveTask": False,
        })
        return response.json()

    def _start_task(self, session_id, browser_id, instruction, world):
        request_id = "batch-" + uuid.uuid4().hex
        payload = {
            "command": instruction, "scene": world,
            "scene_id": world.get("scene_id"), "scene_version": world.get("scene_version"),
            "scene_sub_version": world.get("scene_sub_version", 0),
            "sceneDigest": digest(world), "sessionID": session_id,
            "clientRequestID": request_id, "browserID": browser_id,
        }
        return request_id, self._request("POST", self.agent_url + "/startTask", json=payload).json()

    def _wait_task(self, task_id):
        deadline = time.monotonic() + self.task_timeout
        state = None
        while time.monotonic() < deadline:
            state = self._request("GET", self.agent_url + "/queryTaskState",
                                  params={"taskID": task_id}).json()
            if state.get("terminal") is True:
                result = self._request("GET", self.agent_url + "/queryTaskResult",
                                       params={"taskID": task_id}).json()
                return state, result
            time.sleep(self.poll_interval)
        raise RuntimeError(f"batch_task_timeout:{task_id}")

    def _capture(self, browser_id, world, destination, camera_id):
        kind = "rgb"
        for obj in world.get("objects", []):
            # Session responses and browser JSON may represent the same uint32 id
            # as either a number or a string.  Compare by its canonical text form
            # so an rgbd camera is not accidentally requested as rgb.
            if str(obj.get("object_id_in_scene")) != str(camera_id):
                continue
            for component in obj.get("components", []):
                if component.get("component_type") == "Camera":
                    camera_type = component.get("properties", {}).get("type")
                    if camera_type in {"rgb", "rgbd"}:
                        kind = camera_type
        params = {"id": camera_id, "type": kind, "browser_id": browser_id}
        response = self._request("GET", self.gateway_url + "/captureScene", params=params)
        value = response.json()
        expected_identity = self._identity(world)
        if (value.get("scene_id") != expected_identity["scene_id"]
                or value.get("scene_version") != expected_identity["scene_version"]
                or value.get("scene_sub_version", 0) != expected_identity["scene_sub_version"]
                or value.get("sceneDigest") != expected_identity["sceneDigest"]):
            raise RuntimeError("batch_screenshot_scene_digest_mismatch")
        # The browser frame names the camera as ``id`` (the Gateway request uses
        # ``?id=``); the Agent-facing session records call the same value
        # ``camera_id``.  Accept the wire spelling only, rather than requiring
        # a field the capture contract does not promise.
        if str(value.get("id")) != str(camera_id):
            raise RuntimeError("batch_screenshot_camera_mismatch")
        if value.get("image_encoding") != "png":
            raise RuntimeError("batch_screenshot_invalid_encoding")
        encoded = value.get("image_base64")
        if not isinstance(encoded, str):
            raise RuntimeError("batch_screenshot_missing_png")
        raw = base64.b64decode(encoded, validate=True)
        if (not raw.startswith(b"\x89PNG\r\n\x1a\n") or len(raw) < 24
                or raw[12:16] != b"IHDR"):
            raise RuntimeError("batch_screenshot_invalid_png")
        width, height = struct.unpack(">II", raw[16:24])
        if (value.get("width"), value.get("height")) != (width, height):
            raise RuntimeError("batch_screenshot_dimensions_mismatch")
        destination.write_bytes(raw)
        return {"status": "captured", "camera_id": camera_id, "type": kind,
                "scene_id": value.get("scene_id"), "scene_version": value.get("scene_version"),
                "scene_sub_version": value.get("scene_sub_version", 0),
                "sceneDigest": value.get("sceneDigest"), "width": value.get("width"),
                "height": value.get("height"), "encoding": value.get("image_encoding")}

    def _download_artifacts(self, result, turn_root):
        saved = {}
        artifacts = result.get("artifacts", []) if isinstance(result, dict) else []
        if isinstance(artifacts, dict):
            artifacts = [{"name": name, "url": url} for name, url in artifacts.items()]
        directory = turn_root / "artifacts"
        for item in artifacts:
            if not isinstance(item, dict) or item.get("name") not in _ARTIFACTS:
                continue
            name, url = item["name"], item.get("url")
            if not isinstance(url, str) or not url.startswith("/"):
                continue
            response = self._request("GET", urljoin(self.agent_url + "/", url.lstrip("/")))
            directory.mkdir(exist_ok=True)
            target = directory / (name + ".json")
            target.write_bytes(response.content)
            saved[name] = str(target)
        return saved

    def run(self, input_path):
        loaded = load_batch_input(input_path)
        if loaded["kind"] != "sessions":
            raise ValueError("service_batch_requires_sessions_json")
        browser_id, health = self._resolve_browser()
        root = self.output / ("batch-" + time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:8])
        root.mkdir(parents=True, exist_ok=False)
        (root / "input.json").write_text(Path(input_path).resolve().read_text(encoding="utf-8"), encoding="utf-8")
        results, session_summaries = [], []
        output_names = set()
        for index, session_spec in enumerate(loaded["sessions"], 1):
            name = session_spec.name or f"session-{index:03d}"
            session_id = "batch-" + _safe(name, f"session-{index:03d}") + "-" + uuid.uuid4().hex[:12]
            output_name = _safe(name, f"session-{index:03d}")
            # Different user-facing names can sanitize to the same directory (for
            # example ``a/b`` and ``a-b``). Keep every session's artifacts isolated
            # instead of allowing the second run to overwrite the first one.
            if output_name in output_names:
                suffix = f"-{index:03d}"
                output_name = (output_name[:80 - len(suffix)] + suffix).strip("-")
            output_names.add(output_name)
            session_root = root / "sessions" / output_name
            turns_root = session_root / "turns"
            turns_root.mkdir(parents=True, exist_ok=True)
            failed = False
            session_record = {"name": name, "outputName": output_name, "sessionID": session_id, "scene": session_spec.scene,
                              "difficulty": session_spec.difficulty,
                              "capabilities": list(session_spec.capabilities),
                              "flow_id": session_spec.flow_id, "parent_flow_id": session_spec.parent_flow_id,
                              "category": session_spec.category, "random_seed": session_spec.random_seed,
                              "asset_role_mapping": session_spec.asset_role_mapping,
                              "test_id": session_spec.test_id, "parent_test_id": session_spec.parent_test_id,
                              "coverage_tag": session_spec.coverage_tag, "expected_outcome": session_spec.expected_outcome,
                              "expected_error_codes": session_spec.expected_error_codes,
                              "expected_scene_change": session_spec.expected_scene_change,
                              "assertion_profile": session_spec.assertion_profile,
                              "variant_id": session_spec.variant_id, "equivalence_group": session_spec.equivalence_group,
                              "parent_variant_id": session_spec.parent_variant_id,
                              "fixture_id": session_spec.fixture_id, "asset_seed": session_spec.asset_seed,
                              "parent_run_id": getattr(session_spec, "parent_run_id", None),
                              "parent_scene_path": getattr(session_spec, "parent_scene_path", None),
                              "parent_scene_digest": getattr(session_spec, "parent_scene_digest", None),
                              "baseline_digest": getattr(session_spec, "baseline_digest", None),
                              "role_bindings": getattr(session_spec, "role_bindings", {}) or {},
                              "browserID": browser_id, "turns": len(session_spec.instructions)}
            (session_root / "session.json").write_text(json.dumps(session_record, ensure_ascii=False, indent=2), encoding="utf-8")

            def write_session_summary(status, error=None):
                rows = [item for item in results if item.get("session") == name]
                value = {"name": name, "outputName": output_name,
                         "sessionID": session_record.get("sessionID"),
                         "difficulty": session_spec.difficulty,
                         "capabilities": list(session_spec.capabilities),
                         "flow_id": session_spec.flow_id, "parent_flow_id": session_spec.parent_flow_id,
                         "category": session_spec.category, "random_seed": session_spec.random_seed,
                         "asset_role_mapping": session_spec.asset_role_mapping,
                         "test_id": session_spec.test_id, "parent_test_id": session_spec.parent_test_id,
                         "coverage_tag": session_spec.coverage_tag, "expected_outcome": session_spec.expected_outcome,
                         "expected_error_codes": session_spec.expected_error_codes,
                         "expected_scene_change": session_spec.expected_scene_change,
                         "assertion_profile": session_spec.assertion_profile,
                         "variant_id": session_spec.variant_id, "equivalence_group": session_spec.equivalence_group,
                         "parent_variant_id": session_spec.parent_variant_id,
                         "fixture_id": session_spec.fixture_id, "asset_seed": session_spec.asset_seed,
                         "parent_run_id": getattr(session_spec, "parent_run_id", None),
                         "parent_scene_path": getattr(session_spec, "parent_scene_path", None),
                         "parent_scene_digest": getattr(session_spec, "parent_scene_digest", None),
                         "baseline_digest": getattr(session_spec, "baseline_digest", None),
                         "role_bindings": getattr(session_spec, "role_bindings", {}) or {},
                         "browserID": browser_id, "status": status, "turns": rows}
                if error is not None:
                    value["error"] = error
                (session_root / "session_summary.json").write_text(
                    json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
                return value

            try:
                # Establish the Gateway/Brain session before touching the browser world.  The
                # browser is a shared live surface, while a batch session owns its own frozen
                # original and conversation.  Loading the next session's scene first would
                # mutate the previous session's setup snapshot and, on a real Gateway, could be
                # rejected as a scene switch belonging to the old conversation.  Passing the
                # intended document to /sessions lets the Gateway perform the transition while
                # the current session is still in setup; the subsequent updateWorld is then
                # scoped to the newly activated session.
                if session_spec.scene:
                    scene_path = (Path(input_path).resolve().parent / session_spec.scene).resolve()
                    if not scene_path.is_file():
                        raise FileNotFoundError(str(scene_path))
                    requested_world = json.loads(scene_path.read_text(encoding="utf-8"))
                else:
                    requested_world = {"scene_schema_version": 1, "scene_version": 1,
                                       "scene_id": 0, "scene_name": "empty", "objects": []}
                activation = self._activate(browser_id, requested_world)
                session_id = activation["sessionID"]
                session_record["sessionID"] = session_id
                (session_root / "session.json").write_text(json.dumps(session_record, ensure_ascii=False, indent=2), encoding="utf-8")
                # Only after activation may the shared browser be changed.  This is also the
                # point at which the Gateway assigns its authoritative scene version/digest.
                world = (self._load_preset(scene_path, browser_id)
                         if session_spec.scene else self._load_empty(browser_id))
                camera_id = activation.get("camera_id")
                (session_root / "original_scene.json").write_text(json.dumps(world, ensure_ascii=False, indent=2), encoding="utf-8")
                for turn_index, instruction in enumerate(session_spec.instructions, 1):
                    turn_root = turns_root / f"{turn_index:04d}"
                    turn_root.mkdir()
                    (turn_root / "instruction.txt").write_text(instruction, encoding="utf-8")
                    if failed:
                        result = {"status": "skipped", "reason": "session dependency failed"}
                        # A skipped turn is still a turn in the user-authored sequence.  Keep the
                        # same scene/screenshot evidence shape as executed turns so a report can
                        # distinguish "not attempted because the session failed" from "no
                        # evidence was collected" and never imply that the scene was changed.
                        (turn_root / "task_result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
                        (turn_root / "reply.txt").write_text("", encoding="utf-8")
                        try:
                            current = self._world(browser_id)
                            identity = self._identity(current)
                            (turn_root / "scene.json").write_text(json.dumps(current, ensure_ascii=False, indent=2), encoding="utf-8")
                            (turn_root / "scene_identity.json").write_text(json.dumps(identity, ensure_ascii=False, indent=2), encoding="utf-8")
                            screenshot = {"status": "blocked", "reason": "session_dependency_failed"}
                            if camera_id is not None:
                                try:
                                    screenshot = self._capture(browser_id, current, turn_root / "screenshot.png", camera_id)
                                except Exception as exc:
                                    screenshot = {"status": "blocked", "reason": str(exc)}
                            (turn_root / "screenshot_metadata.json").write_text(
                                json.dumps(screenshot, ensure_ascii=False, indent=2), encoding="utf-8")
                        except Exception as exc:
                            (turn_root / "scene_identity.json").write_text(
                                json.dumps({"status": "blocked", "reason": str(exc)}, ensure_ascii=False, indent=2),
                                encoding="utf-8")
                        results.append({"session": name, "output_name": output_name,
                                        "difficulty": session_spec.difficulty,
                                        "category": session_spec.category,
                                        "turn": turn_index, **result})
                        continue
                    try:
                        request_id, started = self._start_task(session_id, browser_id, instruction, world)
                        state, result = self._wait_task(started["taskID"])
                        current = self._world(browser_id)
                        camera_id = result.get("camera_id") or camera_id
                        identity = self._identity(current)
                        (turn_root / "task_request.json").write_text(json.dumps({"clientRequestID": request_id, "taskID": started["taskID"], "instruction": instruction}, ensure_ascii=False, indent=2), encoding="utf-8")
                        (turn_root / "task_state.json").write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
                        (turn_root / "task_result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
                        (turn_root / "reply.txt").write_text(str(result.get("reply", "")), encoding="utf-8")
                        saved_artifacts = self._download_artifacts(result, turn_root)
                        (turn_root / "scene.json").write_text(json.dumps(current, ensure_ascii=False, indent=2), encoding="utf-8")
                        (turn_root / "scene_identity.json").write_text(json.dumps(identity, ensure_ascii=False, indent=2), encoding="utf-8")
                        screenshot = {"status": "blocked", "reason": "camera_not_bound"}
                        if camera_id is not None:
                            try:
                                screenshot = self._capture(browser_id, current, turn_root / "screenshot.png", camera_id)
                            except Exception as exc:
                                screenshot = {"status": "blocked", "reason": str(exc)}
                        (turn_root / "screenshot_metadata.json").write_text(json.dumps(screenshot, ensure_ascii=False, indent=2), encoding="utf-8")
                        if screenshot.get("status") != "captured" and not self.screenshot_required:
                            screenshot = {**screenshot, "status": "skipped"}
                        outcome = result.get("outcome", "failed")
                        assertion_result, assertion_error = _check_expectation(session_spec, result, state)
                        screenshot_ok = screenshot.get("status") == "captured" or not self.screenshot_required
                        # A safe rejection or a correct clarification is a
                        # passing matrix result when it matches the row's
                        # expected outcome.  The old implementation rejected
                        # every ``outcome=failed`` before consulting the
                        # expectation, making T17/T18 impossible to pass.
                        semantic_ok = (assertion_result == "passed" if session_spec.expected_outcome
                                       else outcome not in {"failed"})
                        ok = bool(state.get("terminal")) and semantic_ok and screenshot_ok
                        if assertion_result == "failed":
                            ok = False
                        if result.get("executed", False) is not False:
                            ok = False
                        row_status = "passed" if ok else ("blocked" if screenshot.get("status") != "captured" and self.screenshot_required else "failed")
                        row = {"session": name, "difficulty": session_spec.difficulty,
                               "capabilities": list(session_spec.capabilities),
                               "category": session_spec.category, "parent_flow_id": session_spec.parent_flow_id,
                               "output_name": output_name,
                               "random_seed": session_spec.random_seed,
                               "asset_role_mapping": session_spec.asset_role_mapping,
                               "turn": turn_index, "instruction": instruction,
                               "taskID": started["taskID"], "status": row_status,
                               "outcome": outcome, "terminal": state.get("terminal", False),
                               "executed": result.get("executed", False),
                               "scene": identity, "screenshot": screenshot,
                               "artifacts": saved_artifacts, "result": result,
                               "evidence_directory": str(turn_root),
                               "test_id": session_spec.test_id, "parent_test_id": session_spec.parent_test_id,
                               "coverage_tag": session_spec.coverage_tag, "expected_outcome": session_spec.expected_outcome,
                               "expected_error_codes": session_spec.expected_error_codes,
                               "expected_scene_change": session_spec.expected_scene_change,
                               "assertion_profile": session_spec.assertion_profile,
                               "assertion_result": assertion_result,
                               "variant_id": session_spec.variant_id,
                               "equivalence_group": session_spec.equivalence_group,
                               "parent_variant_id": session_spec.parent_variant_id,
                               "fixture_id": session_spec.fixture_id,
                               "asset_seed": session_spec.asset_seed,
                               "parent_run_id": getattr(session_spec, "parent_run_id", None),
                               "parent_scene_path": getattr(session_spec, "parent_scene_path", None),
                               "parent_scene_digest": getattr(session_spec, "parent_scene_digest", None),
                               "baseline_digest": getattr(session_spec, "baseline_digest", None),
                               "role_bindings": getattr(session_spec, "role_bindings", {}) or {}}
                        if assertion_error:
                            row["assertion_error"] = assertion_error
                        results.append(row)
                        if not ok:
                            failed = True
                        world = current
                    except Exception as exc:
                        row_status, row_outcome, row_error = _classify_batch_error(exc)
                        failed = failed or row_status == "failed"
                        row = {"session": name, "turn": turn_index, "instruction": instruction,
                               "status": row_status, "outcome": row_outcome, "error": row_error,
                               "failure_class": row_error.get("failure_class")}
                        (turn_root / "error.json").write_text(json.dumps(row, ensure_ascii=False, indent=2), encoding="utf-8")
                        (turn_root / "task_result.json").write_text(json.dumps({"outcome": row_outcome, "executed": False,
                            "failure_class": row_error.get("failure_class"), "error": row_error}, ensure_ascii=False, indent=2), encoding="utf-8")
                        # Preserve the post-failure scene evidence whenever the browser is still
                        # reachable.  A transport failure must never silently discard the reply
                        # context or make a stale screenshot look current.
                        try:
                            current = self._world(browser_id)
                            identity = self._identity(current)
                            (turn_root / "scene.json").write_text(json.dumps(current, ensure_ascii=False, indent=2), encoding="utf-8")
                            (turn_root / "scene_identity.json").write_text(json.dumps(identity, ensure_ascii=False, indent=2), encoding="utf-8")
                        except Exception as snapshot_exc:
                            row["scene_snapshot_error"] = str(snapshot_exc)
                        results.append(row)
            except Exception as exc:
                failed = True
                results.append({"session": name, "output_name": output_name,
                                "difficulty": session_spec.difficulty,
                                "category": session_spec.category,
                                "turn": 0, "status": "failed", "error": str(exc)})
                write_session_summary("failed", str(exc))
                session_summaries.append({"session": name, "sessionID": session_record.get("sessionID"),
                                          "status": "failed", "error": str(exc)})
                continue
            session_status = "failed" if failed else "passed"
            write_session_summary(session_status)
            session_summaries.append({"session": name, "sessionID": session_record.get("sessionID"),
                                      "status": session_status})
        summary = {"transport": "service", "browserID": browser_id, "health": health,
                   "sessions": session_summaries, "turns": results,
                   "totals": {status: sum(item.get("status") == status for item in results)
                              for status in ("passed", "failed", "blocked", "skipped")}}
        (root / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        lines = ["# Batch test summary", "", f"Browser: `{browser_id}`", ""]
        for item in results:
            lines.append(f"- {item['session']} / turn {item['turn']}: **{item['status']}** — {item.get('instruction', '')}")
        (root / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
        _write_results_workbook(root, results)
        return summary, root
