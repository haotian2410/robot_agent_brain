"""Allowlisted deployment summaries and recursive diagnostic redaction."""
import hashlib
import json
from urllib.parse import urlsplit, urlunsplit


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def configuration_summary(config, assets, defaults):
    from .models.prompts import TASK_UNDERSTANDING_PROMPT
    url = urlsplit(config.base_url)
    endpoint = urlunsplit((url.scheme, url.netloc.rsplit("@", 1)[-1], url.path, "", ""))
    return {"provider":config.provider, "model":config.model, "base_url":endpoint,
            "timeout":config.timeout, "structured_output":config.structured_output,
            "robot":config.robot, "seed":config.seed, "vision":config.vision,
            "demo_assets":assets.metadata.demo_assets,
            "assets_sha256":fingerprint(assets.metadata.model_dump(mode="json")),
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
