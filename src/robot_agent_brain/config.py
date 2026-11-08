from __future__ import annotations

import json
import os
from importlib.resources import files
from pathlib import Path
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator
from .contracts.scene import SceneId, RobotDriverProperties
from .contracts.robot_profile import RobotProfileRegistry
from .contracts.release_policy import ReleasePolicy


class LayoutDefaults(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    table_object_id: SceneId = 0
    robot_object_id: SceneId = 1
    robot_position: tuple[float, float, float] = (-.6, 0, 0)
    table_position: tuple[float, float, float] = (0, 0, -.025)
    workspace_min: tuple[float, float] = (-.75, -.55)
    workspace_max: tuple[float, float] = (.75, .55)
    # Robot reachability and scene editing use different safety envelopes.
    # ``workspace_*`` remains the execution/bootstrap envelope.  When the
    # scene-edit values are omitted, SceneEditor derives them from the
    # verified support-surface AABB instead of clipping tabletop edits to the
    # robot's reachable strip.
    scene_edit_workspace_min: tuple[float, float] | None = None
    scene_edit_workspace_max: tuple[float, float] | None = None
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
        if (self.scene_edit_workspace_min is None) != (self.scene_edit_workspace_max is None):
            raise ValueError("scene_edit_workspace_bounds_must_be_paired")
        if self.scene_edit_workspace_min is not None and any(
                a >= b for a, b in zip(self.scene_edit_workspace_min, self.scene_edit_workspace_max)):
            raise ValueError("scene_edit_workspace_bounds_must_increase")
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
    scene_layout_interiors: str | None = None
    semantic_aliases: str | None = None
    scene_reference_catalog: str | None = None
    library_ref_prefix: str = "$LIBRARY_SERVER/"
    default_table_metadata_ref: str | None = None
    default_robot_metadata_ref: str | None = None
    default_scene_edit_assets: dict[str, str] = Field(default_factory=dict)
    default_scene: str | None = None
    default_robot_driver: RobotDriverProperties | None = None
    defaults: str | None = None
    robot: str = "ur5e"
    robot_profiles: RobotProfileRegistry = Field(default_factory=RobotProfileRegistry)
    release_policy: ReleasePolicy = Field(default_factory=ReleasePolicy)
    component_reference_rules: dict[str, dict] = Field(default_factory=dict)
    scene_robot_profile: str | None = None
    scene_platform_object_ids: set[SceneId] | None = None
    allow_scene_reset: bool = False
    output_dir: str = "var/manual-tests"
    vision: bool = False
    scene_id_bits: Literal[32, 53] = 53
    editor_scene_manifests: dict[str, list[SceneId]] = Field(default_factory=dict)
    seed: int = 0
    replay_file: str | None = None
    debug: bool = False
    scene_scale_min: float = Field(default=.1, gt=0)
    scene_scale_max: float = Field(default=10., gt=0)
    scene_scale_small: float = Field(default=1.1, gt=1)
    scene_scale_medium: float = Field(default=1.5, gt=1)
    scene_scale_large: float = Field(default=2., gt=1)
    query_near_distance_m: float = Field(default=.2, gt=0, le=2)
    scene_layout_grid_size: int = Field(default=5, ge=3, le=9)
    scene_layout_near_clearance_m: float = Field(default=.02, ge=0, le=1)

    def scale_policy(self):
        from .scene.scale_policy import SceneScalePolicy
        return SceneScalePolicy(minimum=self.scene_scale_min, maximum=self.scene_scale_max,
                                small=self.scene_scale_small, medium=self.scene_scale_medium, large=self.scene_scale_large)

    @model_validator(mode="after")
    def valid_library_configuration(self):
        self.scale_policy()
        from .scene.component_reference_registry import ComponentReferenceRegistry
        ComponentReferenceRegistry(self.component_reference_rules)
        if self.scene_robot_profile is not None and self.scene_robot_profile not in self.robot_profiles.profiles:
            raise ValueError("robot_setup_profile_not_registered")
        if self.asset_library_root is None and self.asset_geometry_cache is not None:
            raise ValueError("asset_library_config_missing: geometry cache requires a library root")
        if self.asset_library_root is not None and not Path(self.asset_library_root).is_absolute():
            # ``BrainConfig.load`` resolves paths relative to the config file.
            # Direct construction with a relative root is ambiguous and used
            # to silently fall back to demo assets; absolute roots remain
            # injectable in unit tests and are validated when the adapter loads.
            raise ValueError("asset_library_config_root_missing: " + self.asset_library_root)
        if self.asset_category_index is not None and self.asset_library_root is None:
            raise ValueError("asset_library_config_missing: category index requires a library")
        if self.assets is not None and self.asset_library_root is not None:
            raise ValueError("asset_library_config_ambiguous: choose demo assets or a real library")
        if not self.library_ref_prefix or not self.library_ref_prefix.endswith("/"):
            raise ValueError("library_ref_prefix_invalid")
        for name, ref in self.default_scene_edit_assets.items():
            if not isinstance(name, str) or not name.strip() or not isinstance(ref, str) or not ref.startswith(self.library_ref_prefix):
                raise ValueError("default_scene_edit_asset_ref_invalid")
        return self

    @classmethod
    def load(cls, path=None, *, overrides=None, environ=None):
        values = json.loads(files("robot_agent_brain.resources").joinpath("config.json").read_text(encoding="utf-8"))
        if path is not None:
            user = json.loads(Path(path).read_text(encoding="utf-8"))
            if "api_key" in user:
                raise ValueError("config_secret_forbidden: use ROBOT_BRAIN_API_KEY")
            values.update(user)
            for key in ("assets", "defaults", "replay_file", "asset_library_root",
                        "asset_geometry_cache", "asset_category_index", "semantic_aliases",
                        "scene_layout_interiors", "scene_reference_catalog", "default_scene"):
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
        def attach_catalog_aliases(adapter):
            # An explicit semantic_aliases file is authoritative.  For
            # built-in/demo documents without one, preserve aliases published
            # alongside the asset document instead of silently dropping them
            # from the live Qwen catalog.
            aliases = (self.load_semantic_aliases() if self.semantic_aliases is not None
                       else getattr(getattr(adapter, "metadata", None), "aliases", {}))
            adapter.catalog_aliases = dict(aliases or {})
            return adapter

        if self.asset_library_root is not None:
            if (Path(self.asset_library_root) / "models" / "model_index.json").is_file():
                from .adapters.final_models_library import FinalModelsLibraryAdapter
                adapter = FinalModelsLibraryAdapter(self.asset_library_root, self.asset_geometry_cache,
                    self.asset_category_index, library_ref_prefix=self.library_ref_prefix)
                return attach_catalog_aliases(adapter)
            if self.asset_geometry_cache is None:
                raise ValueError("asset_geometry_cache_required")
            from .adapters.local_asset_library import LocalAssetLibraryAdapter
            adapter = LocalAssetLibraryAdapter(self.asset_library_root, self.asset_geometry_cache,
                self.asset_category_index, library_ref_prefix=self.library_ref_prefix)
            return attach_catalog_aliases(adapter)
        from .adapters.demo_asset_library import DemoAssetLibrary
        if self.assets is not None:
            adapter = DemoAssetLibrary(json.loads(Path(self.assets).read_text(encoding="utf-8")))
            return attach_catalog_aliases(adapter)
        data = json.loads(files("robot_agent_brain.resources").joinpath("assets.json").read_text(encoding="utf-8"))
        adapter = DemoAssetLibrary(data)
        return attach_catalog_aliases(adapter)

    def bootstrap_settings(self):
        settings = {}
        if self.asset_library_root is None and self.assets is None:
            settings = json.loads(files("robot_agent_brain.resources").joinpath("demo_platform.json").read_text(encoding="utf-8"))
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

    def load_scene_reference_catalog(self):
        from .semantics.scene_references import SceneReferenceCatalog, SceneReferenceSpec
        if self.scene_reference_catalog is None:
            return SceneReferenceCatalog()
        value = json.loads(Path(self.scene_reference_catalog).read_text(encoding="utf-8"))
        if not isinstance(value, dict) or not isinstance(value.get("scene_references"), list):
            raise ValueError("scene_reference_catalog_invalid")
        specs = []
        for item in value["scene_references"]:
            if not isinstance(item, dict) or not isinstance(item.get("canonical_id"), str):
                raise ValueError("scene_reference_catalog_invalid")
            aliases = item.get("aliases", [])
            if not isinstance(aliases, list) or any(not isinstance(alias, str) for alias in aliases):
                raise ValueError("scene_reference_catalog_invalid")
            specs.append(SceneReferenceSpec(canonical_id=item["canonical_id"], aliases=tuple(aliases),
                kind=item.get("kind", "environment"), selector=item.get("selector", "semantic"),
                allow_default=bool(item.get("allow_default", False))))
        return SceneReferenceCatalog(specs)

    def load_defaults(self):
        resource = Path(self.defaults) if self.defaults else files("robot_agent_brain.resources").joinpath("defaults.json")
        return LayoutDefaults.model_validate_json(resource.read_text(encoding="utf-8"))
