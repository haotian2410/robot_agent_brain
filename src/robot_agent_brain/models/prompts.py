import json
import hashlib
from importlib.resources import files
from ..contracts.asset_catalog import AssetCatalogSnapshot


def _load_prompt(filename: str) -> str:
    content = files("robot_agent_brain.models.prompt_templates").joinpath(filename).read_text(encoding="utf-8")
    if not content.strip():
        raise RuntimeError(f"prompt template is empty: {filename}")
    return content


# There is one runtime source of truth for first-stage understanding.  The
# historical v2 file and route/lexicon fragments remain in the package as
# migration/reference material, but are deliberately not concatenated here:
# fragment order previously made duplicate rules compete and caused Qwen to
# emit a legacy scene_edit envelope.
TASK_UNDERSTANDING_PROMPT = _load_prompt("task_understanding_clean_v3.txt")
VISION_GROUNDING_PROMPT = _load_prompt("vision_grounding_v1.txt")
SKILL_PLANNING_PROMPT = _load_prompt("skill_planning_v2.txt")
DUAL_SKILL_PLANNING_PROMPT = _load_prompt("dual_skill_planning_v3.txt")


def prompt_payload(value) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _snapshot_for_assets(assets, aliases=None, registered_profiles=None):
    """Obtain a public catalog snapshot; never inspect adapter private maps."""
    if isinstance(assets, AssetCatalogSnapshot):
        return assets
    if hasattr(assets, "catalog_snapshot"):
        # Generic/direct callers retain the historical resolver aliases for
        # compatibility (and the legacy prompt unit tests).  Live Brain
        # requests explicitly pass ``aliases={}`` from Application/Pipeline,
        # so the authoritative Qwen catalog never inherits cup->mug silently.
        return assets.catalog_snapshot(
            aliases=aliases if aliases is not None else getattr(assets, "catalog_aliases", {}),
            registered_profiles=registered_profiles or ())
    # Small legacy fakes may only expose a serialized configuration payload.
    # This fallback is intentionally read-only and is not used by production
    # adapters, which all implement catalog_snapshot().
    rows = []
    payload = assets.configuration_payload() if hasattr(assets, "configuration_payload") else {}
    for item in payload.get("assets", []):
        if not isinstance(item, dict):
            continue
        kind = item.get("asset_type", "model")
        identifier = item.get("library_asset_id")
        if identifier is None:
            continue
        rows.append({"asset_key": f"{kind}:{identifier}", "name": item.get("semantic_name", ""),
                     "display_name": item.get("semantic_name", ""), "aliases": (),
                     "tags": tuple(item.get("tags") or ()), "category": item.get("category"),
                     "asset_type": kind, "metadata_ref": item.get("metadata_ref"),
                     "selectable_for_add": kind == "model"})
    from ..contracts.asset_catalog import CatalogAsset
    models = [CatalogAsset.model_validate(x) for x in rows if x["asset_type"] == "model"]
    robots = [CatalogAsset.model_validate(x) for x in rows if x["asset_type"] == "robot"]
    return AssetCatalogSnapshot.from_items(models, robots)


def build_asset_catalog_prompt(assets, aliases=None, *, snapshot=None, registered_profiles=None) -> tuple[str, str]:
    """Build deterministic path-free OLS vocabulary from one catalog revision."""
    snapshot = snapshot or _snapshot_for_assets(assets, aliases, registered_profiles)
    rows = []
    for item in (*snapshot.models, *snapshot.robots):
        rows.append({"asset_key": item.asset_key, "semantic_name": item.name,
                     "display_name": item.display_name or item.name,
                     "aliases": list(item.aliases), "tags": list(item.tags),
                     "category": item.category or "object",
                     "scope": "robot" if item.asset_type == "robot" else "scene_model",
                     "selectable_for_add": item.selectable_for_add})
    lines = ["\n当前 OLS 资产目录（revision=%s）。新建/替换只能选择其中真实存在的 asset_key；不要输出目录外名称、数字实例ID或本地路径：" % snapshot.revision]
    for row in rows:
        aliases_text = ", ".join(row["aliases"]) or "-"
        tags = ", ".join(row["tags"]) or "-"
        lines.append(f"- {row['asset_key']} | semantic_name={row['semantic_name']} | display={row['display_name']} | aliases={aliases_text} | category={row['category']} | tags={tags} | add={str(row['selectable_for_add']).lower()} | scope={row['scope']}")
    if snapshot.scenes:
        lines.append("当前 OLS 场景模板（仅用于场景上下文/预设选择，不可作为 scene_edit.add 的物体）：")
        for item in snapshot.scenes:
            lines.append(f"- {item.scene_key} | scene_name={item.name} | display={item.display_name or item.name}")
    lines.append("目录中的 mug 与 cup 是两个不同资产；只有当当前目录实际列出 cup 时才选择 cup。不要自行做名称替换。")
    lines.append("场景编辑统一在主桌面工作域解释：右/东=+X，前/北=+Y，上=+Z；角落和中间不表示桌外地面。")
    return "\n".join(lines), snapshot.revision.removeprefix("sha256:")
