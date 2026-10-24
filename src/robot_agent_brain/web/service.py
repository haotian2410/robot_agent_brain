"""Loopback-only persistent Agent service. One worker, no Control dispatch."""
import asyncio
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import quote, urlsplit

import httpx
from aiohttp import web
from pydantic import ValidationError
from ..application import BrainApplication
from ..config import BrainConfig
from ..scene.component_access import SceneIndex
from ..scene.component_reference_registry import ComponentReferenceRegistry
from .assets import check_ols
from .gateway import GatewayScenePlatformAdapter, durable_json
from .protocol import PROTOCOL_VERSION, StartTask, SessionRequest, digest, loopback_url, validate_web_scene
from .task_store import TaskStore


class AgentService:
    # §5.3 keeps this reading inside the Gateway's three seconds, but an OLS catalog check walks every
    # model, robot and scene (~55 reads plus a digest each).  The verdict changes when the library
    # changes, not every five seconds, so a health reading reuses the last one for a while.
    ASSET_CHECK_TTL_SECONDS = 30.0

    def __init__(self, config, *, gateway_url="http://127.0.0.1:8099", ols_url="http://127.0.0.1:8000",
                 joint_inventory=None, camera_id=5, provider=None, platform_factory=None):
        if config.scene_id_bits != 32:
            raise ValueError("web_uint32_configuration_required")
        loopback_url(config.base_url)
        self.gateway_url, self.ols_url = loopback_url(gateway_url), loopback_url(ols_url)
        self.config, self.camera_id = config, camera_id
        self.output = Path(config.output_dir).resolve()
        self.joints = json.loads(Path(joint_inventory).read_text(encoding="utf-8")) if joint_inventory else None
        if config.asset_library_root and self.joints is None:
            raise ValueError("robot_joint_inventory_required")
        self.references = ComponentReferenceRegistry(config.component_reference_rules)
        self.tasks = TaskStore(self.output / "agent_tasks.sqlite3")
        self.camera_bindings = {}
        self.binding = None
        self.platform_override = platform_factory
        self.app = BrainApplication(config, provider=provider, platform_factory=self.platform)
        self.queue = asyncio.Queue()
        self.mutex = asyncio.Lock()
        self.worker = None
        self.last_health = {}
        self.assets_check = None
        self.assets_refreshing = False
        self.assets_lock = threading.Lock()
        # A fresh httpx.Client costs about 0.3 s here (certificate loading), and the legs build them
        # concurrently on every reading -- which is how a ready service overran the Gateway's three
        # seconds and read as unreachable.  One shared client keeps /health in milliseconds.
        self.probe_client = httpx.Client(timeout=httpx.Timeout(1.0, connect=0.5), trust_env=False)
        # The catalog walk runs on its own thread, so it must not sit in the same connection pool as
        # the three legs a health reading waits on -- ~55 queued reads there otherwise stretch a
        # concurrent /health past the Gateway's three seconds, which is the very form §5.3 forbids.
        self.catalog_client = httpx.Client(timeout=httpx.Timeout(1.0, connect=0.5), trust_env=False)

    def platform(self):
        if self.binding is None:
            raise ValueError("session_binding_required")
        if self.platform_override:
            return self.platform_override(self.binding)
        return GatewayScenePlatformAdapter(self.gateway_url, self.binding["browser"],
            camera_id=self.camera_bindings.get(self.binding["id"], self.camera_id),
            session_id=self.binding["id"],
            joint_inventory=self.joints, reference_registry=self.references,
            journal_dir=self.output / self.binding["id"] / "gateway_transactions")

    def _bind(self, session_id):
        self.binding = self.tasks.binding(session_id)
        session = self.app.get_session(session_id)
        if (session.platform.browser_id != self.binding["browser"]
                or getattr(session.platform, "session_id", None) != self.binding["id"]):
            session.platform = self.platform()
        return session

    def validate_scene(self, scene, session=None):
        scene = validate_web_scene(scene, self.joints, self.references)
        # A browser may intentionally start a fresh conversation on the protocol's empty
        # document (scene_id=0, no objects).  This is a bootstrap request, not an imported
        # platform scene: Brain will create the configured UR5e/table template in app.handle and
        # commit it through the held Gateway lease.  Do not reject it as an unsupported profile.
        if scene.scene_id == 0 and not scene.objects:
            return scene
        if session is not None and session.scene is not None:
            return scene
        # This release imports UR5e only. Dual scenes remain display-only.
        if self.app.bootstrapper.template_scene is not None:
            template_scene = self.app.bootstrapper.template_scene
            manifest = self.config.scene_platform_object_ids
            if self.config.editor_scene_manifests:
                manifest = self.config.editor_scene_manifests.get(scene.scene_name)
                if manifest is None:
                    raise ValueError("web_platform_profile_unsupported")
                index = json.loads((Path(self.config.asset_library_root) / "scenes/scene_index.json").read_text(encoding="utf-8"))
                item = next(i for i in index if i["name"] == scene.scene_name)
                template_scene = self.app.codec.load(Path(self.config.asset_library_root) / "scenes" / str(item["id"]) / (item["name"] + ".json"))
            template = SceneIndex(template_scene)
            actual = SceneIndex(scene)
            for identifier in manifest or []:
                if {c.component_type for c in actual.object(identifier).components} != {c.component_type for c in template.object(identifier).components}:
                    raise ValueError("web_platform_profile_unsupported")
                if actual.metadata_ref_properties(identifier) != template.metadata_ref_properties(identifier):
                    raise ValueError("web_platform_profile_unsupported")
                driver = template.robot_driver(identifier)
                if driver and (actual.robot_driver(identifier) is None or
                    actual.robot_driver(identifier).deployment_configuration() != driver.deployment_configuration()):
                    raise ValueError("web_platform_profile_unsupported")
        return scene

    def activate(self, request):
        # No checkpoint writes or browser writes on activation. Live validation
        # occurs in the task worker; a restarted uncertain binding stays blocked.
        identifier = self.tasks.activate(request.browserID, request.sessionID,
                                         allow_active_task=request.allowActiveTask)
        if request.camera_id is not None:
            self.camera_bindings[identifier] = request.camera_id
        session = self._bind(identifier)
        if request.camera_id is not None:
            if session.camera_id is not None and session.camera_id != request.camera_id:
                raise ValueError("camera_binding_immutable")
            session.camera_id = request.camera_id
            self.app._save_session(identifier)
        return {"sessionID":identifier,"browserID":request.browserID,
                "camera_id":getattr(session, "camera_id", None),
                "session_phase":getattr(session, "session_phase", "setup"),"active":True}

    def execute(self, identifier):
        record = self.tasks.get(identifier)
        request = StartTask.model_validate(record["payload"])
        self.tasks.update(identifier, "进行中")
        session = None
        platform = None
        result = None
        uncertain = False
        try:
            session = self._bind(request.sessionID)
            if request.sessionID in self.camera_bindings:
                session.camera_id = self.camera_bindings[request.sessionID]
            platform = session.platform
            scene = self.validate_scene(request.scene, session)
            platform.receipts = []
            platform.capabilities()
            if self.config.asset_library_root:
                with httpx.Client(timeout=10, trust_env=False) as client:
                    check_ols(client, self.ols_url, self.config.asset_library_root)
            platform.acquire_lease(identifier, scene)
            if scene.objects:
                manifest = session.platform_object_ids if session.scene is not None else (
                    self.config.editor_scene_manifests.get(scene.scene_name) if self.config.editor_scene_manifests else self.config.scene_platform_object_ids)
                self.app.accept_browser_scene(request.sessionID, scene, platform_object_ids=manifest)
            # An empty browser document has no platform manifest to accept.  The application
            # bootstrap path below owns creation of the initial scene and will publish it through
            # the same lease; accepting it here would incorrectly require table/robot ids.
            session.session_phase = "agent_owned"
            report = self.app.handle(request.command, session_id=request.sessionID)
            record_path = self.output / request.sessionID / report.request_id / "request_record.json"
            turn_record = json.loads(record_path.read_text(encoding="utf-8"))
            if turn_record.get("id_remap"):
                platform.remap_camera(turn_record["id_remap"])
            result = self.result(report, identifier)
            # Even non-mutating plans must still refer to the live editor state.
            # A scene edit may have been committed during this task.  Compare the final
            # result with the browser's current world, not the lease's initial snapshot;
            # otherwise a successful generated-scene commit is reported as scene_changed.
            if session.scene is not None and digest(platform.read_live(lease_snapshot=False)) != digest(session.scene):
                session.sync_state = "unknown"
                raise ValueError("gateway_scene_changed_during_task")
            result["sceneDigest"] = digest(session.scene) if session.scene else None
            result["commitReceipts"] = list(platform.receipts)
            uncertain = session.sync_state == "unknown"
        except Exception as exc:
            uncertain = (session is not None and session.sync_state == "unknown") or (platform is not None and platform.lease_uncertain)
            result = {"taskID":identifier,"sessionID":request.sessionID,"outcome":"failed", "executed":False,
                "reply":str(exc),"error":{"code":str(exc).split(":",1)[0],"message":str(exc)}}
        finally:
            if platform is not None:
                try:
                    platform.release_lease(uncertain=uncertain)
                except Exception:
                    uncertain = True
                    result = {**(result or {}), "outcome":"failed", "executed":False,
                              "reply":"浏览器编辑锁状态待确认，请勿继续修改场景。",
                              "error":{"code":"gateway_unlock_unconfirmed", "message":"Browser edit lock requires explicit recovery"}}
            if session is not None:
                if uncertain:
                    session.sync_state = "unknown"
                else:
                    # A task owns the browser only while it is being processed.  The lease
                    # release above is the authoritative end of that ownership, including
                    # semantic failures (grounding, clarification and unsupported tasks).  Keep
                    # the session editable after a confirmed release; otherwise one failed task
                    # leaves the WebEditor permanently in agent_owned and every later scene
                    # switch is rejected until a manual restart.
                    session.session_phase = "setup"
                try:
                    self.app._save_session(request.sessionID)
                except Exception as exc:
                    uncertain = True
                    result = {**(result or {}),"outcome":"failed","executed":False,
                              "reply":"会话保存失败，现场状态需要人工确认。",
                              "error":{"code":"checkpoint_write_failed","message":str(exc)}}
        self.tasks.update(identifier, "任务失败" if result["outcome"] == "failed" else "任务完成",
                          result, uncertain=uncertain, terminal=True)

    def result(self, report, identifier):
        outcome = {"scene_updated":"scene_updated","answered":"answered","commands_exported":"plan_ready",
                   "session_controlled":"answered"}.get(report.delivery_status, "failed")
        if report.turn_status == "clarification_required" or report.error and report.error.clarification_question:
            outcome = "clarification_required"
        if report.run_status == "failed":
            outcome = "failed"
        result = report.model_dump(mode="json")
        # The public WebEditor envelope exposes a numeric call count.  Keep the
        # detailed trace under a separate key so the browser can render the
        # summary while diagnostics and artifacts retain every call record.
        metrics = result.get("metrics")
        if isinstance(metrics, dict) and isinstance(metrics.get("model_calls"), list):
            metrics["model_call_details"] = metrics["model_calls"]
            metrics["model_calls"] = len(metrics["model_call_details"])
        result.update(taskID=identifier, sessionID=report.session_id, outcome=outcome, executed=False)
        result["artifacts"] = {name:f"/tasks/{identifier}/artifacts/{quote(name)}" for name in report.artifacts
                               if name in {"scene_config", "scene_patch", "commands", "query_result"}}
        if outcome == "plan_ready":
            result["reply"] = "计划已生成，尚未执行。"
        if outcome == "clarification_required":
            result["clarification_question"] = report.clarification_question
            result["reply"] = (report.clarification_question
                                or (report.error.clarification_question if report.error and report.error.clarification_question else None)
                                or report.reply)
            if not result["reply"] or result["reply"] == "需要澄清任务。":
                result["reply"] = "需要澄清：请说明要操作哪个物体、数量和目标位置，可以补充这些信息吗？"
        if "commands" in report.artifacts:
            commands = json.loads(Path(report.artifacts["commands"]).read_text(encoding="utf-8"))
            result["plan"] = commands
            result["planSummary"] = {"operations":commands.get('operations',[]),
                "skillSequence":[c['skill_name'] for c in commands.get('commands',[])]}
        # Internal artifact paths are kept only in the database, never returned.
        result["_artifact_paths"] = report.artifacts
        return result

    def health(self):
        status = {"service":"ready","protocol":PROTOCOL_VERSION,"executed":False,
            "qwen":"unavailable","browser":"not_bound","assets":"unconfigured",
            "capabilities":{"control":False,"segmentation":False,"active_browser_limit":1,
                "requires_open_browser":True,"gateway_protocol":PROTOCOL_VERSION,"commands":["2.0"]}}
        status["browser_id"] = None
        status["tasks"] = {"active_task_id": None, "queued": self.queue.qsize()}
        # §5.3: the Gateway waits three seconds for this reading, so the legs must not queue behind
        # one another -- four sequential one-second caps would already overrun it, and the editor
        # leg alone can stretch that far, which would make a ready service read as unreachable.
        active = next((s for s in self.tasks.sessions() if s["active"]), None)
        if active:
            status["browser_id"] = active["browser"]
        legs = [self._probe_model, self._probe_assets]
        if active:
            legs.append(lambda: self._probe_browser(active["browser"]))
        with ThreadPoolExecutor(max_workers=len(legs)) as pool:
            for future in [pool.submit(leg) for leg in legs]:
                status.update(future.result())
        for record in self._active_records():
            if not record["terminal"]:
                status["tasks"]["active_task_id"] = record["id"]
                break
        return status

    def _probe_model(self):
        client = self.probe_client
        try:
            response = client.get(self.config.base_url.rstrip("/") + "/models")
            response.raise_for_status()
            return {"qwen": "ready" if any(m["id"] == self.config.model for m in response.json()["data"]) else "model_not_found"}
        except Exception:
            return {"qwen": "unavailable"}

    def _probe_assets(self):
        if not self.config.asset_library_root:
            return {}
        cached = self.assets_check
        if cached is not None and time.monotonic() - cached[0] < self.ASSET_CHECK_TTL_SECONDS:
            return cached[1]
        # A catalog walk costs seconds, and the page-load reading is the one that meets it cold: the
        # Gateway is waiting three seconds for this route while the browser is still attaching. So a
        # verdict that has only aged past its TTL still answers, and the refresh runs on its own
        # thread -- the worst this leg can now do is report the library as of TTL ago, never make the
        # reading wait for it.
        if cached is not None:
            self.schedule_asset_refresh()
            return cached[1]
        # The first catalog walk is started by aiohttp's startup hook.  Do not run it inline here:
        # check_ols visits every model, robot and scene and can outlive the Gateway's three-second
        # health deadline.  A cold probe is explicitly transitional until that background refresh
        # publishes its verdict; callers retry the same health endpoint and never wait on the walk.
        self.schedule_asset_refresh()
        return {"assets": "checking", "asset_detail": {"matched": False, "status": "checking"}}

    def schedule_asset_refresh(self):
        if not self.config.asset_library_root:
            return
        with self.assets_lock:
            if self.assets_refreshing:
                return
            self.assets_refreshing = True

        def refresh():
            try:
                self.assets_check = (time.monotonic(), self._asset_verdict())
            finally:
                with self.assets_lock:
                    self.assets_refreshing = False

        threading.Thread(target=refresh, daemon=True).start()

    def _asset_verdict(self):
        client = self.catalog_client
        try:
            detail = check_ols(client, self.ols_url, self.config.asset_library_root)
            return {"assets": "ok" if detail.get("matched") else detail, "asset_detail": detail}
        except Exception as exc:
            return {"assets": {"matched": False, "error": str(exc)}, "asset_detail": {"matched": False, "error": str(exc)}}

    def _probe_browser(self, browser_id):
        # The Gateway answers these two reads through the browser, so this is the leg a busy editor
        # can stretch. A health check must not be able to wait on a task: it shares the short-timeout
        # client and never outlives the Gateway's three-second reading of this route.
        client = self.probe_client
        try:
            gateway = GatewayScenePlatformAdapter(self.gateway_url, browser_id, client=client)
            gateway.capabilities()
            gateway.read_live()
            return {"browser": "bound"}
        except Exception:
            return {"browser": "not_bound"}

    def _active_records(self):
        with self.tasks.lock:
            rows = self.tasks.db.execute("SELECT id FROM tasks WHERE terminal=0").fetchall()
        return [self.tasks.get(row["id"]) for row in rows]

    async def work(self):
        while True:
            identifier = await self.queue.get()
            try:
                await asyncio.to_thread(self.execute, identifier)
            except Exception as exc:
                self.tasks.update(identifier, "任务失败", {"outcome":"failed","executed":False,
                    "error":{"code":"worker_failed","message":str(exc)}}, uncertain=True)
            finally:
                self.queue.task_done()


def create_http_app(service):
    @web.middleware
    async def errors(request, handler):
        try:
            if urlsplit('http://' + request.host).hostname not in {'127.0.0.1', 'localhost', '::1'}:
                raise ValueError('loopback_host_required')
            if request.method == "POST":
                if request.content_type != "application/json":
                    raise ValueError("application_json_required")
                if request.headers.get("Origin") not in {None, service.gateway_url}:
                    raise ValueError("origin_not_allowed")
            return await handler(request)
        except (ValueError, ValidationError, LookupError) as exc:
            text = str(exc)
            code = text.split(":", 1)[0]
            status = 404 if code in {"task_not_found","session_not_found","artifact_not_found"} else 422 if code in {
                "web_platform_profile_unsupported", "robot_joint_inventory_missing"} else 409 if code in {
                "task_busy","idempotency_conflict","session_browser_not_active","session_reconciliation_required"} else 400
            return web.json_response({"error":{"code":code,"message":text}}, status=status)

    app = web.Application(middlewares=[errors], client_max_size=100 * 1024 * 1024)

    def task_id(request):
        value = request.query.get("taskID", request.match_info.get("taskID", ""))
        if not value.isascii() or not value.isdigit() or not 0 < int(value) <= 2**53-1:
            raise ValueError("invalid_task_id")
        return int(value)

    async def start(request):
        payload = await request.json()
        if not isinstance(payload, dict) or not {"sessionID", "clientRequestID", "browserID", "sceneDigest"} <= payload.keys():
            raise ValueError("session_context_required: create/restore an explicit session first")
        value = StartTask.model_validate(payload)
        parsed = validate_web_scene(value.scene)
        if not value.command.strip() or digest(value.scene) != value.sceneDigest:
            raise ValueError("task_scene_digest_or_command_invalid")
        if value.scene_id is not None and value.scene_id != parsed.scene_id:
            raise ValueError("task_scene_identity_invalid")
        if value.scene_version is not None and value.scene_version != parsed.scene_version:
            raise ValueError("task_scene_identity_invalid")
        if value.scene_sub_version != parsed.scene_sub_version:
            raise ValueError("task_scene_identity_invalid")
        async with service.mutex:
            # Reject unsupported platforms before creating a task or acquiring the browser lease.
            # The worker repeats these checks against the live scene; this side-effect-free pass
            # prevents an invalid/empty scene from leaving the editor in agent_owned.
            binding = service.tasks.binding(value.sessionID)
            if not binding["active"] or binding["browser"] != value.browserID:
                raise ValueError("session_browser_not_active")
            if binding["uncertain"]:
                raise ValueError("session_reconciliation_required")
            service._bind(value.sessionID)
            service.validate_scene(value.scene, None)
            record, fresh = service.tasks.submit(value)
            if fresh:
                service.tasks.update(record["id"], "已进入队列", terminal=False)
                await service.queue.put(record["id"])
            current = service.tasks.get(record["id"])
            return web.json_response({"taskID":record["id"],"state":current["state"],
                                      "terminal":current["terminal"],"code":0})

    async def state(request):
        record = service.tasks.get(task_id(request))
        return web.json_response({"taskID":record["id"],"state":record["state"],"terminal":record["terminal"],
                                  "state_detail":None})

    async def failure(request):
        record = service.tasks.get(task_id(request))
        result = record["result"] or {}
        return web.json_response({"taskID":record["id"],"terminal":record["terminal"],
            "failureReason":((result.get("error") or {}).get("message") or result.get("reply"))
                if record["terminal"] and result.get("outcome") == "failed" else None})

    async def result(request):
        record = service.tasks.get(task_id(request))
        value = record["result"]
        return web.json_response({**{k:v for k,v in value.items() if not k.startswith("_")},
                                 "taskID":record['id'],"sessionID":record['session']} if value else
                                 {"taskID":record["id"],"state":record["state"],"terminal":record["terminal"],
                                  "executed":False}, status=200 if value else 202)

    async def sessions(request):
        if request.method == "GET":
            browser_id = request.query.get("browser_id")
            sessions = service.tasks.sessions()
            if browser_id:
                sessions = [s for s in sessions if s["browser"] == browser_id]
            for item in sessions:
                if item["id"] in service.app.sessions:
                    session = service.app.sessions[item["id"]]
                    item["session_phase"] = getattr(session, "session_phase", "setup")
                    item["camera_id"] = getattr(session, "camera_id", None)
                else:
                    item["session_phase"] = "setup"
                    item["camera_id"] = service.camera_bindings.get(item["id"])
            return web.json_response({"sessions":sessions})
        value = SessionRequest.model_validate(await request.json())
        async with service.mutex:
            return web.json_response(service.activate(value))

    async def session_state(request):
        browser_id = request.query.get("browser_id")
        if not browser_id:
            raise ValueError("session_context_required")
        values = [s for s in service.tasks.sessions() if s["browser"] == browser_id and s["active"]]
        if not values:
            raise ValueError("session_not_found")
        item = values[0]
        session = service.app.get_session(item["id"])
        scene = getattr(session, "scene", None)
        return web.json_response({
            "sessionID": item["id"], "browser_id": browser_id,
            "session_phase": getattr(session, "session_phase", "setup"),
            "lease": bool(getattr(session.platform, "lease", None)),
            "quarantine": bool(item["uncertain"]),
            "scene_id": scene.scene_id if scene else None,
            "scene_version": scene.scene_version if scene else None,
            "scene_sub_version": scene.scene_sub_version if scene else None,
            "sceneDigest": digest(scene) if scene else None,
        })

    async def artifact(request):
        record = service.tasks.get(task_id(request))
        value = record["result"] or {}
        name = request.match_info["name"]
        if name not in {"scene_config","scene_patch","commands","query_result"}:
            raise ValueError("artifact_not_found")
        target = value.get("_artifact_paths",{}).get(name)
        if not target:
            raise ValueError("artifact_not_found")
        path = Path(target).resolve()
        allowed = service.output / record["session"] / value["request_id"]
        if not path.is_relative_to(allowed.resolve()) or not path.is_file():
            raise ValueError("artifact_not_found")
        return web.FileResponse(path, headers={"Content-Disposition":f'attachment; filename="{name}.json"'})

    async def health(request):
        return web.json_response(await asyncio.to_thread(service.health))

    app.router.add_post("/startTask", start)
    app.router.add_get("/queryTaskState", state)
    app.router.add_get("/queryTaskFailureReason", failure)
    app.router.add_get("/queryTaskResult", result)
    app.router.add_get("/sessions", sessions)
    app.router.add_post("/sessions", sessions)
    app.router.add_get("/sessionState", session_state)
    app.router.add_get("/tasks/{taskID}/artifacts/{name}", artifact)
    app.router.add_get("/health", health)

    async def allocate_object_id(request):
        count = int(request.query.get("count", "1"))
        if count < 1 or count > 10000:
            raise ValueError("gateway_object_allocator_invalid")
        binding = service.tasks.binding(request.query.get("browser_id", ""))
        if not binding["active"]:
            raise ValueError("session_browser_not_active")
        # Brain's local allocator is monotonic; Gateway remains the final
        # authority in the real deployment and may return a larger range.
        session = service.app.get_session(next(s["id"] for s in service.tasks.sessions()
                                               if s["browser"] == binding["browser"]))
        start = max(session.next_scene_object_id, 0)
        if start + count > 2**32 - 1:
            raise ValueError("object_id_space_exhausted")
        session.next_scene_object_id = start + count
        return web.json_response({"object_ids": list(range(start, start + count)),
                                  "next_object_id": session.next_scene_object_id})

    async def resolve_uncertain(request):
        payload = await request.json()
        browser_id = payload.get("browserID")
        session_id = payload.get("sessionID")
        if not browser_id or not session_id:
            raise ValueError("session_context_required")
        transaction_id = payload.get("transactionID")
        resolution = payload.get("resolution", "resume")
        if transaction_id is not None and (not isinstance(transaction_id, str) or not transaction_id.strip()):
            raise ValueError("transaction_id_invalid")
        if resolution not in {"resume", "new_session"}:
            raise ValueError("resolution_invalid")
        binding = service.tasks.binding(session_id)
        session = service.app.get_session(session_id)
        evidence = payload.get("evidence") or {}
        if binding["browser"] != browser_id or not binding["uncertain"]:
            return web.json_response({"state":"kept_locked","sessionID":session_id,
                                      "transactionID":transaction_id,
                                      "resolution":resolution,
                                      "reason":"uncertain_evidence_missing"})
        live = None
        try:
            live = service.platform().read_live()
        except Exception:
            pass
        receipt_status = evidence.get("receipt_status", "missing")
        if receipt_status not in {"missing", "committed", "rejected", "unknown"}:
            return web.json_response({"state":"kept_locked","sessionID":session_id,
                                      "transactionID":transaction_id,
                                      "resolution":resolution,
                                      "reason":"uncertain_evidence_invalid"})
        expected = evidence.get("expected_digest")
        live_digest = digest(live) if live is not None else None
        # Brain cannot infer a transaction outcome from a timeout.  The caller
        # must provide an explicit receipt status (or ``missing``), exclude
        # late writes, and identify the live scene it actually read.
        valid = (bool(evidence.get("late_write_excluded"))
                 and evidence.get("live_digest") == live_digest
                 and live is not None)
        if expected is not None:
            valid = valid and live_digest == expected
        if receipt_status in {"committed", "rejected"} and not transaction_id:
            valid = False
        if not valid:
            return web.json_response({"state":"kept_locked","sessionID":session_id,
                                      "transactionID":transaction_id,
                                      "resolution":resolution,
                                      "reason":"uncertain_evidence_invalid"})
        with service.tasks.lock, service.tasks.db:
            service.tasks.db.execute("UPDATE sessions SET uncertain=0 WHERE id=?", (session_id,))
        session.sync_state = "synchronized"
        session.recovery_context = None
        service.app._save_session(session_id)
        return web.json_response({"state":"resolved","sessionID":session_id,
            "transactionID":transaction_id,"resolution":resolution,
            "scene_id":live.scene_id,"scene_version":live.scene_version,
            "scene_sub_version":live.scene_sub_version,"sceneDigest":live_digest,"reason":"evidence_verified"})

    app.router.add_get("/allocateObjectID", allocate_object_id)
    app.router.add_post("/resolveUncertain", resolve_uncertain)

    async def startup(app):
        # Finish the first catalog walk before aiohttp accepts requests.  The Gateway's /health
        # relay has a three-second deadline, while check_ols may read dozens of OLS assets.  Later
        # TTL refreshes stay in the background, so a health probe never waits on the catalog.
        if service.config.asset_library_root:
            verdict = await asyncio.to_thread(service._asset_verdict)
            service.assets_check = (time.monotonic(), verdict)
        service.worker = asyncio.create_task(service.work())

    async def cleanup(app):
        # Do not cancel a thread while it may still commit a scene.
        await service.queue.join()
        service.worker.cancel()
        try:
            await service.worker
        except asyncio.CancelledError:
            pass
        for session in service.app.sessions.values():
            session.platform.client.close()
        service.tasks.close()
    app.on_startup.append(startup)
    app.on_cleanup.append(cleanup)
    return app


def serve(args):
    config = BrainConfig.load(args.config)
    service = AgentService(config, gateway_url=args.gateway_url, ols_url=args.ols_url,
                           joint_inventory=args.joint_inventory, camera_id=args.camera_id)
    web.run_app(create_http_app(service), host="127.0.0.1", port=args.port)
