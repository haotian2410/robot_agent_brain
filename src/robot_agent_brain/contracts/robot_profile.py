"""Deployment declarations; group/interface names are never inferred by Brain."""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator, field_serializer

from .robot_setup import RobotSetup, RobotSetupRequest, RobotRuntimeState
from .scene import SceneConfig, SceneId


class RobotProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")
    setup: RobotSetup
    template: SceneConfig
    robot_object_ids: set[SceneId] = Field(min_length=1)
    platform_object_ids: set[SceneId] = Field(min_length=1)
    supported_skills: set[Literal["locate", "move", "grasp", "release"]]
    commands_version: Literal["2.0", "3.0", "4.1"]
    coordinated_execution: bool = False
    initial_state: RobotRuntimeState | None = None
    default_task_arm: Literal["left", "right", "single"] | None = None
    platform_roles: dict[str, SceneId] = Field(default_factory=dict)
    v2_robot: str | None = Field(default=None, min_length=1)
    bound_object_map: dict[SceneId, SceneId] | None = Field(default=None, exclude=True)

    @field_serializer("robot_object_ids", "platform_object_ids", "supported_skills", when_used="json")
    def sorted_sets(self, value):
        return sorted(value)

    @model_validator(mode="after")
    def valid_manifest(self):
        ids = {o.object_id_in_scene for o in self.template.objects}
        if not self.robot_object_ids <= self.platform_object_ids <= ids:
            raise ValueError("robot_profile_manifest_invalid")
        if self.setup.mode == "dual" and self.commands_version not in {"3.0", "4.1"}:
            raise ValueError("robot_profile_dual_requires_v3_or_v4")
        if self.commands_version == "4.1" and self.setup.mode != "dual":
            raise ValueError("robot_profile_v4_requires_dual")
        if self.default_task_arm is not None and self.default_task_arm not in self.setup.arms:
            raise ValueError("robot_profile_default_arm_invalid")
        if self.initial_state is not None:
            self.initial_state.require_idle(self.setup)
        if (not set(self.platform_roles.values()) <= self.platform_object_ids - self.robot_object_ids
                or len(set(self.platform_roles.values())) != len(self.platform_roles)):
            raise ValueError("robot_profile_platform_roles_invalid")
        self.validate_scene(self.template)
        return self

    def validate_scene(self, scene, setup=None):
        from ..scene.component_access import SceneIndex
        index = SceneIndex(scene)
        setup = setup or self.setup
        if setup.mode != self.setup.mode or setup.profile_id != self.setup.profile_id or set(setup.arms) != set(self.setup.arms):
            raise ValueError("robot_profile_scene_mode_mismatch")
        template_index = SceneIndex(self.template)
        for side, arm in setup.arms.items():
            if arm.model_dump(exclude={"robot_object_id"}) != self.setup.arms[side].model_dump(exclude={"robot_object_id"}):
                raise ValueError("robot_profile_interface_mapping_mismatch")
            if index.robot_driver(arm.robot_object_id) is None or index.robot_driver(arm.robot_object_id).role != "arm":
                raise ValueError("robot_profile_driver_missing")
            if index.metadata_type(arm.robot_object_id) != "robot":
                raise ValueError("robot_profile_metadata_type_invalid")
            expected = self.setup.arms[side].robot_object_id
            if self.bound_object_map is not None:
                expected = next((key for key, value in self.bound_object_map.items() if value == expected), expected)
            if (index.metadata_ref(arm.robot_object_id) != template_index.metadata_ref(expected)
                    or any(getattr(index.robot_driver(arm.robot_object_id), name) !=
                           getattr(template_index.robot_driver(expected), name)
                           for name in ("joint_sequence", "joint_limits", "available_connect_joints", "available_connect_link"))):
                raise ValueError("robot_profile_resource_mapping_mismatch")
        # The manifest, not type/name heuristics, owns all removable robot parts.
        for obj in self.template.objects:
            attachment = SceneIndex(self.template).properties(obj.object_id_in_scene, "RobotAttachment")
            if attachment and attachment.parent_object_id in self.robot_object_ids and obj.object_id_in_scene not in self.robot_object_ids:
                raise ValueError("robot_profile_attachment_not_owned")
            if attachment and setup == self.setup and self.bound_object_map is None:
                actual = index.properties(obj.object_id_in_scene, "RobotAttachment")
                if actual != attachment:
                    raise ValueError("robot_profile_attachment_mapping_mismatch")
        if setup == self.setup and not {a.robot_object_id for a in setup.arms.values()} <= (set(self.bound_object_map.values()) if self.bound_object_map else self.robot_object_ids):
            raise ValueError("robot_profile_arm_not_owned")


class RobotProfileRegistry(BaseModel):
    model_config = ConfigDict(extra="forbid")
    profiles: dict[str, RobotProfile] = Field(default_factory=dict)
    default_single: str | None = None
    default_dual: str | None = None

    @model_validator(mode="after")
    def valid_defaults(self):
        if any(key != p.setup.profile_id for key, p in self.profiles.items()):
            raise ValueError("robot_profile_id_mismatch")
        for mode in ("single", "dual"):
            key = getattr(self, "default_" + mode)
            if key is not None and (key not in self.profiles or self.profiles[key].setup.mode != mode):
                raise ValueError("robot_profile_default_invalid")
        return self

    def resolve(self, request: RobotSetupRequest):
        key = request.profile_id or getattr(self, "default_" + request.mode)
        profile = self.profiles.get(key)
        if profile is None:
            raise ValueError("robot_setup_profile_not_registered")
        if profile.setup.mode != request.mode:
            raise ValueError("robot_setup_profile_mode_mismatch")
        return profile.model_copy(deep=True)

    def resolve_scene(self, scene):
        """Resolve declared scene setup or a unique exact active-driver binding."""
        from ..scene.component_access import SceneIndex
        declared = scene.raw_document().get("robot_setup")
        if declared is not None:
            setup = RobotSetup.model_validate(declared)
            profile = self.resolve(RobotSetupRequest(mode=setup.mode, profile_id=setup.profile_id))
            profile.validate_scene(scene, setup)
            # Match owned parts without substituting template object IDs for
            # the declared live arm identities. Ambiguous assets require an
            # explicit deployment manifest rather than an ordering guess.
            index, template = SceneIndex(scene), SceneIndex(profile.template)
            mapping = {profile.setup.arms[side].robot_object_id: arm.robot_object_id
                       for side, arm in setup.arms.items()}
            for identifier in sorted(profile.platform_object_ids - set(mapping)):
                matches = [obj.object_id_in_scene for obj in scene.objects
                           if obj.object_id_in_scene not in mapping.values()
                           and index.metadata_type(obj.object_id_in_scene) == template.metadata_type(identifier)
                           and index.metadata_ref(obj.object_id_in_scene) == template.metadata_ref(identifier)]
                if identifier in matches:
                    matches = [identifier]
                if len(matches) != 1:
                    raise ValueError("robot_scene_profile_mapping_ambiguous")
                mapping[identifier] = matches[0]
            from ..scene.component_reference_registry import ComponentReferenceRegistry
            references = ComponentReferenceRegistry()
            for identifier, live_id in mapping.items():
                component = template.component(identifier, "RobotAttachment")
                actual = index.component(live_id, "RobotAttachment")
                if component is not None:
                    expected = references.remap_component(component.model_dump(mode="json"), mapping)
                    if actual is None or actual.model_dump(mode="json") != expected:
                        raise ValueError("robot_profile_attachment_mapping_mismatch")
                elif actual is not None:
                    raise ValueError("robot_profile_attachment_mapping_mismatch")
            return profile.model_copy(update={"setup": setup, "bound_object_map": mapping}, deep=True)
        index = SceneIndex(scene)
        active = {obj.object_id_in_scene for obj in scene.objects
                  if index.robot_driver(obj.object_id_in_scene) is not None
                  and index.robot_driver(obj.object_id_in_scene).role != "passive"}
        matches = []
        for profile in self.profiles.values():
            if {arm.robot_object_id for arm in profile.setup.arms.values()} != active:
                continue
            try:
                profile.validate_scene(scene)
            except ValueError:
                continue
            matches.append(profile)
        if len(matches) > 1:
            raise ValueError("robot_scene_profile_ambiguous")
        return matches[0].model_copy(deep=True) if matches else None
