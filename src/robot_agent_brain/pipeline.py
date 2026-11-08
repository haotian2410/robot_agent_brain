from __future__ import annotations

from collections.abc import Callable
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator

from .contracts.camera import CameraFrame
from .contracts.commands import CommandsFile
from .contracts.commands_v3 import CommandsFileV3
from .contracts.robot_setup import RobotSetup
from .contracts.grounded_task import GroundedTask
from .contracts.scene import SceneConfig, ScenePatch, SceneId
from .contracts.skill_plan import SkillPlan
from .contracts.task_intent import TaskIntent
from .contracts.turn import BrainTurn, SceneQueryIntent, SessionControlIntent, TurnKind, TurnStatus
from .scene.query import SceneQueryEngine, SceneQueryResult
from .scene.editor import SceneEditor
from .grounding.scene_grounder import SceneGrounder, GroundingAmbiguous
from .grounding.vision_fallback import VisionFallbackGrounder
from .models.vision_grounding import VisionEntity
from .models.task_understanding import TaskUnderstandingRequest, normalize_motion_language
from .planning.command_exporter import CommandExporter
from .planning.motion_scale import MotionScaleResolver
from .planning.recipe_planner import RecipePlanner
from .planning.skill_planner_router import SkillPlannerRouter
from .skills.registry import REGISTRY
from .planning.task_expander import TaskExpander
from .semantics.task_domain_policy import TaskDomainPolicy
from .errors import BrainError
from .scene.component_access import SceneIndex
from .adapters.ols_robot_assembly import normalize_robot_platform_name


_QUERY_MARKERS = (
    "有没有", "是否存在", "是否有", "有几个", "多少个", "多少只", "多少件",
    "哪些", "查询", "查一下", "查查", "数一数", "场景中有", "场景里有",
)
_EDIT_MARKERS = (
    "增加", "添加", "生成", "放置", "摆放", "移动", "挪", "删除", "改成",
    "换成", "渲染成", "画成", "旋转", "缩放", "放大", "缩小", "替换", "放进",
    "放到", "移到", "调整",
)


def _canonicalize_query_route(turn: BrainTurn, instruction: str) -> BrainTurn:
    """Prevent an accepted scene-edit payload from mutating a query.

    The model is still the source of the structured entities and relations,
    but the short, unambiguous Chinese query verbs are a protocol safety
    boundary.  This only rewrites an *accepted* scene-edit response when the
    user did not express an edit verb; mixed query/edit sentences remain on
    the model route and are allowed to clarify instead of guessing.
    """
    if turn.status != TurnStatus.ACCEPTED:
        return turn
    text = (instruction or "").casefold()
    if not any(marker in text for marker in _QUERY_MARKERS) or any(marker in text for marker in _EDIT_MARKERS):
        return turn
    if turn.turn_kind == TurnKind.SCENE_EDIT and turn.scene_edit is not None:
        entities = turn.scene_edit.entities
        relations = [relation for relation in turn.scene_edit.relations if relation.scope == "selection"]
    elif (turn.turn_kind == TurnKind.ROBOT_TASK and turn.task_intent is not None
          and not turn.task_intent.operations):
        entities = turn.task_intent.entities
        relations = [relation for relation in turn.task_intent.spatial_relations if relation.scope == "selection"]
    else:
        return turn
    if not entities:
        return BrainTurn(protocol_version=turn.protocol_version,
                         status=TurnStatus.CLARIFICATION_REQUIRED,
                         turn_kind=TurnKind.SCENE_QUERY,
                         instruction=instruction,
                         clarification_question="请明确要查询哪些物体或属性。")
    query_type = "count" if any(marker in text for marker in ("有几个", "多少个", "多少只", "多少件")) else "existence"
    # Preserve only query-compatible selection relations.  A layout relation
    # in a wrongly-routed edit is not evidence for a query and must not be
    # silently reinterpreted.
    try:
        query = SceneQueryIntent(query_type=query_type,
                                 entities=entities,
                                 relations=relations,
                                 target=entities[0].entity_id,
                                 evidence_source="scene")
    except Exception:
        return BrainTurn(protocol_version=turn.protocol_version,
                         status=TurnStatus.CLARIFICATION_REQUIRED,
                         turn_kind=TurnKind.SCENE_QUERY,
                         instruction=instruction,
                         clarification_question="请明确要查询的对象、数量或存在性。")
    return turn.model_copy(update={"turn_kind": TurnKind.SCENE_QUERY,
                                   "scene_edit": None,
                                   "scene_query": query,
                                   "task_intent": None,
                                   "session_control": None,
                                   "robot_setup_request": None})

class BrainResult(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    status: TurnStatus = TurnStatus.ACCEPTED
    turn_kind: TurnKind = TurnKind.ROBOT_TASK
    task_intent: TaskIntent | None = Field(default=None, alias="intent")
    grounded_task: GroundedTask | None = None
    skill_plan: SkillPlan | None = None
    commands: CommandsFile | CommandsFileV3 | None = None
    scene_patch: ScenePatch | None = None
    scene_replacement: SceneConfig | None = None
    scene_source_snapshot: str | None = None
    scene_id_remap: dict[int, int] | None = None
    robot_setup_changed: RobotSetup | None = None
    platform_rebind: dict | None = None
    robot_setup_was_changed: bool = False
    scene_query_result: SceneQueryResult | None = None
    session_action: SessionControlIntent | None = None
    focus_object_ids: list[SceneId] | None = None
    deleted_object_ids: list[SceneId] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    planner_used: Literal["recipe", "qwen"] | None = None
    planner_trace: dict | None = Field(default=None, exclude=True)

    @property
    def intent(self):
        return self.task_intent

    @model_validator(mode="after")
    def turn_payload(self):
        robot_config_payload = self.robot_setup_changed if self.robot_setup_changed is not None else self.platform_rebind
        groups = {
            TurnKind.ROBOT_CONFIG: (robot_config_payload,),
            TurnKind.ROBOT_TASK: (self.task_intent, self.grounded_task, self.skill_plan, self.commands),
            TurnKind.SCENE_EDIT: (self.scene_patch,),
            TurnKind.SCENE_QUERY: (self.scene_query_result,),
            TurnKind.SESSION_CONTROL: (self.session_action,),
        }
        if isinstance(self.commands, CommandsFileV3):
            # A staged v3 plan is not a flattened v2 SkillPlan.
            groups[TurnKind.ROBOT_TASK] = (self.task_intent, self.grounded_task, self.commands)
        if self.turn_kind == TurnKind.ROBOT_TASK and self.robot_setup_changed is not None:
            groups[TurnKind.ROBOT_TASK] = (*groups[TurnKind.ROBOT_TASK], self.robot_setup_changed)
            groups[TurnKind.ROBOT_CONFIG] = ()
        if self.scene_replacement is not None:
            if self.scene_patch is not None:
                raise ValueError("brain_result_patch_and_replacement_exclusive")
            groups[TurnKind.SCENE_EDIT] = (self.scene_replacement,)
        if self.status != TurnStatus.ACCEPTED:
            if any(v is not None for values in groups.values() for v in values):
                raise ValueError("brain_result_rejected_payload")
            return self
        if self.turn_kind not in groups or any(v is None for v in groups[self.turn_kind]):
            raise ValueError("brain_result_payload_missing")
        if any(v is not None for kind, values in groups.items() if kind != self.turn_kind for v in values):
            raise ValueError("brain_result_payload_mismatch")
        return self

class BrainPipeline:
    def __init__(self, understanding, assets, scene_editor=None, vision_provider=None,
                 skill_planning_provider=None, planner_mode="recipe", robot="ur5e", aliases=None,
                 query_near_distance_m=.2, registered_profiles=None,
                 primary_table_metadata_ref=None, workspace_center_m=None,
                 placement_policy_version="grid-v2", motion_policy_version="motion-v1",
                 catalog_for_provider: bool = True):
        self.understanding = understanding
        self.assets = assets
        # This is the configured command/export profile, not a guess from the
        # scene image.  A scene may declare another arm platform; before an
        # explicit RobotProfile is bound we must refuse to export commands
        # rather than silently serializing them as UR5e commands.
        self.robot = robot
        self.query_near_distance_m = query_near_distance_m
        self.aliases = getattr(getattr(assets, "metadata", None), "aliases", {})
        if aliases is not None:
            self.aliases = aliases
        self.registered_profiles = tuple(sorted(set(registered_profiles or ())))
        self.catalog_for_provider = bool(catalog_for_provider)
        # The live provider must see the current adapter-owned catalog data,
        # including human-language aliases that are valid for this exact OLS
        # revision.  ``FinalModelsLibraryAdapter`` reserves canonical names,
        # so a future real ``cup`` asset cannot inherit the mug-only ``cup``
        # alias.  Keep ``self.aliases`` for deterministic grounding of
        # existing scene instances and old replay inputs only.
        # Only the live Qwen transport receives the request-scoped OLS
        # catalog automatically.  Injected HTTP transports are explicit
        # replay/test boundaries and retain the pre-v3 compatibility path;
        # tests that exercise the live contract pass a catalog on the request
        # (or construct the provider with ``live_catalog=True``).
        self.asset_catalog = (assets.catalog_snapshot(aliases=None,
                                                      registered_profiles=self.registered_profiles)
                              if hasattr(assets, "catalog_snapshot") else None)
        from .contracts.workspace import WorkspaceSemanticPolicy
        self.workspace_context = WorkspaceSemanticPolicy(
            primary_table_metadata_ref=primary_table_metadata_ref,
            workspace_center_m=workspace_center_m,
            placement_policy_version=placement_policy_version,
            motion_policy_version=motion_policy_version)
        self.category_aliases = getattr(getattr(assets, "metadata", None), "category_aliases", {})
        self.grounder = SceneGrounder(aliases=self.aliases, category_aliases=self.category_aliases, assets=assets)
        self.motion = MotionScaleResolver(assets)
        self.planner = RecipePlanner()
        self.skill_planner = SkillPlannerRouter(mode=planner_mode, recipe_planner=self.planner,
                                               model_provider=skill_planning_provider, registry=REGISTRY)
        self.expander = TaskExpander()
        self.scene_editor = scene_editor or SceneEditor(assets, aliases=self.aliases, category_aliases=self.category_aliases)
        self.exporter = CommandExporter(robot=robot)
        self.vision_provider = vision_provider
        self.vision_fallback = VisionFallbackGrounder()
        self.domain_policy = TaskDomainPolicy()

    def _understanding_scene_context(self, scene):
        """Build the bounded, read-only scene context sent to Qwen.

        The first-stage model must receive more than an object count when a
        turn refers to an existing object (or to the primary tabletop).  Keep
        this summary semantic and path-free: geometry, mesh data and absolute
        metadata paths remain Python-only.  Object IDs are included solely as
        stable selectors in the input context; the prompt still forbids the
        model from inventing or emitting them in its semantic payload.
        """
        if scene is None:
            # A missing session scene is a bootstrap request.  The configured
            # tabletop policy supplies the primary support that the bootstrap
            # stage will materialize; an uploaded *empty* SceneConfig below is
            # deliberately different and has no implicit table.
            return {
                "basis": "bootstrap",
                "primary_table_available": True,
                "primary_table_object_id": None,
                "object_count": 0,
                "objects": [],
                "catalog_revision": self.asset_catalog.revision if self.asset_catalog is not None else None,
            }

        index = SceneIndex(scene)
        # Only the configured OLS identity is a verified primary table in a
        # production scene.  A fallback to the canonical semantic name is
        # retained for small in-memory/unit fixtures that intentionally do
        # not carry a deployment configuration.  ``coffee_table`` and an
        # arbitrary surface are never promoted to primary implicitly.
        configured_ref = self.workspace_context.primary_table_metadata_ref
        table_aliases = {"table", "desk", "desktop", "work_table", "桌子", "桌面", "台面"}
        objects = []
        table_ids = []
        for item in sorted(scene.objects, key=lambda value: value.object_id_in_scene):
            oid = item.object_id_in_scene
            semantic = index.semantic(oid)
            transform = index.transform(oid)
            renderer = index.properties(oid, "MeshRenderer")
            semantic_name = semantic.semantic_name if semantic is not None else ""
            category = semantic.category if semantic is not None else ""
            canonical_name = self.aliases.get(semantic_name.casefold(), semantic_name.casefold())
            metadata_ref = index.metadata_ref(oid)
            metadata_type = index.metadata_type(oid)
            if configured_ref is not None:
                is_table = (metadata_ref == configured_ref and metadata_type == "model"
                            and (canonical_name in table_aliases
                                 or category.casefold() in {"surface", "support_surface", "table"}))
                # An explicitly configured table must also be resolvable by
                # the read-only asset adapter; otherwise do not advertise a
                # usable support plane to Qwen.
                if is_table:
                    try:
                        self.assets.resolve(metadata_ref, asset_type="model")
                    except Exception:
                        is_table = False
            else:
                is_table = canonical_name in table_aliases and category.casefold() in {
                    "surface", "support_surface", "table", "furniture", ""
                }
            if is_table:
                table_ids.append(oid)
            objects.append({
                "object_id": oid,
                "object_name": item.object_name_in_scene,
                "semantic_name": semantic_name,
                "category": category,
                "support": semantic.support if semantic is not None else None,
                "parent": transform.parent if transform is not None else None,
                "color_override": renderer.forceOverrideColor if renderer is not None else None,
            })
        return {
            "basis": "current",
            "primary_table_available": len(table_ids) == 1,
            "primary_table_object_id": table_ids[0] if len(table_ids) == 1 else None,
            "object_count": len(scene.objects),
            "objects": objects,
            "catalog_revision": self.asset_catalog.revision if self.asset_catalog is not None else None,
        }

    def _validate_robot_platform(self, scene, robot_profile=None):
        """Guard the legacy single-arm exporter against platform mismatch.

        Imported Web scenes carry the authoritative robot MetadataRef.  The
        old pipeline used ``self.exporter`` whenever no RobotProfile was
        configured, which made Piper/CobotMagic scenes look like UR5e plans.
        Only arm-like robot objects participate; grippers, cameras and passive
        articulated models are intentionally ignored.  A configured profile
        has already validated its manifest and is therefore the explicit
        opt-in path for a non-default platform.
        """
        if robot_profile is not None or scene is None:
            return
        index = SceneIndex(scene)
        detected = []
        for obj in scene.objects:
            oid = obj.object_id_in_scene
            driver = index.robot_driver(oid)
            if driver is None or driver.role == "passive" or not driver.joint_sequence:
                continue
            if index.metadata_type(oid) != "robot":
                continue
            semantic = index.semantic(oid)
            if semantic is not None and semantic.category.casefold() not in {"robot", "arm", "manipulator"}:
                continue
            ref = index.metadata_ref(oid)
            if not ref:
                continue
            try:
                asset = self.assets.resolve(ref, "robot")
                name = asset.semantic_name
            except Exception:
                # Scene validation normally resolves this earlier.  Keep the
                # diagnostic useful if a direct caller bypasses Web validation.
                name = ref.rsplit("/", 1)[-1]
            detected.append((oid, ref, name))
        if not detected:
            return
        expected = normalize_robot_platform_name(self.robot)
        actual = []
        for _, _, name in detected:
            actual.append(normalize_robot_platform_name(name))
        if any(value == expected for value in actual):
            return
        raise BrainError(
            "capability_unsupported",
            "processing",
            f"场景机器人平台 {', '.join(sorted(set(actual)))} 未注册到当前 Brain 配置，"
            f"当前命令配置为 {expected}；不会生成伪造的 UR5e 命令。",
            category="capability",
            expected_robot=expected,
            detected_robots=sorted(set(actual)),
        )

    def understand_turn(self, instruction: str, *, scene: SceneConfig | None = None,
                        dialogue=None) -> BrainTurn:
        """Call understanding once; keep injected context out of the user text."""
        # The OLS directory is a per-turn input, not a process-start constant.
        # Adapters backed by a read-only local index can cheaply return the same
        # revision; adapters that refresh from OLS expose the new revision here.
        # Updating the provider prompt and the request together prevents a new
        # catalog from being used to interpret an old response (or vice versa).
        if hasattr(self.assets, "catalog_snapshot"):
            # A live OLS adapter is read-only but can publish a new index
            # while Brain remains running.  Refresh before taking the
            # request-scoped snapshot so every first-stage call sees the
            # current catalog rather than a process-start copy.  The adapter
            # swaps atomically only after metadata/geometry validation; a
            # stale or inconsistent publication therefore fails closed.
            if hasattr(self.assets, "refresh_from_source"):
                self.assets.refresh_from_source()
            current_catalog = self.assets.catalog_snapshot(aliases=None,
                                                          registered_profiles=self.registered_profiles)
            if self.asset_catalog is None or current_catalog.revision != self.asset_catalog.revision:
                self.asset_catalog = current_catalog
                if hasattr(self.understanding, "set_asset_catalog"):
                    self.understanding.set_asset_catalog(current_catalog)
        deferred_reference_error = None
        try:
            original_requested = any(token in instruction.casefold() for token in ("原始场景", "初始场景", "最开始的场景", "original scene", "initial scene"))
            provider_instruction = dialogue.contextualize(instruction, scene) if dialogue and scene is not None and not original_requested else instruction
        except ValueError as exc:
            if str(exc) not in {"dialogue_reference_missing", "dialogue_reference_ambiguous"}:
                raise
            # Only parsed lifecycle can establish whether 'it' is a new object
            # introduced in this turn. Do not reject it before understanding.
            deferred_reference_error = exc
            provider_instruction = instruction
        scene_context = self._understanding_scene_context(scene)
        request = TaskUnderstandingRequest(instruction=provider_instruction,
                                           asset_catalog=self.asset_catalog if self.catalog_for_provider else None,
                                           workspace=self.workspace_context,
                                           scene_context=scene_context)
        if hasattr(self.understanding, "understand_turn"):
            turn = self.understanding.understand_turn(request)
        else:
            intent = self.understanding.understand(request)
            turn = BrainTurn(status="accepted", turn_kind="robot_task", instruction=instruction, task_intent=intent)
        # Keep unambiguous existence/count language on the read-only query
        # route even if a provider emits an accepted scene_edit envelope.  A
        # query must never acquire, resolve or commit an edit lease.
        turn = _canonicalize_query_route(turn, instruction)
        # Bind the canonical turn to the exact catalog used in its provider
        # request.  This is checked again immediately before scene editing so
        # an OLS update between understanding and execution cannot retarget a
        # model key to a different asset.
        turn = turn.model_copy(update={"instruction": instruction,
                                       "asset_catalog_revision": self.asset_catalog.revision
                                       if self.asset_catalog is not None else None})
        # The scene basis is a safety-sensitive routing decision, not a
        # semantic detail that Qwen may omit.  An explicit user request for
        # the original/initial scene must win over a model response that
        # leaves the default as ``current``; otherwise an apparently valid
        # edit silently mutates the latest scene instead of deriving from the
        # immutable import snapshot.
        if original_requested and turn.scene_edit is not None and turn.scene_edit.scene_basis != "original":
            turn = turn.model_copy(update={"scene_edit": turn.scene_edit.model_copy(update={"scene_basis": "original"})})
        if deferred_reference_error is not None and turn.status == TurnStatus.ACCEPTED:
            from .contracts.turn import SceneEditPlan
            edits = turn.scene_edit
            introduced, reused = set(), set()
            valid_local = isinstance(edits, SceneEditPlan)
            if valid_local:
                by_id = {e.entity_id:e for e in edits.entities}
                for edit in edits.operations:
                    if edit.reference in by_id and (by_id[edit.reference].dialogue_ref or by_id[edit.reference].dialogue_ref_set):
                        valid_local &= edit.reference in introduced
                    if edit.operation == "add":
                        introduced.add(edit.target)
                    elif edit.target in introduced:
                        reused.add(edit.target)
                    elif edit.target in by_id and (by_id[edit.target].dialogue_ref or by_id[edit.target].dialogue_ref_set):
                        valid_local = False
            if not valid_local or not reused:
                raise deferred_reference_error
        if turn.task_intent is not None:
            turn = turn.model_copy(update={"task_intent": turn.task_intent.model_copy(update={"instruction": instruction})})
        if dialogue is not None and scene is not None and not (turn.scene_edit and turn.scene_edit.scene_basis == "original"):
            turn = dialogue.apply_exclusions(turn, scene, aliases=self.aliases)
        turn = self.domain_policy.classify(turn, instruction)
        if turn.scene_edit is not None and turn.scene_edit.scene_basis == "original" and not original_requested:
            raise ValueError("original_scene_requires_explicit_request")
        if turn.status == TurnStatus.ACCEPTED and turn.turn_kind == TurnKind.ROBOT_TASK:
            turn = turn.model_copy(update={"task_intent": normalize_motion_language(turn.task_intent)})
        return turn

    def process_turn(self, request_id: str, turn: BrainTurn, scene: SceneConfig | None, *,
                     dialogue=None, bindings_override=None, edit_defaults=None,
                     capture: Callable[[], CameraFrame] | None = None,
                     held_object: SceneId | None = None,
                     robot_profile=None, robot_setup_revision=0, arm_states=None,
                     seen_scene_object_ids=None, next_scene_object_id=None) -> BrainResult:
        """Consume an understood turn without another provider call or normalization."""
        self.skill_planner.last_trace = None
        if turn.status != TurnStatus.ACCEPTED:
            return BrainResult(status=turn.status, turn_kind=turn.turn_kind)
        if (turn.asset_catalog_revision is not None and self.asset_catalog is not None
                and turn.asset_catalog_revision != self.asset_catalog.revision):
            raise ValueError("asset_catalog_revision_conflict")
        dual = robot_profile is not None and robot_profile.setup.mode == "dual"
        if not dual:
            turn.require_legacy_execution()
        elif turn.robot_setup_request is not None:
            request = turn.robot_setup_request
            if request.mode != "dual" or request.profile_id not in {None, robot_profile.setup.profile_id}:
                raise ValueError("robot_setup_switch_required")
        if turn.turn_kind == TurnKind.SESSION_CONTROL:
            return BrainResult(turn_kind=turn.turn_kind, session_action=turn.session_control)
        if scene is None:
            raise ValueError("scene_required")
        if turn.turn_kind == TurnKind.SCENE_EDIT:
            edited = self.scene_editor.edit_result(turn.scene_edit, scene, dialogue=dialogue, defaults=edit_defaults,
                                                  bindings_override=bindings_override,
                                                  seen_scene_object_ids=seen_scene_object_ids,
                                                  next_scene_object_id=next_scene_object_id)
            return BrainResult(turn_kind=turn.turn_kind, scene_patch=edited.patch,
                               focus_object_ids=edited.focus_object_ids or None,
                               deleted_object_ids=edited.deleted_object_ids,
                               assumptions=edited.assumptions)
        if turn.turn_kind == TurnKind.SCENE_QUERY:
            visual = turn.scene_query.evidence_source == "image"
            if visual and (self.vision_provider is None or capture is None):
                raise ValueError("query_visual_evidence_required")
            query = SceneQueryEngine(aliases=self.aliases, category_aliases=self.category_aliases, assets=self.assets,
                                    near_distance_m=self.query_near_distance_m).query(
                                        turn.scene_query.model_copy(update={"evidence_source": "scene"}), scene, dialogue)
            if visual:
                from .scene.component_access import SceneIndex
                from .contracts.task_intent import TaskEntity
                index, frame = SceneIndex(scene), capture()
                identifiers = set(query.object_ids)
                if query.reference_object_id is not None:
                    identifiers.add(query.reference_object_id)
                if not identifiers:
                    raise ValueError("query_visual_evidence_required: 无候选不能证明画面中没有物体")
                for oid in sorted(identifiers):
                    semantic = index.semantic(oid)
                    entity = TaskEntity(entity_id=semantic.semantic_name, semantic_name=semantic.semantic_name,
                                        category=semantic.category)
                    self.vision_fallback.resolve(entity, [index.object(oid)], scene, frame, self.vision_provider)
                query.evidence_source = "image_and_scene_geometry"
                query.reply = "已通过当前真实图像核对候选物体；以下关系依据同一快照的场景几何。" + (query.reply or str(query.names))
            return BrainResult(turn_kind=turn.turn_kind, scene_query_result=query, focus_object_ids=query.object_ids)
        # Do this immediately before grounding/planning so scene edits and
        # queries remain displayable on unsupported platforms, while robot
        # tasks cannot fall through to the fixed UR5e exporter.
        self._validate_robot_platform(scene, robot_profile=robot_profile)
        intent = turn.task_intent
        if robot_profile is not None and not dual:
            if arm_states is None or not arm_states.arms["single"].state_known:
                raise ValueError("robot_runtime_state_unknown")
            if robot_profile.v2_robot is None:
                raise ValueError("robot_profile_v2_robot_missing")
            held_object = arm_states.arms["single"].holding_object
        overrides = dialogue.bindings(intent, scene) if dialogue else {}
        for entity_id, ids in (bindings_override or {}).items():
            if entity_id in overrides and overrides[entity_id] != ids:
                raise ValueError("grounding_binding_conflict: " + entity_id)
            overrides[entity_id] = ids
        frame = None
        while True:
            try:
                grounded = self.grounder.ground(intent, scene, overrides)
                break
            except GroundingAmbiguous as exc:
                if self.vision_provider is None or capture is None or exc.entity.entity_id in overrides:
                    raise
                if frame is None:
                    frame = capture()
                ids = self.vision_fallback.resolve(exc.entity, exc.candidates, scene, frame, self.vision_provider)
                overrides[exc.entity.entity_id] = ids
        grounded = self.expander.expand(grounded, scene)
        grounded = self.motion.resolve(grounded)
        if dual:
            from .planning.dual_arm_recipe_planner import DualArmRecipePlanner
            from .planning.arm_assignment_resolver import resolve_arms
            if arm_states is None:
                raise ValueError("robot_runtime_state_unknown")
            grounded = resolve_arms(grounded, robot_profile, arm_usage=intent.arm_usage)
            operations = grounded.operations
            if any(op.parallel_required for op in operations) and not robot_profile.coordinated_execution:
                raise ValueError("dual_coordinated_execution_not_registered")
            from .planning.skill_planner_router import PlanningTrace
            mode = "qwen" if self.skill_planner.mode == "qwen" else "recipe"
            trace = self.skill_planner.last_trace = PlanningTrace(self.skill_planner.mode, used_planner=mode)
            if mode == "qwen":
                from .planning.dual_qwen_planner import DualQwenPlanner
                commands = DualQwenPlanner().plan(request_id, grounded, scene, robot_profile,
                    robot_setup_revision, arm_states, self.skill_planner.provider, REGISTRY, trace)
            else:
                commands = DualArmRecipePlanner().plan(request_id, grounded, scene, robot_profile.setup,
                                                      robot_setup_revision, arm_states)
            from .planning.dual_capability import validate_dual_capability
            validate_dual_capability(commands, robot_profile)
            by_entity = {e.entity_id: e.scene_object_id for e in grounded.entities}
            return BrainResult(task_intent=intent, grounded_task=grounded, commands=commands,
                focus_object_ids=list(dict.fromkeys(by_entity[op.source or op.target] for op in operations)),
                planner_used=mode, planner_trace=trace.debug_payload())
        planning = self.skill_planner.plan(grounded, held_object=held_object, scene=scene)
        plan = planning.plan
        exporter = CommandExporter(robot=robot_profile.v2_robot) if robot_profile is not None else self.exporter
        commands = exporter.export(request_id, grounded, plan, scene, held_object=held_object)
        by_entity = {e.entity_id:e.scene_object_id for e in grounded.entities}
        focus = list(dict.fromkeys(by_entity[op.source or op.target] for op in grounded.operations))
        return BrainResult(task_intent=intent, grounded_task=grounded, skill_plan=plan, commands=commands,
                           focus_object_ids=focus, planner_used=planning.trace.used_planner,
                           planner_trace=planning.trace.debug_payload())

    def run(self, request_id: str, instruction: str, scene: SceneConfig, *,
            dialogue=None, capture: Callable[[], CameraFrame] | None = None,
            held_object: SceneId | None = None, bindings_override=None) -> BrainResult:
        turn = self.understand_turn(instruction, scene=scene, dialogue=dialogue)
        return self.process_turn(request_id, turn, scene, dialogue=dialogue, capture=capture,
                                 held_object=held_object, bindings_override=bindings_override)

    def run_turn(self, request_id, instruction, scene, **kwargs):
        return self.run(request_id, instruction, scene, **kwargs)
