"""Application orchestration shared by APIs and terminal clients. Export only."""
import time
import uuid
import json
import traceback
from pathlib import Path
from pydantic import ValidationError
from .config import BrainConfig
from .pipeline import BrainPipeline
from .session.brain_session import BrainSession
from .session.store import SessionStore
from .scene.bootstrapper import SceneBootstrapper
from .adapters.local_scene_platform import LocalScenePlatform
from .adapters.scene_file_codec import SceneFileCodec
from .adapters.artifact_writer import ArtifactWriter, safe_identifier
from .contracts.run_report import BrainRunReport
from .errors import BrainIssue, BrainError
from .models.qwen_http import QwenHTTPProvider, QwenProviderError
from .diagnostics import configuration_summary, fingerprint, redact


class BrainApplication:
    def __init__(self, config=None, *, provider=None, platform_factory=LocalScenePlatform):
        self.config = config or BrainConfig.load()
        self.assets = self.config.load_assets()
        self.defaults = self.config.load_defaults()
        self.config_summary = configuration_summary(self.config, self.assets, self.defaults)
        self.config_fingerprint = fingerprint(self.config_summary)
        if provider is None:
            if self.config.provider != "qwen" or not self.config.model:
                raise BrainError("config_missing", "configuration", "Configure a model or supply a replay provider")
            provider = QwenHTTPProvider(self.config.base_url, self.config.model,
                api_key=self.config.api_key.get_secret_value() if self.config.api_key else "",
                timeout=self.config.timeout, structured_output=self.config.structured_output)
        self.provider = provider
        self.pipeline = BrainPipeline(provider, self.assets)
        self.bootstrapper = SceneBootstrapper(self.assets, self.defaults, robot=self.config.robot, seed=self.config.seed)
        self.codec = SceneFileCodec(self.assets)
        self.writer = ArtifactWriter(self.config.output_dir)
        self.sessions = {}
        self.store = SessionStore(self.config.output_dir)
        self.revisions = {}
        self.platform_factory = platform_factory

    def get_session(self, session_id):
        safe_identifier(session_id)
        state = self.store.load(session_id)
        if session_id not in self.sessions or state is not None and state.revision > self.revisions.get(session_id, 0):
            if state is not None and state.scene is not None:
                for obj in state.scene.objects:
                    try:
                        self.assets.get_model_property(obj.asset_id)
                    except LookupError as exc:
                        raise ValueError("session_asset_missing: " + obj.asset_id) from exc
            session = BrainSession(None, self.pipeline, self.platform_factory())
            self.sessions[session_id] = self.store.restore(state, session) if state else session
            self.sessions[session_id].restored_config_fingerprint = state.config_fingerprint if state else None
            self.revisions[session_id] = state.revision if state else 0
        return self.sessions[session_id]

    def load_scene(self, session_id, path):
        with self.store.lock(session_id):
            scene = self._load_scene(session_id, path)
            self._save_session(session_id)
            return scene

    def _load_scene(self, session_id, path):
        session = self.get_session(session_id)
        scene = self.codec.load(path)
        session.initialize_scene(scene)
        return session.scene

    def handle(self, instruction, *, session_id=None, scene_path=None):
        session_id = session_id or uuid.uuid4().hex
        try:
            with self.store.lock(session_id):
                return self._handle(instruction, session_id=session_id, scene_path=scene_path)
        except Exception as exc:
            # Lock/restore failures happen before a safe request directory can
            # be published. Still return a complete report, never old artifacts.
            issue = self._issue(exc, "session_restore")
            secret = self.config.api_key.get_secret_value() if self.config.api_key else None
            issue = BrainIssue.model_validate(redact(issue.model_dump(), secret))
            return BrainRunReport(session_id=session_id, request_id=uuid.uuid4().hex,
                run_status="blocked" if issue.code == "session_busy" else "failed",
                provider=self.config.provider, error=issue, reply=issue.message,
                metrics={"understanding_calls":0, "vision_calls":0, "model_calls":[]})

    def _save_session(self, session_id):
        self.revisions[session_id] = self.store.save(session_id, self.sessions[session_id],
            revision=self.revisions.get(session_id, 0) + 1, config_fingerprint=self.config_fingerprint)

    def mark_dispatched(self, session_id, commands):
        with self.store.lock(session_id):
            session = self.get_session(session_id)
            from .contracts.commands import canonical_commands
            path = Path(self.config.output_dir).resolve() / safe_identifier(session_id) / safe_identifier(commands.request_id) / "commands.json"
            if not path.is_file() or json.loads(path.read_text(encoding="utf-8")) != canonical_commands(commands):
                raise ValueError("execution_export_artifact_missing_or_changed")
            session.mark_dispatched(commands)
            self._save_session(session_id)

    def apply_execution_feedback(self, session_id, feedback, *, confirmed_scene=None, feedback_source="external"):
        with self.store.lock(session_id):
            session = self.get_session(session_id)
            try:
                return session.apply_execution_feedback(feedback, confirmed_scene=confirmed_scene,
                                                        feedback_source=feedback_source)
            finally:
                self._save_session(session_id)

    def _handle(self, instruction, *, session_id, scene_path=None):
        request_id = uuid.uuid4().hex
        session = self.get_session(session_id)
        started = time.monotonic()
        report = BrainRunReport(session_id=session_id, request_id=request_id, run_status="failed",
                                provider=self.config.provider)
        result = None
        turn = None
        debug = {}
        stage = "session"
        before = session.scene
        calls_start = len(getattr(self.provider, "calls", []))
        understanding_calls = 0
        try:
            if session.session_action == "close":
                raise ValueError("session_closed")
            if scene_path is not None:
                stage = "scene_import"
                if session.scene is not None:
                    raise ValueError("scene_already_loaded: use explicit load_scene to replace it")
                self._load_scene(session_id, scene_path)
                report.scene_source = "uploaded"
                report.scene_commit_status = "committed"
            elif session.scene is not None:
                report.scene_source = "session"
            stage = "understanding"
            understanding_calls = 1
            turn = self.pipeline.understand_turn(instruction, scene=session.scene, dialogue=session.dialogue)
            report.turn_kind, report.turn_status = turn.turn_kind, turn.status
            if turn.status != "accepted":
                report.run_status = "blocked"
                report.reply = "需要澄清任务。" if turn.status == "clarification_required" else "不支持该任务。"
            else:
                session.check_turn(turn)
                bindings = None
                if session.scene is None and turn.turn_kind not in {"scene_query", "session_control"}:
                    stage = "bootstrap"
                    initial = self.bootstrapper.prepare(turn, scene_id=uuid.uuid4().hex)
                    session.initialize_scene(initial.scene)
                    report.scene_source = "generated"
                    report.scene_created = True
                    report.scene_commit_status = "committed"
                    report.assumptions = initial.assumptions
                    bindings = initial.bindings_for(session.scene)
                stage = "processing"
                result = session.process_turn(request_id, turn, bindings_override=bindings,
                                              edit_defaults=self.defaults if report.scene_created else None)
                report.run_status = "success"
                if result.commands is not None:
                    report.delivery_status = "commands_exported"
                    report.reply = "已生成任务计划，尚未执行。"
                elif result.scene_patch is not None:
                    report.delivery_status = "scene_updated"
                    report.scene_commit_status = "committed"
                    report.reply = "场景元数据已更新（未运行仿真）。"
                elif result.scene_query_result is not None:
                    query = result.scene_query_result
                    report.delivery_status = "answered"
                    if query.query_type == "count":
                        report.reply = f"匹配对象共 {query.count} 个。"
                    elif query.query_type == "existence":
                        report.reply = "存在匹配对象。" if query.exists else "不存在匹配对象。"
                    else:
                        report.reply = str(query.positions if query.query_type == "position" else query.states)
                else:
                    report.delivery_status = "session_controlled"
                    report.reply = "会话状态：" + result.session_action.action
        except Exception as exc:
            if self.config.debug:
                debug["traceback"] = traceback.format_exc()
            report.error = self._issue(exc, stage)
            report.run_status = "blocked" if report.error.code.startswith(("scene_required", "grounding_", "bootstrap_", "asset_", "holding_", "plan_", "capability_", "dialogue_", "motion_", "execution_pending", "session_paused", "scene_sync_")) else "failed"
            report.reply = report.error.message
            if session.sync_state == "unknown":
                report.scene_commit_status = "unknown"
        if session.scene is not None:
            report.scene_id, report.scene_version = session.scene.scene_id, session.scene.scene_version
        report.metrics = {"understanding_calls":understanding_calls, "vision_calls":0,
                          "elapsed_seconds":time.monotonic()-started,
                          "model_calls":getattr(self.provider,"calls",[])[calls_start:]}
        previous_config = getattr(session, "restored_config_fingerprint", None)
        if previous_config and previous_config != self.config_fingerprint:
            report.assumptions.append("configuration_changed_since_restore: confirmed scene retained; review deployment metadata")
        record = {"instruction":instruction, "provider":self.config.provider,
                  "turn_kind":report.turn_kind, "turn_status":report.turn_status,
                  "config":self.config_summary, "config_fingerprint":self.config_fingerprint,
                  "restored_config_fingerprint":previous_config,
                  "scene_source":report.scene_source, "before_version":before.scene_version if before else None,
                  "after_version":report.scene_version}
        secret = self.config.api_key.get_secret_value() if self.config.api_key else None
        if self.config.debug:
            debug["model_calls"] = report.metrics["model_calls"]
            if len(getattr(self.provider, "calls", [])) > calls_start:
                debug["raw_model_response"] = json.dumps(getattr(self.provider, "last_raw_text", {}), ensure_ascii=False)
            if turn is not None:
                debug["brain_turn"] = turn.model_dump(mode="json")
                if turn.task_intent is not None:
                    debug["task_intent"] = turn.task_intent.model_dump(mode="json")
            if result is not None:
                for key in ("grounded_task", "skill_plan"):
                    value = getattr(result, key)
                    if value is not None:
                        debug[key] = value.model_dump(mode="json")
        report = BrainRunReport.model_validate(redact(report.model_dump(mode="json"), secret))
        try:
            self._save_session(session_id)
            return self.writer.publish(report, scene=session.scene, result=result,
                                       request_record=redact(record, secret), debug=redact(debug, secret))
        except Exception as exc:
            report.run_status = "failed"
            report.delivery_status = "none"
            report.artifacts = {}
            report.error = BrainIssue(code="artifact_write_failed", stage="publication", message=str(exc))
            report.reply = "产物保存失败；场景提交状态：" + report.scene_commit_status
            return report

    @staticmethod
    def _issue(exc, stage):
        if isinstance(exc, BrainError):
            return exc.issue
        if isinstance(exc, QwenProviderError):
            code = exc.code
        elif isinstance(exc, ValidationError):
            code = "model_output_invalid" if stage == "understanding" else "validation_failed"
        elif isinstance(exc, ValueError) and ":" in str(exc):
            code = str(exc).split(":",1)[0]
        elif isinstance(exc, ValueError) and str(exc).replace("_", "").isalnum():
            code = str(exc)
        else:
            code = "internal_error"
        return BrainIssue(code=code, stage=stage, message=str(exc))
