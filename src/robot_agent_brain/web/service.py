"""Loopback-only persistent Agent service. One worker, no Control dispatch."""
import asyncio
import json
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
    def __init__(self, config, *, gateway_url="http://127.0.0.1:8099", ols_url="http://127.0.0.1:8000",
                 joint_inventory=None, camera_id=5, provider=None, platform_factory=None):
        if config.scene_id_bits != 32:
            raise ValueError("web_uint32_configuration_required")
        loopback_url(config.base_url)
        self.gateway_url, self.ols_url = loopback_url(gateway_url), loopback_url(ols_url)
        self.config, self.camera_id = config, camera_id
        self.output = Path(config.output_dir).resolve()
        self.joints = json.loads(Path(joint_inventory).read_text()) if joint_inventory else None
        if config.asset_library_root and self.joints is None:
            raise ValueError("robot_joint_inventory_required")
        self.references = ComponentReferenceRegistry(config.component_reference_rules)
        self.tasks = TaskStore(self.output / "agent_tasks.sqlite3")
        self.binding = None
        self.platform_override = platform_factory
        self.app = BrainApplication(config, provider=provider, platform_factory=self.platform)
        self.queue = asyncio.Queue()
        self.mutex = asyncio.Lock()
        self.worker = None
        self.last_health = {}

    def platform(self):
        if self.binding is None:
            raise ValueError("session_binding_required")
        if self.platform_override:
            return self.platform_override(self.binding)
        return GatewayScenePlatformAdapter(self.gateway_url, self.binding["browser"], camera_id=self.camera_id,
            joint_inventory=self.joints, reference_registry=self.references,
            journal_dir=self.output / self.binding["id"] / "gateway_transactions")

    def _bind(self, session_id):
        self.binding = self.tasks.binding(session_id)
        session = self.app.get_session(session_id)
        if session.platform.browser_id != self.binding["browser"]:
            session.platform = self.platform()
        return session

    def validate_scene(self, scene, session=None):
        scene = validate_web_scene(scene, self.joints, self.references)
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
                index = json.loads((Path(self.config.asset_library_root) / "scenes/scene_index.json").read_text())
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
        identifier = self.tasks.activate(request.browserID, request.sessionID)
        return {"sessionID":identifier,"browserID":request.browserID,"active":True}

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
            platform = session.platform
            scene = self.validate_scene(request.scene, session)
            platform.receipts = []
            platform.capabilities()
            if self.config.asset_library_root:
                with httpx.Client(timeout=10, trust_env=False) as client:
                    check_ols(client, self.ols_url, self.config.asset_library_root)
            platform.acquire_lease(identifier, scene)
            manifest = session.platform_object_ids if session.scene is not None else (
                self.config.editor_scene_manifests.get(scene.scene_name) if self.config.editor_scene_manifests else self.config.scene_platform_object_ids)
            self.app.accept_browser_scene(request.sessionID, scene, platform_object_ids=manifest)
            report = self.app.handle(request.command, session_id=request.sessionID)
            record_path = self.output / request.sessionID / report.request_id / "request_record.json"
            turn_record = json.loads(record_path.read_text())
            if turn_record.get("id_remap"):
                platform.remap_camera(turn_record["id_remap"])
            result = self.result(report, identifier)
            # Even non-mutating plans must still refer to the live editor state.
            if session.scene is not None and digest(platform.read_live()) != digest(session.scene):
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
                try:
                    self.app._save_session(request.sessionID)
                except Exception as exc:
                    uncertain = True
                    result = {**(result or {}),"outcome":"failed","executed":False,
                              "reply":"会话保存失败，现场状态需要人工确认。",
                              "error":{"code":"checkpoint_write_failed","message":str(exc)}}
        self.tasks.update(identifier, "任务失败" if result["outcome"] == "failed" else "任务完成", result, uncertain=uncertain)

    def result(self, report, identifier):
        outcome = {"scene_updated":"scene_updated","answered":"answered","commands_exported":"plan_ready",
                   "session_controlled":"answered"}.get(report.delivery_status, "failed")
        if report.turn_status == "clarification_required" or report.error and report.error.clarification_question:
            outcome = "clarification_required"
        if report.run_status == "failed":
            outcome = "failed"
        result = report.model_dump(mode="json")
        result.update(taskID=identifier, sessionID=report.session_id, outcome=outcome, executed=False)
        result["artifacts"] = {name:f"/tasks/{identifier}/artifacts/{quote(name)}" for name in report.artifacts
                               if name in {"scene_config", "scene_patch", "commands", "query_result"}}
        if outcome == "plan_ready":
            result["reply"] = "计划已生成，尚未执行。"
        if outcome == "clarification_required":
            result["reply"] = report.error.clarification_question if report.error and report.error.clarification_question else report.reply
            if not result["reply"] or result["reply"] == "需要澄清任务。":
                result["reply"] = "需要澄清：请说明要操作哪个物体、数量和目标位置，可以补充这些信息吗？"
        if "commands" in report.artifacts:
            commands = json.loads(Path(report.artifacts["commands"]).read_text())
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
        with httpx.Client(timeout=3, trust_env=False) as client:
            try:
                response = client.get(self.config.base_url.rstrip("/") + "/models")
                response.raise_for_status()
                status["qwen"] = "ready" if any(m["id"] == self.config.model for m in response.json()["data"]) else "model_not_found"
            except Exception:
                pass
            if self.config.asset_library_root:
                try:
                    status["assets"] = check_ols(client, self.ols_url, self.config.asset_library_root)
                except Exception as exc:
                    status["assets"] = {"matched":False,"error":str(exc)}
        active = next((s for s in self.tasks.sessions() if s["active"]), None)
        if active:
            try:
                gateway = GatewayScenePlatformAdapter(self.gateway_url, active["browser"])
                gateway.capabilities()
                gateway.read_live()
                status["browser"] = "ready"
                gateway.client.close()
            except Exception as exc:
                status["browser"] = str(exc)
        return status

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
            status = 404 if code in {"task_not_found","session_not_found","artifact_not_found"} else 409 if code in {
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
        if not value.command.strip() or digest(value.scene) != value.sceneDigest:
            raise ValueError("task_scene_digest_or_command_invalid")
        async with service.mutex:
            record, fresh = service.tasks.submit(value)
            if fresh:
                service.tasks.update(record["id"], "已进入队列")
                await service.queue.put(record["id"])
            return web.json_response({"taskID":record["id"],"state":service.tasks.get(record["id"])["state"],"code":0})

    async def state(request):
        record = service.tasks.get(task_id(request))
        return web.json_response({"taskID":record["id"],"state":record["state"]})

    async def failure(request):
        record = service.tasks.get(task_id(request))
        result = record["result"] or {}
        return web.json_response({"taskID":record["id"],"state":record["state"],
            "failureReason":((result.get("error") or {}).get("message") or result.get("reply"))
                if record['state']=='任务失败' else None})

    async def result(request):
        record = service.tasks.get(task_id(request))
        value = record["result"]
        return web.json_response({**{k:v for k,v in value.items() if not k.startswith("_")},
                                 "taskID":record['id'],"sessionID":record['session']} if value else
                                 {"taskID":record["id"],"state":record["state"],"executed":False}, status=200 if value else 202)

    async def sessions(request):
        if request.method == "GET":
            return web.json_response({"sessions":service.tasks.sessions()})
        value = SessionRequest.model_validate(await request.json())
        async with service.mutex:
            return web.json_response(service.activate(value))

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
    app.router.add_get("/tasks/{taskID}/artifacts/{name}", artifact)
    app.router.add_get("/health", health)

    async def startup(app):
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
