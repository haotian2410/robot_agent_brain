from ..contracts.camera import CameraRequest
from ..contracts.commands import ExecutionFeedback, canonical_commands
from ..contracts.scene import SceneConfig
from ..scene.scene_manager import SceneManager
from .dialogue_state import DialogueState

class BrainSession:
    """Local semantic state commits only after platform acknowledgement."""
    def __init__(self, scene, pipeline, platform, *, robot_profiles=None, reference_registry=None):
        self.scene_manager = None
        self.scene_id_bits = 53
        self.seen_scene_object_ids = set()
        self.next_scene_object_id = 0
        self.pipeline, self.platform = pipeline, platform
        self.robot_profiles = robot_profiles
        from ..scene.component_reference_registry import ComponentReferenceRegistry
        self.reference_registry = reference_registry or ComponentReferenceRegistry()
        self.dialogue = DialogueState()
        self.session_action = None
        self.sync_state = "synchronized"
        self.holding_object = None
        self.robot_setup = None
        self.robot_setup_revision = 0
        self.arm_states = None
        self.original_scene_manifest = None
        self.platform_object_ids = None
        self.original_store = None
        self.scene_reset_allowed = False
        self.profile_object_map = None
        self.last_request_id = None
        self.last_exported_request = None
        self.exported_commands = {}
        self.dispatched_requests = set()
        self.pending_commands = None
        self.pending_execution_request = None
        self.recovery_context = None
        if scene is not None:
            self.initialize_scene(scene)

    @property
    def scene(self):
        return self.scene_manager.scene.model_copy(deep=True) if self.scene_manager else None

    def require_scene(self):
        if self.scene is None:
            raise ValueError("scene_required")
        return self.scene

    def initialize_scene(self, scene):
        if self.pending_execution_request is not None:
            raise ValueError("execution_pending")
        candidate = self._candidate_manager(scene)
        try:
            self._check_snapshot(self.platform.load_scene(candidate.scene), candidate.scene)
        except Exception:
            self.sync_state = "unknown"
            raise
        self._commit_manager(candidate)
        self.sync_state = "synchronized"
        self.dialogue = DialogueState()
        self.holding_object = None
        # A generic import is not proof that the old deployed bindings still
        # apply. Restore/configuration paths must explicitly supply them again.
        self.robot_setup = None
        self.robot_setup_revision = 0
        self.arm_states = None
        self.platform_object_ids = None
        self.profile_object_map = None
        self.exported_commands.clear()
        self.last_exported_request = None
        self.last_request_id = None

        self.recovery_context = None

    def _candidate_manager(self, scene):
        self._validate_identity_range(scene)
        current = {obj.object_id_in_scene for obj in self.scene.objects} if self.scene else set()
        incoming = {obj.object_id_in_scene for obj in scene.objects}
        retired = self.seen_scene_object_ids - current
        if incoming & retired:
            raise ValueError("scene_object_id_reused")
        return SceneManager(scene, seen_scene_object_ids=self.seen_scene_object_ids,
                            next_scene_object_id=self.next_scene_object_id)

    def _validate_identity_range(self, scene):
        limit = 2 ** self.scene_id_bits
        if scene.scene_id >= limit or scene.scene_version >= limit or any(o.object_id_in_scene >= limit for o in scene.objects):
            raise ValueError("scene_identity_range_unsupported")

    def accept_browser_scene(self, candidate, *, platform_object_ids):
        """Accept an editor snapshot, never execute/reset or confirm robot state."""
        from ..web.protocol import digest
        from ..scene.component_access import SceneIndex
        if self.pending_execution_request is not None or self.sync_state != "synchronized":
            raise ValueError("browser_sync_execution_state_blocked")
        if self.holding_object is not None or (self.arm_states and any(
                not a.state_known or a.holding_object is not None for a in self.arm_states.arms.values())):
            raise ValueError("browser_sync_robot_not_idle")
        self.reference_registry.validate_scene(candidate)
        manager = self._candidate_manager(candidate)
        known = {o.object_id_in_scene for o in candidate.objects}
        if not set(platform_object_ids) <= known:
            raise ValueError("scene_platform_manifest_invalid")
        current = self.scene
        changed = current is None or digest(current) != digest(candidate)
        if current is not None:
            if candidate.scene_id != current.scene_id:
                raise ValueError("browser_new_session_required")
            if candidate.scene_version < current.scene_version or (changed and candidate.scene_version == current.scene_version):
                raise ValueError("browser_scene_version_conflict")
            old_index, new_index = SceneIndex(current), SceneIndex(candidate)
            for obj in current.objects:
                identifier = obj.object_id_in_scene
                if identifier in known and old_index.metadata_ref_properties(identifier) != new_index.metadata_ref_properties(identifier):
                    raise ValueError("browser_asset_replacement_requires_new_id")
                if identifier in (self.platform_object_ids or set()):
                    if identifier not in known:
                        raise ValueError("browser_platform_rebind_required")
                    def static(value):
                        data = value.model_dump(mode="json")
                        for c in data["components"]:
                            if c["component_type"] == "RobotDriver":
                                c["properties"].pop("now_joint_positions_rad", None)
                        return data
                    if static(obj) != static(new_index.object(identifier)):
                        raise ValueError("browser_platform_rebind_required")
            old_ids = {o.object_id_in_scene for o in current.objects}
            if any(i < self.next_scene_object_id for i in known - old_ids):
                raise ValueError("scene_object_id_reused")
            if any(SceneIndex(candidate).robot_driver(i) is not None for i in known - old_ids):
                raise ValueError("browser_platform_rebind_required")
        self._check_snapshot(self.platform.adopt(candidate), candidate)
        manager.next_scene_object_id = max(manager.next_scene_object_id, self.platform.next_object_id)
        self._commit_manager(manager)
        if current is None:
            self.platform_object_ids = set(platform_object_ids)
        if changed:
            self.dialogue.last_entity_ids = [i for i in self.dialogue.last_entity_ids if i in known]
            if self.dialogue.last_entity_id not in known:
                self.dialogue.last_entity_id = None
            self.exported_commands.clear()
            self.last_exported_request = self.last_request_id = None
        return changed

    def _commit_manager(self, manager):
        self.scene_manager = manager
        self.seen_scene_object_ids = set(manager.seen_scene_object_ids)
        self.next_scene_object_id = manager.next_scene_object_id

    @staticmethod
    def _check_snapshot(snapshot, expected):
        if not snapshot.accepted:
            raise ValueError(snapshot.error or "scene_platform_rejected_patch")
        if (snapshot.scene_id, snapshot.scene_version) != (expected.scene_id, expected.scene_version):
            raise ValueError("scene_platform_snapshot_mismatch")

    def apply_scene_patch(self, patch):
        if self.pending_execution_request is not None:
            raise ValueError("execution_pending")
        if self.robot_setup is not None and self.robot_setup.mode == "dual":
            if self.arm_states is None:
                raise ValueError("robot_runtime_state_unknown")
            self.arm_states.require_idle(self.robot_setup)
        candidate = self._candidate_manager(self.require_scene())
        candidate_scene = candidate.apply_patch(patch)
        self._validate_identity_range(candidate_scene)
        try:
            snapshot = self.platform.apply_patch(patch)
        except Exception:
            self.sync_state = "unknown"
            raise
        try:
            self._check_snapshot(snapshot, candidate_scene)
        except Exception:
            self.sync_state = "unknown"
            raise
        self.sync_state = "synchronized"
        self._commit_manager(candidate)
        return self.scene

    def capture(self, request=None):
        self.require_scene()
        frame = self.platform.capture(request or CameraRequest())
        if (frame.scene_id, frame.scene_version) != (self.scene.scene_id, self.scene.scene_version):
            raise ValueError("camera_frame_scene_mismatch")
        return frame

    def run_task(self, request_id, instruction):
        if self.session_action == "close":
            raise ValueError("session_closed")
        turn = self.pipeline.understand_turn(instruction, scene=self.scene, dialogue=self.dialogue)
        return self.process_turn(request_id, turn)

    def check_turn(self, turn):
        if turn.scene_edit is not None and turn.scene_edit.scene_basis == "original" and self.original_scene_manifest is None:
            raise ValueError("original_scene_unavailable")
        if turn.robot_setup_request is not None:
            if self.robot_profiles is None:
                raise ValueError("robot_setup_profile_not_registered")
            self.robot_profiles.resolve(turn.robot_setup_request)
        elif self.robot_setup is None or self.robot_setup.mode != "dual":
            turn.require_legacy_execution()
        elif turn.turn_kind == "scene_edit":
            if self.arm_states is None:
                raise ValueError("robot_runtime_state_unknown")
            self.arm_states.require_idle(self.robot_setup)
        if self.session_action == "close":
            raise ValueError("session_closed")
        if self.sync_state != "synchronized" and turn.turn_kind != "session_control":
            raise ValueError("scene_sync_unknown")
        if self.pending_execution_request is not None and turn.turn_kind != "session_control":
            raise ValueError("execution_pending")
        if self.session_action == "pause" and (turn.session_control is None or turn.session_control.action not in {"resume", "close"}):
            raise ValueError("session_paused")

    def process_turn(self, request_id, turn, *, bindings_override=None, edit_defaults=None):
        self.check_turn(turn)
        if turn.robot_setup_request is not None:
            return self._process_setup_turn(request_id, turn, bindings_override=bindings_override)
        if turn.scene_edit is not None and turn.scene_edit.scene_basis == "original":
            from ..pipeline import BrainResult
            if self.original_store is None:
                raise ValueError("original_scene_unavailable")
            if any(e.dialogue_ref or e.dialogue_ref_set for e in turn.scene_edit.entities):
                raise ValueError("original_scene_dialogue_reference_ambiguous")
            result = None
            def edit(original):
                nonlocal result
                result = self.pipeline.scene_editor.edit_result(
                    turn.scene_edit.model_copy(update={"scene_basis": "current"}), original,
                    next_scene_object_id=max(self.next_scene_object_id, max((o.object_id_in_scene for o in original.objects), default=-1)+1))
                return SceneManager(original, next_scene_object_id=max(self.next_scene_object_id,
                    max((o.object_id_in_scene for o in original.objects), default=-1)+1)).apply_patch(result.patch)
            remapped = self.derive_original_scene(self.original_store, edit, reset_allowed=self.scene_reset_allowed)
            final = BrainResult(turn_kind="scene_edit", scene_replacement=remapped.scene,
                scene_source_snapshot=self.original_scene_manifest.snapshot_id, scene_id_remap=remapped.id_map,
                focus_object_ids=[remapped.id_map[i] for i in result.focus_object_ids])
            self.dialogue.observe(final)
            return final
        profile = None
        if self.robot_setup is not None:
            from ..contracts.robot_setup import RobotSetupRequest
            if self.robot_profiles is None:
                raise ValueError("robot_setup_profile_not_registered")
            profile = self.robot_profiles.resolve(RobotSetupRequest(mode=self.robot_setup.mode, profile_id=self.robot_setup.profile_id))
            profile.validate_scene(self.require_scene(), self.robot_setup)
            profile = profile.model_copy(update={"setup": self.robot_setup.model_copy(deep=True)})
        result = self.pipeline.process_turn(request_id, turn, self.scene,
                                           dialogue=self.dialogue, capture=self.capture,
                                           held_object=self.holding_object, bindings_override=bindings_override, edit_defaults=edit_defaults,
                                           seen_scene_object_ids=self.seen_scene_object_ids,
                                           next_scene_object_id=self.next_scene_object_id,
                                           robot_profile=profile, robot_setup_revision=self.robot_setup_revision, arm_states=self.arm_states)
        return self._accept_result(request_id, result)

    def _process_setup_turn(self, request_id, turn, *, bindings_override=None):
        from ..pipeline import BrainResult
        from ..contracts.robot_setup import RobotSetupRequest
        target = self.robot_profiles.resolve(turn.robot_setup_request)
        if self.robot_setup is None or self.profile_object_map is None:
            raise ValueError("robot_setup_current_mapping_unavailable")
        if request_id in self.exported_commands or request_id in self.dispatched_requests:
            raise ValueError("request_id_reused")
        if target.setup.profile_id == self.robot_setup.profile_id:
            if turn.turn_kind == "robot_config":
                return BrainResult(turn_kind="robot_config", robot_setup_changed=self.robot_setup)
            return self.process_turn(request_id, turn.model_copy(update={"robot_setup_request": None}), bindings_override=bindings_override)
        old = self.robot_profiles.resolve(RobotSetupRequest(mode=self.robot_setup.mode, profile_id=self.robot_setup.profile_id))
        anchors = target.platform_object_ids - target.robot_object_ids
        if set(target.platform_roles.values()) != anchors:
            raise ValueError("robot_setup_platform_roles_incomplete")
        bindings = {}
        for role, identifier in target.platform_roles.items():
            if role not in old.platform_roles or old.platform_roles[role] not in self.profile_object_map:
                raise ValueError("robot_setup_platform_role_unbound: " + role)
            bindings[identifier] = self.profile_object_map[old.platform_roles[role]]
        def plan(prepared, state, revision):
            return self.pipeline.process_turn(request_id, turn.model_copy(update={"robot_setup_request": None}), prepared.scene,
                dialogue=self.dialogue, bindings_override=bindings_override,
                robot_profile=target.model_copy(update={"setup": prepared.setup}),
                robot_setup_revision=revision, arm_states=state)
        prepared, result = self.switch_robot_setup(target, platform_bindings=bindings,
            plan_candidate=plan if turn.turn_kind == "robot_task" else None)
        if result is None:
            return BrainResult(turn_kind="robot_config", robot_setup_changed=prepared.setup, robot_setup_was_changed=True)
        result = result.model_copy(update={"robot_setup_changed": prepared.setup, "robot_setup_was_changed": True})
        return self._accept_result(request_id, result)

    def bind_imported_profile(self, profile):
        """Bind an explicitly configured imported scene; not a robot replacement.

        Initial state is a deployment declaration, not measured Control evidence.
        Absence remains unknown and blocks planning/dispatch.
        """
        from ..contracts.robot_setup import RobotRuntimeState, ArmRuntimeState
        if self.robot_setup is not None or self.pending_execution_request is not None or self.holding_object is not None:
            raise ValueError("robot_profile_binding_requires_fresh_import")
        profile.validate_scene(self.require_scene())
        self.robot_setup = profile.setup.model_copy(deep=True)
        self.robot_setup_revision = 1
        self.platform_object_ids = set(profile.platform_object_ids)
        self.profile_object_map = {i: i for i in profile.platform_object_ids}
        self.arm_states = (profile.initial_state.model_copy(deep=True) if profile.initial_state is not None else
                           RobotRuntimeState(arms={side: ArmRuntimeState(state_known=False) for side in self.robot_setup.arms}))

    def switch_robot_setup(self, target_profile, *, platform_bindings, plan_candidate=None):
        """Prepare, optionally plan, then ACK and commit the robot-only candidate."""
        from ..scene.robot_setup_manager import RobotSetupManager
        from ..contracts.robot_setup import RobotSetupRequest, RobotRuntimeState, ArmRuntimeState
        if self.pending_execution_request is not None:
            raise ValueError("execution_pending")
        if self.sync_state != "synchronized" or self.session_action in {"pause", "close"}:
            raise ValueError("session_not_ready_for_robot_switch")
        if self.robot_setup is None or self.robot_profiles is None or self.profile_object_map is None:
            raise ValueError("robot_setup_current_mapping_unavailable")
        if self.arm_states is None:
            raise ValueError("robot_runtime_state_unknown")
        self.arm_states.require_idle(self.robot_setup)
        current_profile = self.robot_profiles.resolve(RobotSetupRequest(mode=self.robot_setup.mode, profile_id=self.robot_setup.profile_id))
        if not current_profile.robot_object_ids <= set(self.profile_object_map):
            raise ValueError("robot_setup_current_mapping_unavailable")
        prepared = RobotSetupManager(reference_registry=self.reference_registry).prepare(self.require_scene(),
            current_robot_ids={self.profile_object_map[i] for i in current_profile.robot_object_ids},
            target_profile=target_profile, platform_bindings=platform_bindings, next_object_id=self.next_scene_object_id)
        initial = (target_profile.initial_state.model_copy(deep=True) if target_profile.initial_state is not None else
                   RobotRuntimeState(arms={side: ArmRuntimeState(state_known=False) for side in prepared.setup.arms}))
        revision = self.robot_setup_revision + 1
        # No live mutation before the entire optional task plan is validated.
        result = plan_candidate(prepared, initial, revision) if plan_candidate is not None else None
        manager = self._candidate_manager(prepared.scene)
        try:
            self._check_snapshot(self.platform.load_scene(prepared.scene), prepared.scene)
        except Exception:
            self.sync_state = "unknown"
            raise
        self._commit_manager(manager)
        self.robot_setup = prepared.setup
        surviving = {obj.object_id_in_scene for obj in prepared.scene.objects}
        focus = self.dialogue.last_entity_ids or ([self.dialogue.last_entity_id] if self.dialogue.last_entity_id is not None else [])
        self.dialogue.last_entity_ids = [identifier for identifier in focus if identifier in surviving]
        self.dialogue.last_entity_id = self.dialogue.last_entity_ids[0] if len(self.dialogue.last_entity_ids) == 1 else None
        self.robot_setup_revision = revision
        self.arm_states = initial
        self.holding_object = None
        self.platform_object_ids = (set(self.platform_object_ids or ()) - {self.profile_object_map[i] for i in current_profile.robot_object_ids}) | prepared.robot_object_ids
        self.profile_object_map = dict(prepared.template_id_map)
        self.exported_commands.clear()
        self.last_exported_request = None
        self.last_request_id = None
        self.sync_state = "synchronized"
        return prepared, result

    def confirm_robot_state(self, state, *, scene_id, scene_version, robot_setup_revision, source="external"):
        """Explicit external confirmation after import/reset; never a model guess."""
        from ..contracts.robot_setup import RobotRuntimeState
        if self.pending_execution_request is not None:
            raise ValueError("execution_pending")
        if self.sync_state != "synchronized" or self.robot_setup is None:
            raise ValueError("robot_state_confirmation_requires_synchronized_scene")
        scene = self.require_scene()
        if (scene_id, scene_version, robot_setup_revision) != (scene.scene_id, scene.scene_version, self.robot_setup_revision):
            raise ValueError("robot_state_confirmation_stale")
        if source not in {"external", "simulated"}:
            raise ValueError("execution_feedback_source_invalid")
        state = RobotRuntimeState.model_validate(state.model_dump() if hasattr(state, "model_dump") else state)
        if set(state.arms) != set(self.robot_setup.arms):
            raise ValueError("robot_runtime_arm_mapping_invalid")
        held = [a.holding_object for a in state.arms.values() if a.holding_object is not None]
        if not set(held) <= {o.object_id_in_scene for o in scene.objects} or len(held) != len(set(held)):
            raise ValueError("robot_state_confirmation_holding_invalid")
        self.arm_states = state.model_copy(deep=True)
        self.holding_object = state.arms["single"].holding_object if self.robot_setup.mode == "single" else None
        self.last_feedback_source = source
        # Old plans were derived from different initial state evidence.
        self.exported_commands.clear()
        self.last_exported_request = None
        self.last_request_id = None

    def reconcile_scene_and_robot_state(self, *, confirmed_scene, confirmed_arms,
                                        source_request_id, robot_setup_revision, source="external"):
        """Trusted adapter API, not natural-language confirmation or execution.

        The adapter must authenticate its measurements. This in-process API
        validates provenance/versions but is not an authentication boundary.
        """
        from ..contracts.robot_setup import RobotRuntimeState
        if confirmed_scene is None:
            raise ValueError("authoritative_scene_required")
        if source not in {"external", "simulated"}:
            raise ValueError("execution_feedback_source_invalid")
        if self.pending_execution_request is not None:
            raise ValueError("execution_pending")
        context = self.recovery_context
        if (context is None or source_request_id != context.request_id
                or source_request_id not in self.dispatched_requests or source != context.source):
            raise ValueError("execution_recovery_source_unproven")
        if (self.robot_setup is None or self.robot_setup.mode != "dual"
                or robot_setup_revision != self.robot_setup_revision
                or robot_setup_revision != context.robot_setup_revision):
            raise ValueError("execution_robot_setup_mismatch")
        scene = self.require_scene()
        candidate = SceneConfig.model_validate(confirmed_scene.model_dump() if hasattr(confirmed_scene, "model_dump") else confirmed_scene)
        if candidate.scene_id != context.scene_id or candidate.scene_version < context.minimum_scene_version:
            raise ValueError("execution_recovery_scene_mismatch")
        self._validate_execution_scene(candidate, kind="recovery")
        known = {o.object_id_in_scene for o in candidate.objects}
        state = RobotRuntimeState.model_validate(confirmed_arms.model_dump() if hasattr(confirmed_arms, "model_dump") else confirmed_arms)
        if set(state.arms) != set(self.robot_setup.arms) or any(not a.state_known for a in state.arms.values()):
            raise ValueError("robot_runtime_state_unknown")
        held = [a.holding_object for a in state.arms.values() if a.holding_object is not None]
        if not set(held) <= known or len(held) != len(set(held)):
            raise ValueError("robot_state_confirmation_holding_invalid")
        manager = self._candidate_manager(candidate)
        # Once platform I/O begins, a timeout may mean it accepted the load.
        # Keep provenance and unknown state for retry; never claim rollback.
        self.sync_state = "unknown"
        self.recovery_context = context.model_copy(update={"minimum_scene_version": candidate.scene_version})
        self._check_snapshot(self.platform.load_scene(candidate), candidate)
        self._commit_manager(manager)
        self.arm_states = state.model_copy(deep=True)
        self.sync_state = "synchronized"
        self.last_feedback_source = source
        self.recovery_context = None
        self.exported_commands.clear()
        self.last_exported_request = None
        self.last_request_id = None

    def derive_original_scene(self, original_store, transform, *, reset_allowed=False):
        """Commit a validated edit of the immutable original via one platform load.

        This is a scene-platform reset, not physical robot execution. The edit
        callback must perform its own geometry checks before returning a Scene.
        Restored arms remain unknown until the external platform confirms state.
        """
        from secrets import randbits
        from ..scene.id_remapper import remap_scene
        from ..contracts.robot_setup import RobotRuntimeState, ArmRuntimeState
        if not reset_allowed:
            raise ValueError("original_scene_reset_not_permitted")
        if self.pending_execution_request is not None:
            raise ValueError("execution_pending")
        if self.sync_state != "synchronized" or self.session_action in {"pause", "close"}:
            raise ValueError("session_not_ready_for_scene_reset")
        if self.holding_object is not None:
            raise ValueError("robot_runtime_holding_object")
        if self.robot_setup is not None:
            if self.arm_states is None:
                raise ValueError("robot_runtime_state_unknown")
            self.arm_states.require_idle(self.robot_setup)
        if self.original_scene_manifest is None:
            raise ValueError("original_scene_unavailable")
        original, manifest = original_store.load(self.original_scene_manifest)
        edited = SceneConfig.model_validate(transform(original.model_copy(deep=True)).model_dump())
        identifier = randbits(self.scene_id_bits)
        while identifier in {original.scene_id, self.require_scene().scene_id}:
            identifier = randbits(self.scene_id_bits)
        remapped = remap_scene(edited, new_scene_id=identifier, next_object_id=self.next_scene_object_id,
                              reference_registry=self.reference_registry,
                               robot_setup=manifest.robot_setup)
        if not set(manifest.platform_object_ids) <= set(remapped.id_map):
            raise ValueError("original_scene_platform_object_removed")
        manager = self._candidate_manager(remapped.scene)
        try:
            self._check_snapshot(self.platform.load_scene(remapped.scene), remapped.scene)
        except Exception:
            self.sync_state = "unknown"
            raise
        self._commit_manager(manager)
        self.robot_setup = remapped.robot_setup
        self.profile_object_map = ({int(k): remapped.id_map[v] for k, v in manifest.profile_object_map.items()}
                                   if manifest.profile_object_map is not None else None)
        self.robot_setup_revision = self.robot_setup_revision + 1 if remapped.robot_setup is not None else 0
        self.arm_states = (RobotRuntimeState(arms={side: ArmRuntimeState(state_known=False) for side in remapped.robot_setup.arms})
                           if remapped.robot_setup is not None else None)
        self.platform_object_ids = {remapped.id_map[i] for i in manifest.platform_object_ids}
        self.dialogue = DialogueState()
        self.exported_commands.clear()
        self.last_exported_request = None
        self.last_request_id = None
        self.sync_state = "synchronized"
        return remapped

    def process_initial_robot_turn(self, request_id, turn, scene, *, bindings_override, profile=None):
        """Plan against a prospective bootstrap; load it only after validation.

        Bootstrap supplies complete instance bindings, so this path needs no
        rendered vision fallback. Never load a scene for a failed planner.
        """
        self.check_turn(turn)
        if self.scene is not None or turn.turn_kind != "robot_task" or turn.status != "accepted":
            raise ValueError("initial_robot_turn_required")
        if profile is not None:
            from ..contracts.robot_setup import RobotRuntimeState, ArmRuntimeState
            profile.validate_scene(scene)
            state = profile.initial_state or RobotRuntimeState(arms={side: ArmRuntimeState(state_known=False) for side in profile.setup.arms})
            result = self.pipeline.process_turn(request_id, turn.model_copy(update={"robot_setup_request": None}), scene,
                bindings_override=bindings_override, robot_profile=profile, robot_setup_revision=1, arm_states=state)
        else:
            result = self.pipeline.process_turn(request_id, turn, scene, bindings_override=bindings_override)
        self.initialize_scene(scene)
        if profile is not None:
            self.bind_imported_profile(profile)
        return self._accept_result(request_id, result)

    def _accept_result(self, request_id, result):
        if self.session_action == "pause":
            if result.session_action is None or result.session_action.action not in {"resume", "close"}:
                raise ValueError("session_paused")
        if result.commands is not None:
            if request_id in self.exported_commands or request_id in self.dispatched_requests:
                raise ValueError("request_id_reused")
            self.exported_commands[request_id] = canonical_commands(result.commands)
            self.last_exported_request = request_id
            self.last_request_id = request_id
        if result.scene_patch is not None:
            if self.holding_object is not None and any(op.object_id_in_scene == self.holding_object for op in result.scene_patch.operations):
                raise ValueError("scene_edit_held_object_conflict")
            self.apply_scene_patch(result.scene_patch)
        if result.session_action is not None:
            self.session_action = result.session_action.action
        self.dialogue.observe(result)
        return result

    def mark_dispatched(self, commands):
        if self.pending_execution_request is not None:
            raise ValueError("execution_pending")
        if self.sync_state != "synchronized" or self.session_action in {"pause", "close"}:
            raise ValueError("session_not_ready_for_dispatch")
        scene = self.require_scene()
        if commands.schema_version == "3.0":
            if commands.robot_setup != self.robot_setup or commands.robot_setup_revision != self.robot_setup_revision:
                raise ValueError("execution_robot_setup_mismatch")
            if self.arm_states is None or any(not arm.state_known for arm in self.arm_states.arms.values()):
                raise ValueError("robot_runtime_state_unknown")
            from ..contracts.robot_setup import RobotSetupRequest
            from ..planning.dual_capability import validate_dual_capability
            if self.robot_profiles is None:
                raise ValueError("robot_setup_profile_not_registered")
            profile = self.robot_profiles.resolve(RobotSetupRequest(mode="dual", profile_id=self.robot_setup.profile_id))
            if self.profile_object_map is None or any(
                    self.profile_object_map.get(binding.robot_object_id) != self.robot_setup.arms[side].robot_object_id
                    for side, binding in profile.setup.arms.items()):
                raise ValueError("execution_robot_setup_mismatch")
            profile.validate_scene(scene, self.robot_setup)
            validate_dual_capability(commands, profile)
        elif self.robot_setup is not None and self.robot_setup.mode == "dual":
            raise ValueError("execution_commands_version_mismatch")
        if (commands.scene_id, commands.scene_version) != (scene.scene_id, scene.scene_version):
            raise ValueError("execution_scene_mismatch")
        payload = canonical_commands(commands)
        if commands.request_id in self.dispatched_requests or self.exported_commands.get(commands.request_id) != payload:
            raise ValueError("execution_not_exported_by_session")
        self.pending_commands = payload
        self.pending_execution_request = commands.request_id
        self.dispatched_requests.add(commands.request_id)

    def apply_execution_feedback(self, feedback: ExecutionFeedback, *, confirmed_scene=None, feedback_source="external"):
        if self.pending_commands and self.pending_commands["schema_version"] == "3.0":
            from ..contracts.feedback_v3 import ExecutionFeedbackV3
            if not isinstance(feedback, ExecutionFeedbackV3):
                raise ValueError("execution_feedback_version_mismatch")
            return self._apply_dual_feedback(feedback, confirmed_scene=confirmed_scene, feedback_source=feedback_source)
        feedback = ExecutionFeedback.model_validate(feedback.model_dump())
        if self.pending_execution_request != feedback.request_id:
            raise ValueError("execution_feedback_stale_or_unknown_request")
        expected = {c["command_id"] for c in self.pending_commands["commands"]}
        actual = [c.command_id for c in feedback.commands]
        if len(actual) != len(set(actual)) or not set(actual) <= expected:
            raise ValueError("execution_feedback_command_mismatch")
        if feedback.status == "success" and (set(actual) != expected or any(c.status != "success" for c in feedback.commands)):
            raise ValueError("execution_feedback_incomplete_success")
        scene = self.require_scene()
        if feedback.holding_object is not None and feedback.holding_object not in {o.object_id_in_scene for o in scene.objects}:
            raise ValueError("execution_feedback_holding_unknown")
        candidate = None
        if confirmed_scene is not None:
            candidate = SceneConfig.model_validate(confirmed_scene.model_dump())
            if candidate.scene_id != scene.scene_id or candidate.scene_version <= scene.scene_version:
                raise ValueError("execution_feedback_scene_mismatch")
            if feedback.holding_object is not None and feedback.holding_object not in {o.object_id_in_scene for o in candidate.objects}:
                raise ValueError("execution_feedback_holding_unknown")
        if feedback_source not in {"external", "simulated"}:
            raise ValueError("execution_feedback_source_invalid")
        self.sync_state = "unknown"
        if candidate is not None:
            manager = self._candidate_manager(candidate)
            self._check_snapshot(self.platform.load_scene(candidate), candidate)
            self._commit_manager(manager)
            self.sync_state = "synchronized"
        self.holding_object = feedback.holding_object
        if self.robot_setup is not None and self.robot_setup.mode == "single":
            from ..contracts.robot_setup import RobotRuntimeState
            self.arm_states = RobotRuntimeState(arms={"single": {"state_known": feedback.status == "success",
                                                                  "holding_object": feedback.holding_object}})
        self.last_feedback_source = feedback_source
        self.pending_execution_request = None
        self.pending_commands = None
        return feedback.status

    def _validate_execution_scene(self, candidate, *, kind):
        """Validate authoritative snapshots identically before any platform I/O."""
        from ..contracts.robot_setup import RobotSetupRequest
        scene = self.require_scene()
        if candidate.scene_id != scene.scene_id or candidate.scene_version <= scene.scene_version:
            raise ValueError(f"execution_{kind}_scene_mismatch")
        if {o.object_id_in_scene for o in candidate.objects} != {o.object_id_in_scene for o in scene.objects}:
            raise ValueError(f"execution_{kind}_object_set_changed")
        if self.robot_profiles is None or self.robot_setup is None:
            raise ValueError("robot_setup_profile_not_registered")
        profile = self.robot_profiles.resolve(RobotSetupRequest(mode=self.robot_setup.mode,
            profile_id=self.robot_setup.profile_id))
        profile.validate_scene(candidate, self.robot_setup)
        from ..scene.component_access import SceneIndex
        actual, template = SceneIndex(candidate), SceneIndex(profile.template)
        for side, arm in self.robot_setup.arms.items():
            expected_id = profile.setup.arms[side].robot_object_id
            if actual.robot_driver(arm.robot_object_id).deployment_configuration() != template.robot_driver(expected_id).deployment_configuration():
                raise ValueError("robot_profile_driver_configuration_mismatch")
        self.reference_registry.validate_scene(candidate)

    def _apply_dual_feedback(self, feedback, *, confirmed_scene=None, feedback_source="external"):
        from ..contracts.commands import parse_commands
        from ..contracts.feedback_v3 import ExecutionFeedbackV3
        from ..contracts.robot_setup import RobotRuntimeState, ArmRuntimeState
        feedback = ExecutionFeedbackV3.model_validate(feedback.model_dump())
        if self.pending_execution_request != feedback.request_id:
            raise ValueError("execution_feedback_stale_or_unknown_request")
        plan = parse_commands(self.pending_commands)
        feedback.validate_against(plan, self.arm_states)
        if plan.robot_setup != self.robot_setup or plan.robot_setup_revision != self.robot_setup_revision:
            raise ValueError("execution_robot_setup_mismatch")
        if feedback_source not in {"external", "simulated"}:
            raise ValueError("execution_feedback_source_invalid")
        scene = self.require_scene()
        candidate = SceneConfig.model_validate(confirmed_scene.model_dump()) if confirmed_scene is not None else None
        if candidate is not None:
            self._validate_execution_scene(candidate, kind="feedback")
        known = {o.object_id_in_scene for o in (candidate or scene).objects}
        if any(a.holding_object is not None and a.holding_object not in known for a in feedback.arms.values()):
            raise ValueError("execution_feedback_holding_unknown")
        if not {a.robot_object_id for a in self.robot_setup.arms.values()} <= known:
            raise ValueError("execution_feedback_robot_missing")
        # Preserve measured partial results even if subsequent scene sync fails.
        # Missing arm feedback is unknown, never copied from its peer or rolled
        # back to the pre-execution empty state.
        self.arm_states = RobotRuntimeState(arms={side: feedback.arms.get(side, ArmRuntimeState(state_known=False))
                                                  for side in ("left", "right")})
        self.sync_state = "unknown"
        self.last_feedback_source = feedback_source
        from ..contracts.feedback_v3 import ExecutionRecoveryContext
        self.recovery_context = ExecutionRecoveryContext(request_id=feedback.request_id, scene_id=scene.scene_id,
            base_scene_version=scene.scene_version, minimum_scene_version=candidate.scene_version if candidate else scene.scene_version + 1,
            robot_setup_revision=self.robot_setup_revision, feedback_status=feedback.status, source=feedback_source)
        self.pending_execution_request = None
        self.pending_commands = None
        if candidate is not None:
            manager = self._candidate_manager(candidate)
            self._check_snapshot(self.platform.load_scene(candidate), candidate)
            self._commit_manager(manager)
            self.sync_state = "synchronized"
            self.recovery_context = None
        return feedback.status
