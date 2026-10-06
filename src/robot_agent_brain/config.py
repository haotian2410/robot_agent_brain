from __future__ import annotations

import json
import os
from importlib.resources import files
from pathlib import Path
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator


class LayoutDefaults(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    table_asset_id: str = "demo_table"
    table_object_id: str = "table_01"
    table_position: tuple[float, float, float] = (0, 0, -.025)
    workspace_min: tuple[float, float] = (-.75, -.55)
    workspace_max: tuple[float, float] = (.75, .55)
    clearance_m: float = Field(default=.04, gt=0)
    max_attempts: int = Field(default=400, ge=1, le=10000)
    coordinate_convention: Literal["x_right_y_front_z_up"] = "x_right_y_front_z_up"
    initial_counts: dict[str, int] = Field(default_factory=dict)

    @model_validator(mode="after")
    def valid_workspace(self):
        if any(a >= b for a, b in zip(self.workspace_min, self.workspace_max)):
            raise ValueError("workspace bounds must increase")
        if any(count < 1 for count in self.initial_counts.values()):
            raise ValueError("initial counts must be positive")
        return self


class BrainConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    provider: Literal["qwen", "replay"] = "qwen"
    base_url: str = "http://127.0.0.1:8080/v1"
    model: str | None = None
    timeout: float = Field(default=120, gt=0)
    structured_output: bool = True
    api_key: SecretStr | None = Field(default=None, exclude=True)
    assets: str | None = None
    defaults: str | None = None
    robot: str = "ur5e"
    output_dir: str = "var/manual-tests"
    vision: bool = False
    seed: int = 0
    replay_file: str | None = None
    debug: bool = False

    @classmethod
    def load(cls, path=None, *, overrides=None, environ=None):
        values = json.loads(files("robot_agent_brain.resources").joinpath("config.json").read_text())
        if path is not None:
            user = json.loads(Path(path).read_text(encoding="utf-8"))
            if "api_key" in user:
                raise ValueError("config_secret_forbidden: use ROBOT_BRAIN_API_KEY")
            values.update(user)
            for key in ("assets", "defaults", "replay_file"):
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
        from .adapters.local_asset_catalog import LocalAssetCatalog
        if self.assets is not None:
            return LocalAssetCatalog.from_file(self.assets)
        data = json.loads(files("robot_agent_brain.resources").joinpath("assets.json").read_text())
        return LocalAssetCatalog.from_document(data)

    def load_defaults(self):
        resource = Path(self.defaults) if self.defaults else files("robot_agent_brain.resources").joinpath("defaults.json")
        return LayoutDefaults.model_validate_json(resource.read_text(encoding="utf-8"))
