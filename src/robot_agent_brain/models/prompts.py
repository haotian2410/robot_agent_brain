import json
import hashlib
from importlib.resources import files


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


def build_asset_catalog_prompt(assets) -> tuple[str, str]:
    """Build a deterministic, path-free OLS vocabulary for task understanding."""
    views = list(getattr(assets, "_assets", {}).values())
    if not views and hasattr(assets, "configuration_payload"):
        raw = assets.configuration_payload().get("assets", [])
        views = raw
    aliases = {
        "apple": ["苹果"], "banana": ["香蕉"], "baseball": ["棒球"],
        "basket": ["篮子", "筐"], "tray": ["托盘"], "mug": ["杯子", "马克杯", "coffee cup"],
        "pen": ["钢笔"], "screwdriver": ["螺丝刀"], "marker": ["马克笔"],
        "table": ["桌子", "桌面"], "coffee_table": ["茶几"], "sugar_box": ["糖盒"],
        "rubiks_cube": ["魔方"], "school_bell": ["铃铛"], "test_tube": ["试管"],
        "test_tube_rack": ["试管架"], "doll": ["玩偶"], "bottle": ["瓶子"],
        "can": ["罐子", "易拉罐"], "drawer": ["抽屉"], "cabinet": ["柜子"],
        "microwave": ["微波炉"], "button": ["按钮"], "gum_bottle": ["胶瓶"], "cream": ["护肤霜"],
    }
    rows = []
    for view in sorted(views, key=lambda x: (str(getattr(x, "asset_type", x.get("asset_type", "model") if isinstance(x, dict) else "model")),
                                              int(getattr(x, "library_asset_id", x.get("library_asset_id", 0) if isinstance(x, dict) else 0)))):
        if isinstance(view, dict):
            name = view.get("semantic_name", "")
            tags = view.get("tags", [])
            category = view.get("category") or "object"
            asset_type = view.get("asset_type", "model")
        else:
            name, tags, category, asset_type = view.semantic_name, view.tags, view.category or "object", view.asset_type
        rows.append({"semantic_name": name, "aliases": aliases.get(name, []), "tags": list(tags or ()), "category": category,
                     "scope": "robot" if asset_type == "robot" else "scene_model"})
    canonical = json.dumps(rows, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    lines = ["\n当前 OLS 资产词表（必须从中选择 semantic_name；不要输出数字 ID 或词表外名称）："]
    for row in rows:
        tags = ", ".join(row["tags"]) or "-"
        alias_text = ", ".join(row["aliases"]) or "-"
        lines.append(f"- {row['semantic_name']} | aliases={alias_text} | category={row['category']} | tags={tags} | scope={row['scope']}")
    lines.append("中文别名必须结合 tags 选择；例如杯子/cup/马克杯只能映射到词表中真实存在的 mug 或 cup。")
    lines.append("所有场景编辑位置都按桌面区域解释：左/右/前/后、角落和中间不表示桌外地面。")
    return "\n".join(lines), digest
