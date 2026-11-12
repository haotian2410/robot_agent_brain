from __future__ import annotations

from pydantic import BaseModel, ConfigDict, model_validator


class ReleasePolicy(BaseModel):
    """Feature gates for the published Brain build."""

    model_config = ConfigDict(extra="forbid")
    version: str = "v0.2"
    dynamic_platform_rebind: bool = False
    runtime_robot_setup_change: bool = False
    nl_initial_platform_selection: bool = False

    @model_validator(mode="after")
    def published_defaults_are_closed(self):
        if self.version == "v0.2" and any((self.dynamic_platform_rebind,
                                           self.runtime_robot_setup_change,
                                           self.nl_initial_platform_selection)):
            raise ValueError("release_policy_v02_capability_must_be_disabled")
        return self

    def deny_dynamic_platform(self) -> None:
        if not self.dynamic_platform_rebind:
            raise ValueError(
                "capability_unsupported: v0.2 暂不支持在对话内更换机器人平台配置。"
                "请结束当前对话，并在新会话绑定前选择平台。"
            )

    def deny_runtime_robot_setup(self) -> None:
        if not self.runtime_robot_setup_change:
            raise ValueError(
                "capability_unsupported: v0.2 暂不支持在对话内修改机器人、夹爪、相机或单/双臂部署配置。"
                "请在新会话绑定前选择初始平台。"
            )
