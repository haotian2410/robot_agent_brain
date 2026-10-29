"""Allowlisted deployment summaries and recursive diagnostic redaction."""
import hashlib
import json
from urllib.parse import urlsplit, urlunsplit


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def configuration_summary(config, assets, defaults):
    from .scene.colors import COLOR_POLICY_VERSION
    from .models.prompts import TASK_UNDERSTANDING_PROMPT, SKILL_PLANNING_PROMPT, DUAL_SKILL_PLANNING_PROMPT
    from .skills.registry import REGISTRY
    url = urlsplit(config.base_url)
    endpoint = urlunsplit((url.scheme, url.netloc.rsplit("@", 1)[-1], url.path, "", ""))
    metadata = getattr(assets, "metadata", None)
    asset_payload = (assets.configuration_payload() if hasattr(assets, "configuration_payload")
                     else metadata.model_dump(mode="json"))
    from .scene.layout_geometry import SceneLayoutGeometryRegistry
    layout_registry = SceneLayoutGeometryRegistry.from_path(config.scene_layout_interiors)
    scene_reference_catalog = config.load_scene_reference_catalog()
    return {"provider":config.provider, "model":config.model, "base_url":endpoint,
            "scene_scale_policy": config.scale_policy().model_dump(mode="json"),
            "query_near_distance_m": config.query_near_distance_m,
            "scene_layout_interiors_sha256": fingerprint(layout_registry.configuration_payload()),
            "color_policy_version": COLOR_POLICY_VERSION,
            "scene_id_bits": config.scene_id_bits,
            "editor_scene_manifests": config.editor_scene_manifests,
            "planner":config.planner, "planner_max_completion_tokens":config.planner_max_completion_tokens,
            "skill_planning_prompt_sha256":fingerprint(SKILL_PLANNING_PROMPT),
            "dual_skill_planning_prompt_sha256": fingerprint(DUAL_SKILL_PLANNING_PROMPT),
            "skill_catalog_sha256":fingerprint(REGISTRY.prompt_catalog()),
            "timeout":config.timeout, "structured_output":config.structured_output,
            "robot":config.robot, "seed":config.seed, "vision":config.vision,
            "robot_profiles_sha256": fingerprint(config.robot_profiles.model_dump(mode="json")),
            "component_reference_rules_sha256": fingerprint(config.component_reference_rules),
            "scene_robot_profile": config.scene_robot_profile,
            "scene_platform_object_ids": sorted(config.scene_platform_object_ids) if config.scene_platform_object_ids is not None else None,
            "allow_scene_reset": config.allow_scene_reset,
            "demo_assets":getattr(assets, "demo_assets", getattr(metadata, "demo_assets", False)),
            "assets_sha256":fingerprint(asset_payload),
            "semantic_aliases_sha256":fingerprint(config.load_semantic_aliases()),
            "scene_reference_catalog_sha256": fingerprint(scene_reference_catalog.configuration_payload()),
            "bootstrap_settings_sha256":fingerprint(config.bootstrap_settings()),
            "default_table_metadata_ref":config.default_table_metadata_ref,
            "default_robot_metadata_ref":config.default_robot_metadata_ref,
            "default_scene_edit_assets":config.default_scene_edit_assets,
            "scene_layout_policy_version":"grid-v2",
            "scene_layout_clearance_m": getattr(defaults, "clearance_m", None),
            "scene_layout_grid_size": config.scene_layout_grid_size,
            "scene_layout_near_clearance_m": config.scene_layout_near_clearance_m,
            "robot_driver_sha256":fingerprint(config.default_robot_driver.model_dump(mode="json")
                                               if config.default_robot_driver is not None else None),
            "defaults_sha256":fingerprint(defaults.model_dump(mode="json")),
            "understanding_prompt_sha256":fingerprint(TASK_UNDERSTANDING_PROMPT)}


def redact(value, secret=None):
    if isinstance(value, dict):
        return {key:("[REDACTED]" if key.casefold() in {"authorization", "api_key", "access_token", "password"}
                     else redact(item, secret)) for key,item in value.items()}
    if isinstance(value, list):
        return [redact(item, secret) for item in value]
    if isinstance(value, str) and secret:
        return value.replace(secret, "[REDACTED]")
    return value
