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
    commands_version: Literal["2.0", "3.0"]
    coordinated_execution: bool = False
    initial_state: RobotRuntimeState | None = None
    default_task_arm: Literal["left", "right", "single"] | None = None
    platform_roles: dict[str, SceneId] = Field(default_factory=dict)
    v2_robot: str | None = Field(default=None, min_length=1)

    @field_serializer("robot_object_ids", "platform_object_ids", "supported_skills", when_used="json")
    def sorted_sets(self, value):
        return sorted(value)

    @model_validator(mode="after")
    def valid_manifest(self):
        ids = {o.object_id_in_scene for o in self.template.objects}
        if not self.robot_object_ids <= self.platform_object_ids <= ids:
            raise ValueError("robot_profile_manifest_invalid")
        if self.setup.mode == "dual" and self.commands_version != "3.0":
            raise ValueError("robot_profile_dual_requires_v3")
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
        template_index = SceneIndex(self.template)
        for side, arm in setup.arms.items():
            if index.robot_driver(arm.robot_object_id) is None:
                raise ValueError("robot_profile_driver_missing")
            if index.metadata_type(arm.robot_object_id) != "robot":
                raise ValueError("robot_profile_metadata_type_invalid")
            expected = self.setup.arms[side].robot_object_id
            if (index.metadata_ref(arm.robot_object_id) != template_index.metadata_ref(expected)
                    or index.robot_driver(arm.robot_object_id).joint_sequence != template_index.robot_driver(expected).joint_sequence):
                raise ValueError("robot_profile_resource_mapping_mismatch")
        # The manifest, not type/name heuristics, owns all removable robot parts.
        for obj in self.template.objects:
            attachment = SceneIndex(self.template).properties(obj.object_id_in_scene, "RobotAttachment")
            if attachment and attachment.parent_object_id in self.robot_object_ids and obj.object_id_in_scene not in self.robot_object_ids:
                raise ValueError("robot_profile_attachment_not_owned")
        if setup == self.setup and not {a.robot_object_id for a in setup.arms.values()} <= self.robot_object_ids:
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
