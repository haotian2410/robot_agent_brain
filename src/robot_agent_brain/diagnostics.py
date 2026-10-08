"""Allowlisted deployment summaries and recursive diagnostic redaction."""
import hashlib
import json
from urllib.parse import urlsplit, urlunsplit


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def configuration_summary(config, assets, defaults):
    from .models.prompts import TASK_UNDERSTANDING_PROMPT, SKILL_PLANNING_PROMPT
    from .skills.registry import REGISTRY
    url = urlsplit(config.base_url)
    endpoint = urlunsplit((url.scheme, url.netloc.rsplit("@", 1)[-1], url.path, "", ""))
    metadata = getattr(assets, "metadata", None)
    asset_payload = (assets.configuration_payload() if hasattr(assets, "configuration_payload")
                     else metadata.model_dump(mode="json"))
    return {"provider":config.provider, "model":config.model, "base_url":endpoint,
            "planner":config.planner, "planner_max_completion_tokens":config.planner_max_completion_tokens,
            "skill_planning_prompt_sha256":fingerprint(SKILL_PLANNING_PROMPT),
            "skill_catalog_sha256":fingerprint(REGISTRY.prompt_catalog()),
            "timeout":config.timeout, "structured_output":config.structured_output,
            "robot":config.robot, "seed":config.seed, "vision":config.vision,
            "demo_assets":getattr(assets, "demo_assets", getattr(metadata, "demo_assets", False)),
            "assets_sha256":fingerprint(asset_payload),
            "semantic_aliases_sha256":fingerprint(config.load_semantic_aliases()),
            "bootstrap_settings_sha256":fingerprint(config.bootstrap_settings()),
            "default_table_metadata_ref":config.default_table_metadata_ref,
            "default_robot_metadata_ref":config.default_robot_metadata_ref,
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
