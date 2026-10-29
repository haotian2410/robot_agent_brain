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
from .scene.editor import SceneEditor
from .scene.scene_layout import SceneLayoutPolicy
from .scene.layout_geometry import SceneLayoutGeometryRegistry
from .adapters.local_scene_platform import LocalScenePlatform
from .adapters.scene_file_codec import SceneFileCodec
from .adapters.artifact_writer import ArtifactWriter, safe_identifier
from .contracts.run_report import BrainRunReport
from .contracts.turn import TurnStatus
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
                timeout=self.config.timeout, structured_output=self.config.structured_output,
                planner_max_completion_tokens=self.config.planner_max_completion_tokens)
        self.provider = provider
        if self.config.vision and (platform_factory is LocalScenePlatform or not hasattr(provider, "detect")):
            raise BrainError("vision_requires_rendering_platform", "configuration",
                             "Vision requires an explicit rendering platform and a detection provider; LocalScenePlatform has no images")
        aliases = (self.config.load_semantic_aliases() if self.config.semantic_aliases is not None
                   else getattr(getattr(self.assets, "metadata", None), "aliases", {}))
        category_aliases = getattr(getattr(self.assets, "metadata", None), "category_aliases", {})
        layout_interiors = SceneLayoutGeometryRegistry.from_path(self.config.scene_layout_interiors)
        editor = SceneEditor(self.assets, SceneLayoutPolicy(clearance_m=self.config.scene_layout_near_clearance_m,
                                                            grid_size=self.config.scene_layout_grid_size), seed=self.config.seed,
                             aliases=aliases, category_aliases=category_aliases,
                             default_scene_edit_assets=self.config.default_scene_edit_assets,
                             scale_policy=self.config.scale_policy(), scale_defaults=self.defaults,
                             table_metadata_ref=self.config.bootstrap_settings().get("default_table_metadata_ref"),
                             layout_interiors=layout_interiors)
        self.pipeline = BrainPipeline(provider, self.assets, scene_editor=editor,
                                      vision_provider=provider if self.config.vision else None,
                                      skill_planning_provider=provider if hasattr(provider, "plan") else None,
                                      planner_mode=self.config.planner, robot=self.config.robot,
                                      query_near_distance_m=self.config.query_near_distance_m,
                                      aliases=self.config.load_semantic_aliases() if self.config.semantic_aliases else None)
        bootstrap = self.config.bootstrap_settings()
        self.bootstrapper = SceneBootstrapper(self.assets, self.defaults, robot=self.config.robot, seed=self.config.seed,
            table_metadata_ref=bootstrap.get("default_table_metadata_ref"),
            robot_metadata_ref=bootstrap.get("default_robot_metadata_ref"),
            robot_driver=bootstrap.get("default_robot_driver"),
            aliases=aliases, category_aliases=category_aliases,
            default_scene_edit_assets=self.config.default_scene_edit_assets)
        self.codec = SceneFileCodec(self.assets)
        if self.config.default_scene:
            template = self.codec.load(self.config.default_scene)
            self.bootstrapper.template_scene = template
            from .scene.scene_graph import world_transform
            # The editor defaults contain bootstrap IDs, while an imported
            # browser scene may remap platform object IDs.  Resolve the table
            # from the template's metadata instead of assuming the numeric
            # bootstrap ID remains valid.
            try:
                table_id = editor._default_surface_id(template, self.defaults)
            except ValueError:
                table_id = self.defaults.table_object_id
            editor.scale_table_transform = world_transform(template, table_id)
        self.writer = ArtifactWriter(self.config.output_dir)
        self.sessions = {}
        self.store = SessionStore(self.config.output_dir)
        self.revisions = {}
        self.platform_factory = platform_factory

    def get_session(self, session_id):
        safe_identifier(session_id)
        state = self.store.load(session_id)
        from .session.publication_store import PublicationStore
        PublicationStore(self.store.directory(session_id)).require_checkpoint(state)
        if session_id not in self.sessions or state is not None and state.revision > self.revisions.get(session_id, 0):
            # Scene Semantic queries do not require mesh resources. Resolve
            # MetadataRef only when geometry is actually needed, not on restore.
            from .scene.component_reference_registry import ComponentReferenceRegistry
            session = BrainSession(None, self.pipeline, self.platform_factory(), robot_profiles=self.config.robot_profiles,
                reference_registry=ComponentReferenceRegistry(self.config.component_reference_rules))
            session.scene_id_bits = self.config.scene_id_bits
            self.sessions[session_id] = self.store.restore(state, session) if state else session
            from .session.original_scene_store import OriginalSceneStore
            self.sessions[session_id].original_store = OriginalSceneStore(self.store.directory(session_id))
            # LocalScenePlatform edits metadata only. External platforms must
            # explicitly opt into destructive scene resets via configuration.
            self.sessions[session_id].scene_reset_allowed = self.platform_factory is LocalScenePlatform or self.config.allow_scene_reset
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
        profile = None
        if self.config.scene_robot_profile is not None:
            profile = self.config.robot_profiles.profiles[self.config.scene_robot_profile]
            profile.validate_scene(scene)
        elif self.config.scene_platform_object_ids is not None:
            if not self.config.scene_platform_object_ids <= {o.object_id_in_scene for o in scene.objects}:
                raise ValueError("scene_platform_manifest_invalid")
        session.initialize_scene(scene)
        if profile is not None:
            session.bind_imported_profile(profile)
        elif self.config.scene_platform_object_ids is not None:
            session.platform_object_ids = set(self.config.scene_platform_object_ids)
        # The acknowledged import, not its first edited successor, is original.
        # Persist first so a later understanding/publication failure cannot lose
        # the platform-confirmed import; capture_once keeps earlier originals.
        self._save_session(session_id)
        # An explicitly imported empty template is still a valid original
        # snapshot.  Do not wait for the first added object: otherwise the
        # first edit becomes part of ``original_scene.json`` and later
        # "原始场景" edits cannot reproduce the imported scene.
        self._capture_original(session_id, request_id="import-" + uuid.uuid4().hex,
                               source="uploaded", allow_empty=True)
        self._save_session(session_id)
        return session.scene

    def _capture_original(self, session_id, *, request_id, source, allow_empty=False):
        from .session.original_scene_store import OriginalSceneStore
        session = self.sessions[session_id]
        if session.scene is not None and session.original_scene_manifest is None:
            session.original_scene_manifest = OriginalSceneStore(self.store.directory(session_id)).capture_once(
                session.scene, platform_object_ids=session.platform_object_ids, request_id=request_id,
                source=source, robot_setup=session.robot_setup, config_fingerprint=self.config_fingerprint,
                profile_object_map=session.profile_object_map, allow_empty=allow_empty)

    def accept_browser_scene(self, session_id, scene, *, platform_object_ids=None):
        """External editor metadata sync, distinct from execution reconciliation."""
        with self.store.lock(session_id):
            session = self.get_session(session_id)
            candidate = self.codec.decode(scene.raw_document() if hasattr(scene, "raw_document")
                                          else (scene.model_dump(mode="json") if hasattr(scene, "model_dump") else scene))
            manifest = platform_object_ids if platform_object_ids is not None else self.config.scene_platform_object_ids
            if manifest is None:
                raise ValueError("browser_platform_manifest_required")
            changed = session.accept_browser_scene(candidate, platform_object_ids=manifest)
            self._save_session(session_id)
            self._capture_original(session_id, request_id="browser-import-" + uuid.uuid4().hex, source="uploaded", allow_empty=True)
            self._save_session(session_id)
            return changed

    def _editor_defaults(self, session):
        """Allow implicit additions only on the explicitly configured editor table.

        This does not apply the default workspace to arbitrary imported scenes.
        """
        if self.bootstrapper.template_scene is None or session.scene is None:
            return None
        # Automatically bootstrapped sessions already carry a Brain-owned
        # template and platform manifest.  Keep the same table/workspace
        # defaults available after an original-scene derivation, whose new
        # scene id and task objects no longer compare equal to the template.
        # Uploaded scenes remain excluded unless their configured manifest
        # explicitly opts them in.
        manifest = session.original_scene_manifest
        if manifest is not None and manifest.source == "generated":
            return self.defaults
        # An explicitly imported editor scene is also eligible when its
        # configured platform manifest identifies the scene.  After deriving
        # an original-scene edit the scene id changes, so comparing the whole
        # scene to the template would incorrectly drop the editor defaults on
        # the second original-scene operation.
        if manifest is not None and manifest.source == "uploaded":
            scene_name = getattr(session.scene, "scene_name", None)
            configured = self.config.editor_scene_manifests.get(scene_name, [])
            imported_platform = set(manifest.platform_object_ids)
            if configured and set(configured) == imported_platform:
                return self.defaults
        if not self.config.editor_scene_manifests:
            return None
        from .scene.component_access import SceneIndex
        from .scene.scene_graph import world_transform
        identifier = self.defaults.table_object_id
        try:
            actual, template = SceneIndex(session.scene), SceneIndex(self.bootstrapper.template_scene)
            if (identifier in (session.platform_object_ids or set())
                    and actual.metadata_ref_properties(identifier) == template.metadata_ref_properties(identifier)
                    and world_transform(session.scene, identifier) == world_transform(self.bootstrapper.template_scene, identifier)):
                return self.defaults
        except (LookupError, ValueError):
            pass
        return None

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
                metrics={"understanding_calls":0, "vision_calls":0, "skill_planning_calls":0,
                         "planner_requested":self.config.planner, "planner_used":None, "model_calls":[]})

    def get_publication_status(self, session_id, request_id):
        """Read commit facts even when checkpoint restoration is blocked."""
        from .session.publication_store import PublicationStore
        with self.store.lock(session_id):
            return PublicationStore(self.store.directory(session_id)).read(request_id)

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

    def reconcile_scene_and_robot_state(self, session_id, *, confirmed_scene, confirmed_arms,
                                        source_request_id, robot_setup_revision, source="external"):
        with self.store.lock(session_id):
            session = self.get_session(session_id)
            try:
                return session.reconcile_scene_and_robot_state(confirmed_scene=confirmed_scene,
                    confirmed_arms=confirmed_arms, source_request_id=source_request_id,
                    robot_setup_revision=robot_setup_revision, source=source)
            finally:
                self._save_session(session_id)

    def confirm_robot_state(self, session_id, state, *, scene_id, scene_version, robot_setup_revision, source="external"):
        with self.store.lock(session_id):
            session = self.get_session(session_id)
            session.confirm_robot_state(state, scene_id=scene_id, scene_version=scene_version,
                                        robot_setup_revision=robot_setup_revision, source=source)
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
        self.pipeline.skill_planner.last_trace = None
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
                report.clarification_question = turn.clarification_question
                report.reply = (turn.clarification_question or "需要澄清任务。") \
                    if turn.status == "clarification_required" else (turn.clarification_question or "不支持该任务。")
            else:
                session.check_turn(turn)
                bindings = None
                initial_robot = None
                initial_edit = None
                initial_profile = None
                active_bootstrapper = self.bootstrapper
                if session.scene is None and turn.turn_kind not in {"scene_query", "session_control"}:
                    stage = "bootstrap"
                    from secrets import randbits
                    from .contracts.robot_setup import RobotSetupRequest
                    setup_request = turn.robot_setup_request
                    if setup_request is None and self.config.robot_profiles.default_single is not None:
                        setup_request = RobotSetupRequest(mode="single")
                    if setup_request is not None:
                        initial_profile = self.config.robot_profiles.resolve(setup_request)
                        active_bootstrapper = self.bootstrapper.for_profile(initial_profile)
                    if turn.turn_kind == "robot_config":
                        if initial_profile is None:
                            raise ValueError("robot_setup_profile_not_registered")
                        template = active_bootstrapper.template_scene.model_copy(update={"scene_id": randbits(self.config.scene_id_bits), "scene_version": 1})
                        session.initialize_scene(template)
                        session.bind_imported_profile(initial_profile)
                        report.scene_created = True
                        report.scene_commit_status = "committed"
                        initial = None
                    else:
                        initial = active_bootstrapper.prepare(turn, scene_id=randbits(self.config.scene_id_bits))
                    report.scene_source = "generated"
                    report.assumptions = initial.assumptions if initial is not None else []
                    if turn.turn_kind == "robot_task":
                        initial_robot = initial
                    elif turn.turn_kind == "scene_edit" and initial is not None:
                        initial_edit = initial
                    elif initial is not None:
                        session.initialize_scene(initial.scene)
                        report.scene_created = True
                        report.scene_commit_status = "committed"
                        bindings = initial.bindings_for(session.scene)
                        if initial_profile is not None:
                            session.bind_imported_profile(initial_profile)
                stage = "processing"
                if initial_edit is not None:
                    result = session.process_initial_edit_turn(request_id, turn, initial_edit.scene,
                        bindings_override=initial_edit.bindings_for(initial_edit.scene),
                        edit_defaults=active_bootstrapper.defaults, profile=initial_profile)
                    report.scene_created = True
                    report.scene_commit_status = "committed"
                elif initial_robot is not None:
                    result = session.process_initial_robot_turn(request_id, turn, initial_robot.scene,
                        bindings_override=initial_robot.bindings_for(initial_robot.scene), profile=initial_profile)
                    report.scene_created = True
                    report.scene_commit_status = "committed"
                else:
                    result = session.process_turn(request_id, turn, bindings_override=bindings,
                                                  edit_defaults=self.defaults if report.scene_created else self._editor_defaults(session))
                if getattr(result, "assumptions", None):
                    report.assumptions.extend(result.assumptions)
                report.run_status = "success"
                if result.robot_setup_was_changed:
                    report.scene_commit_status = "committed"
                if report.scene_created:
                    session.platform_object_ids = ({o.object_id_in_scene for o in active_bootstrapper.template_scene.objects}
                        if active_bootstrapper.template_scene is not None else {self.defaults.table_object_id, self.defaults.robot_object_id})
                if result.commands is not None:
                    report.delivery_status = "commands_exported"
                    report.reply = "已生成任务计划，尚未执行。"
                elif result.robot_setup_changed is not None:
                    report.delivery_status = "robot_configured"
                    report.reply = ("机器人配置已更新（未执行机器人动作）。" if result.robot_setup_was_changed or report.scene_created
                                    else "已是该机器人配置，场景未改变。")
                elif result.scene_patch is not None or result.scene_replacement is not None:
                    report.delivery_status = "scene_updated"
                    report.scene_commit_status = "committed"
                    report.reply = "场景元数据已更新（未运行仿真）。"
                    default_choices = [item for item in report.assumptions
                                       if item.startswith("source=default_asset:")]
                    alternatives = [item for item in report.assumptions
                                    if item.startswith("alternatives=")]
                    if default_choices:
                        report.reply += " 已按默认样式放置；如需其他款式，请说明颜色或款式。"
                        if alternatives:
                            report.reply += " 当前还有候选：" + alternatives[0].split("=", 1)[1] + "。"
                elif result.scene_query_result is not None:
                    query = result.scene_query_result
                    report.delivery_status = "answered"
                    if query.reply:
                        report.reply = query.reply
                    elif query.query_type == "count":
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
            from .scene.user_feedback import explain_issue
            explain_issue(report.error, exc, session.scene, self.assets)
            report.run_status = "blocked" if report.error.code.startswith(("scene_required", "grounding_", "bootstrap_", "asset_", "holding_", "plan_", "capability_", "dialogue_", "motion_", "execution_pending", "session_paused", "scene_sync_", "scene_reference_", "semantic_protocol")) else "failed"
            if report.error.code.startswith("scene_scale_") or report.error.code == "scene_edit_color_unknown":
                report.run_status = "blocked"
            if report.error.code == "scene_edit_color_unknown":
                report.error.clarification_question = "请提供明确的颜色名称或 #RRGGBB / #RRGGBBAA。"
            if report.error.clarification_question:
                report.run_status = "blocked"
                report.turn_status = TurnStatus.CLARIFICATION_REQUIRED
                report.clarification_question = report.error.clarification_question
            report.reply = report.error.clarification_question or report.error.message
            if session.sync_state == "unknown":
                report.scene_commit_status = "unknown"
        if session.scene is not None:
            report.scene_id, report.scene_version = session.scene.scene_id, session.scene.scene_version
        current_calls = getattr(self.provider,"calls",[])[calls_start:]
        planning_trace = self.pipeline.skill_planner.last_trace
        report.metrics = {"understanding_calls":understanding_calls,
                          "skill_planning_calls":planning_trace.model_calls if planning_trace else 0,
                          "planner_requested":self.config.planner,
                          "planner_used":planning_trace.used_planner if planning_trace else None,
                          "vision_calls":sum(call.get("stage") == "vision_grounding" for call in current_calls),
                          "elapsed_seconds":time.monotonic()-started,
                          "model_calls":current_calls}
        previous_config = getattr(session, "restored_config_fingerprint", None)
        if previous_config and previous_config != self.config_fingerprint:
            report.assumptions.append("configuration_changed_since_restore: confirmed scene retained; review deployment metadata")
        record = {"instruction":instruction, "provider":self.config.provider,
                  "turn_kind":report.turn_kind, "turn_status":report.turn_status,
                  "config":self.config_summary, "config_fingerprint":self.config_fingerprint,
                  "restored_config_fingerprint":previous_config,
                  "scene_source":report.scene_source, "before_version":before.scene_version if before else None,
                  "after_version":report.scene_version}
        if result is not None and result.scene_replacement is not None and result.scene_source_snapshot is not None:
            record.update(scene_basis="original", source_snapshot=result.scene_source_snapshot,
                          id_remap={str(k): v for k, v in result.scene_id_remap.items()})
        record.update(robot_setup=session.robot_setup.model_dump(mode="json") if session.robot_setup else None,
                      robot_setup_revision=session.robot_setup_revision)
        secret = self.config.api_key.get_secret_value() if self.config.api_key else None
        if self.config.debug:
            if planning_trace is not None:
                debug.update(planning_trace.debug_payload())
                if planning_trace.model_calls and "raw_skill_plan" not in debug:
                    raw_values = getattr(self.provider, "last_raw_values", {})
                    raw_text = getattr(self.provider, "last_raw_text", {})
                    if "skill_planning" in raw_values:
                        debug["raw_skill_plan"] = raw_values["skill_planning"]
                    elif "skill_planning" in raw_text:
                        debug["raw_skill_plan"] = {"text": raw_text["skill_planning"]}
                    else:
                        debug["raw_skill_plan"] = {"available": False, "reason": "No model response received"}
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
        from .session.publication_store import PublicationStore
        publication = PublicationStore(self.store.directory(session_id))
        publication_record = {"request_id": request_id, "session_id": session_id,
            "scene_commit_status": report.scene_commit_status, "scene_id": report.scene_id,
            "scene_version": report.scene_version, "snapshot_id": None, "publication_status": "pending",
            "checkpoint_revision": self.revisions.get(session_id, 0) + 1}
        try:
            publication.write(publication_record)
            # Save the confirmed scene before freezing/publishing derived files.
            # A later crash must not cause the next turn to invent a new scene.
            self._save_session(session_id)
            if report.run_status == "success" and session.scene is not None and session.original_scene_manifest is None:
                self._capture_original(session_id, request_id=request_id, source=report.scene_source)
            self._save_session(session_id)
            publication_record["snapshot_id"] = session.original_scene_manifest.snapshot_id if session.original_scene_manifest else None
            publication.write(publication_record)
            published = self.writer.publish(report, scene=session.scene, result=result,
                                            request_record=redact(record, secret), debug=redact(debug, secret))
            publication_record["publication_status"] = "published"
            publication.write(publication_record)
            return published
        except Exception as exc:
            publication_record["publication_status"] = "failed"
            publication_record["snapshot_id"] = session.original_scene_manifest.snapshot_id if session.original_scene_manifest else None
            try:
                publication.write(publication_record)
            except Exception:
                report.assumptions.append("publication_status_not_durable: storage unavailable; inspect external platform before retry")
            report.run_status = "failed"
            report.delivery_status = "none"
            report.artifacts = {}
            report.error = BrainIssue(code="artifact_write_failed", stage="publication", message=str(exc))
            report.reply = "产物保存失败；场景提交状态：" + report.scene_commit_status
            report.assumptions.append("query_commit: get_publication_status(session_id, request_id); do not replay robot commands")
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
