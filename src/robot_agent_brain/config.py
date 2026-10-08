from __future__ import annotations

import json
import os
from importlib.resources import files
from pathlib import Path
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator
from .contracts.scene import SceneId, RobotDriverProperties


class LayoutDefaults(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    table_object_id: SceneId = 0
    robot_object_id: SceneId = 1
    robot_position: tuple[float, float, float] = (-.6, 0, 0)
    table_position: tuple[float, float, float] = (0, 0, -.025)
    workspace_min: tuple[float, float] = (-.75, -.55)
    workspace_max: tuple[float, float] = (.75, .55)
    clearance_m: float = Field(default=.04, gt=0)
    support_contact_tolerance_m: float = Field(default=.001, gt=0)
    max_attempts: int = Field(default=400, ge=1, le=10000)
    coordinate_convention: Literal["x_right_y_front_z_up"] = "x_right_y_front_z_up"
    initial_counts: dict[str, int] = Field(default_factory=dict)

    @model_validator(mode="after")
    def valid_workspace(self):
        if self.table_object_id == self.robot_object_id:
            raise ValueError("bootstrap_object_id_collision")
        if any(a >= b for a, b in zip(self.workspace_min, self.workspace_max)):
            raise ValueError("workspace bounds must increase")
        if any(count < 1 for count in self.initial_counts.values()):
            raise ValueError("initial counts must be positive")
        return self


class BrainConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    provider: Literal["qwen", "replay"] = "qwen"
    planner: Literal["recipe", "qwen", "auto"] = "recipe"
    planner_max_completion_tokens: int = Field(default=1024, ge=128, le=4096)
    base_url: str = "http://127.0.0.1:8080/v1"
    model: str | None = None
    timeout: float = Field(default=120, gt=0)
    structured_output: bool = True
    api_key: SecretStr | None = Field(default=None, exclude=True)
    assets: str | None = None
    asset_library_root: str | None = None
    asset_geometry_cache: str | None = None
    asset_category_index: str | None = None
    semantic_aliases: str | None = None
    library_ref_prefix: str = "$LIBRARY_SERVER/"
    default_table_metadata_ref: str | None = None
    default_robot_metadata_ref: str | None = None
    default_robot_driver: RobotDriverProperties | None = None
    defaults: str | None = None
    robot: str = "ur5e"
    output_dir: str = "var/manual-tests"
    vision: bool = False
    seed: int = 0
    replay_file: str | None = None
    debug: bool = False

    @model_validator(mode="after")
    def valid_library_configuration(self):
        if (self.asset_library_root is None) != (self.asset_geometry_cache is None):
            raise ValueError("asset_library_config_missing: root and geometry cache must be configured together")
        if self.asset_category_index is not None and self.asset_library_root is None:
            raise ValueError("asset_library_config_missing: category index requires a library")
        if self.assets is not None and self.asset_library_root is not None:
            raise ValueError("asset_library_config_ambiguous: choose demo assets or a real library")
        if not self.library_ref_prefix or not self.library_ref_prefix.endswith("/"):
            raise ValueError("library_ref_prefix_invalid")
        return self

    @classmethod
    def load(cls, path=None, *, overrides=None, environ=None):
        values = json.loads(files("robot_agent_brain.resources").joinpath("config.json").read_text())
        if path is not None:
            user = json.loads(Path(path).read_text(encoding="utf-8"))
            if "api_key" in user:
                raise ValueError("config_secret_forbidden: use ROBOT_BRAIN_API_KEY")
            values.update(user)
            for key in ("assets", "defaults", "replay_file", "asset_library_root",
                        "asset_geometry_cache", "asset_category_index", "semantic_aliases"):
                if user.get(key) and not Path(user[key]).is_absolute():
                    values[key] = str((Path(path).resolve().parent / user[key]).resolve())
        env = os.environ if environ is None else environ
        for key in cls.model_fields:
            value = env.get("ROBOT_BRAIN_" + key.upper())
            if value is not None:
                values[key] = value
        values.update({k: v for k, v in (overrides or {}).items() if v is not None})
        return cls.model_validate(values)

    def load_assets(self):
        if self.asset_library_root is not None:
            from .adapters.local_asset_library import LocalAssetLibraryAdapter
            return LocalAssetLibraryAdapter(self.asset_library_root, self.asset_geometry_cache,
                self.asset_category_index, library_ref_prefix=self.library_ref_prefix)
        from .adapters.demo_asset_library import DemoAssetLibrary
        if self.assets is not None:
            return DemoAssetLibrary(json.loads(Path(self.assets).read_text(encoding="utf-8")))
        data = json.loads(files("robot_agent_brain.resources").joinpath("assets.json").read_text())
        return DemoAssetLibrary(data)

    def bootstrap_settings(self):
        settings = {}
        if self.asset_library_root is None and self.assets is None:
            settings = json.loads(files("robot_agent_brain.resources").joinpath("demo_platform.json").read_text())
        for field in ("default_table_metadata_ref", "default_robot_metadata_ref", "default_robot_driver"):
            value = getattr(self, field)
            if value is not None:
                settings[field] = value.model_dump(mode="json") if hasattr(value, "model_dump") else value
        return settings

    def load_semantic_aliases(self):
        if self.semantic_aliases is None:
            return {}
        value = json.loads(Path(self.semantic_aliases).read_text(encoding="utf-8"))
        if not isinstance(value, dict) or any(not isinstance(k, str) or not k.strip()
                or not isinstance(v, str) or not v.strip() for k, v in value.items()):
            raise ValueError("semantic_aliases_invalid")
        normalized = {}
        for key, target in value.items():
            key, target = key.strip().casefold(), target.strip().casefold()
            if key in normalized and normalized[key] != target:
                raise ValueError("semantic_aliases_conflict")
            normalized[key] = target
        return normalized

    def load_defaults(self):
        resource = Path(self.defaults) if self.defaults else files("robot_agent_brain.resources").joinpath("defaults.json")
        return LayoutDefaults.model_validate_json(resource.read_text(encoding="utf-8"))
