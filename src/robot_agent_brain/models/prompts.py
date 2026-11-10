import json
import hashlib
from importlib.resources import files
from ..contracts.asset_catalog import AssetCatalogSnapshot


def _load_prompt(filename: str) -> str:
    content = files("robot_agent_brain.models.prompt_templates").joinpath(filename).read_text(encoding="utf-8")
    if not content.strip():
        raise RuntimeError(f"prompt template is empty: {filename}")
    return content


def _join(values) -> str:
    return "、".join(str(value) for value in values)


def _literal_values(annotation):
    """Collect nested ``Literal`` members so value lists never drift from a contract."""
    from typing import Literal, get_args, get_origin
    if get_origin(annotation) is Literal:
        return list(get_args(annotation))
    return [value for item in get_args(annotation) for value in _literal_values(item)]


def build_spatial_reference_tables() -> str:
    """Render the spatial vocabulary straight from the live contracts.

    Spatial wording is shared by every route, so the accepted values must not
    be copied by hand into one route's section: a hand-maintained list is how
    the robot route lost region and extremum vocabulary in the first place.
    """
    from ..contracts.spatial import (BINARY_SPATIAL_RELATIONS, EXTREME_SPATIAL_RELATIONS,
                                     HALF_SPATIAL_RELATIONS, PLACEMENT_HINTS,
                                     PLACEMENT_TARGET_KINDS, RelationScope, SpatialRelationType,
                                     TABLETOP_REGIONS)
    from ..contracts.turn import SceneQueryIntent
    from ..semantics import spatial_phrases
    from ..semantics.domain_policy_registry import DomainPolicyRegistry
    from ..semantics.robot_interactions import RobotInteractionLexicon

    registry = DomainPolicyRegistry()
    aliases_by_region: dict[str, list[str]] = {}
    for phrases, region in spatial_phrases.TABLETOP_REGION_PHRASES:
        aliases_by_region.setdefault(region, []).extend(phrases)
    ordered = list(SpatialRelationType)
    halves = _join(item.value for item in ordered if item in HALF_SPATIAL_RELATIONS)
    extremes = _join(item.value for item in ordered if item in EXTREME_SPATIAL_RELATIONS)
    binary = _join(item.value for item in ordered if item in BINARY_SPATIAL_RELATIONS)
    query_predicates = _join(_literal_values(SceneQueryIntent.model_fields["predicate"].annotation))
    lines = ["\n## 附录：空间语义取值表（由 Python 契约生成，请勿手改）",
             "",
             "`relations` 数组的条目形状对 `scene_edit`、`robot_task`、`scene_query` 完全相同：",
             "```text",
             '{"scope":"selection","subject":"<entity_id>","relation":"<关系取值>","reference":null}',
             "```",
             f"- `scope`：{_join(item.value for item in RelationScope)}；缺省 `selection`。"
             "`goal` 只是提示，`state` 本期没有消费者，不要输出。",
             "- `subject` 必须是本轮已声明的 `entity_id`；`reference` 是另一个实体或已注册环境引用，"
             "不得等于 `subject`。",
             f"- 半区关系（筛选候选；`reference` 可选，为 null 时按世界原点切分，写支撑面时按该面中心切分）：{halves}。",
             f"- 极值关系（筛选候选；解析器不使用 `reference`，必须为 null）：{extremes}。",
             f"- 二元关系（必须带 `reference`）：{binary}。",
             f"- `scene_query.predicate` 取值：{query_predicates}。",
             "  `predicate` 只与 `query_type=relation` 同时出现，其它查询类型必须为 null，"
             "空间约束写进 `scene_query.relations`。",
             f"- `scene_edit.operations[].relation` 取值：{_join(sorted(registry.supported_scene_relations()))}；"
             "与 `reference` 同时出现或同时为 null。",
             "- 桌面区域对 `scene_edit.operations[].placement_region` 和 "
             "`robot_task.operations[].placement_target.region` 使用同一组取值："]
    for region in TABLETOP_REGIONS:
        lines.append(f"  - `{region}`：{_join(aliases_by_region.get(region, []))}")
    lines += [f"- `scene_edit.operations[].placement_hint` 取值：{_join(PLACEMENT_HINTS)}；"
              "“中间/正中央/中心位置”用 `placement_hint=center`，机器人落点本期没有中心字段。",
              f"- `placement_target.kind` 取值：{_join(PLACEMENT_TARGET_KINDS)}；"
              "`relative_object` 必须同时给 `reference` 和 `relation`，`free_space` 的 `relation` 必须为 null。",
              f"- 机器人能力名称：{_join(sorted(registry.supported_robot_actions()))}。",
              "",
              RobotInteractionLexicon.prompt_rules()]
    return "\n".join(lines) + "\n"


# There is one runtime source of truth for first-stage understanding.  The
# historical v2 file and route/lexicon fragments remain in the package as
# migration/reference material, but are deliberately not concatenated here:
# fragment order previously made duplicate rules compete and caused Qwen to
# emit a legacy scene_edit envelope.
TASK_UNDERSTANDING_PROMPT = _load_prompt("task_understanding_clean_v3.txt") + build_spatial_reference_tables()
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
        # Generic/direct callers and live Brain requests both use aliases
        # attached to the exact adapter revision when no override is passed.
        # Production adapters reserve canonical names (for example a real
        # ``cup`` entry) before exposing aliases, so this is catalog data and
        # not a process-wide cup->mug replacement rule.
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
        # Keep the complete OLS directory visible to the model while making
        # the safety boundary explicit.  ``category`` is an asset taxonomy,
        # not an instruction about whether the object can be added to a
        # tabletop scene; passive URDF mechanisms and robot platforms need a
        # distinct usage label so Qwen does not treat every catalog row as a
        # normal scene-edit candidate.
        if item.availability_reason == "passive_scene_model":
            usage = "scene_object_without_joint_control"
        elif item.availability_reason == "passive_mechanism_only":
            usage = "passive_mechanism_capability_boundary"
        elif item.asset_type == "robot" or item.availability_reason == "robot_platform_only":
            usage = "robot_platform_capability_boundary"
        elif (item.category or "").casefold() in {"surface", "support_surface", "table"}:
            usage = "support_surface"
        elif (item.category or "").casefold() in {"container", "receptacle"}:
            usage = "container"
        else:
            usage = "ordinary_scene_object"
        rows.append({"asset_key": item.asset_key, "semantic_name": item.name,
                     "display_name": item.display_name or item.name,
                     "display_name_chinese": item.display_name_chinese or "",
                     "aliases": list(item.aliases), "tags": list(item.tags),
                     "category": item.category or "object",
                     "scope": "robot" if item.asset_type == "robot" else "scene_model",
                     "selectable_for_add": item.selectable_for_add,
                     "availability_reason": item.availability_reason,
                     "usage": usage,
                     "can_place": item.can_place})
    lines = ["\n当前 OLS 资产目录（revision=%s）。新建/替换只能选择其中真实存在的 asset_key；不要输出目录外名称、数字实例ID或本地路径：" % snapshot.revision]
    lines.append("tags 是物体语义标签（中文），用于匹配用户指令中的物体描述。从用户指令中提取相关标签填入 entities[].tags 数组。")
    for row in rows:
        aliases_text = ", ".join(row["aliases"]) or "-"
        tags = ", ".join(row["tags"]) or "-"
        reason = row["availability_reason"] or "available"
        chinese = row["display_name_chinese"]
        display = f'{row["display_name"]}/{chinese}' if chinese else row["display_name"]
        can_place = str(row["can_place"]).lower()
        lines.append(f"- {row['asset_key']} | semantic_name={row['semantic_name']} | display={display} | aliases={aliases_text} | category={row['category']} | tags={tags} | usage={row['usage']} | availability={reason} | add={str(row['selectable_for_add']).lower()} | can_place={can_place} | scope={row['scope']}")
    if snapshot.scenes:
        lines.append("当前 OLS 场景模板（仅用于场景上下文/预设选择，不可作为 scene_edit.add 的物体）：")
        for item in snapshot.scenes:
            lines.append(f"- {item.scene_key} | scene_name={item.name} | display={item.display_name or item.name}")
    assembly_catalog = getattr(assets, "robot_assembly_catalog", None)
    if callable(assembly_catalog):
        lines.append("OLS 机器人/配件装配目录（只用于语义选择；是否能规划仍由 RobotProfile 决定）：")
        try:
            assembly_items = assembly_catalog(registered_profiles or ())
        except TypeError:
            assembly_items = assembly_catalog()
        for item in assembly_items:
            aliases_text = ", ".join(item.get("aliases") or ()) or "-"
            lines.append("- {asset_key} | semantic_name={semantic_name} | role={role} | aliases={aliases} | "
                         "connect_joints={connect_joints} | connect_links={connect_links} | child_link={child_link} | "
                         "profile_registered={profile_registered}".format(
                             asset_key=item.get("asset_key"), semantic_name=item.get("semantic_name"),
                             role=item.get("role"), aliases=aliases_text,
                             connect_joints=",".join(item.get("connect_joints") or ()) or "-",
                             connect_links=",".join(item.get("connect_links") or ()) or "-",
                             child_link=item.get("child_link") or "-",
                             profile_registered=str(bool(item.get("profile_registered"))).lower()))
    lines.append("目录中的 mug 与 cup 是两个不同资产；只有当当前目录实际列出 cup 时才选择 cup。不要自行做名称替换。")
    lines.append("场景编辑统一在主桌面工作域解释：右/东=+X，前/北=+Y，上=+Z；角落和中间不表示桌外地面。")
    return "\n".join(lines), snapshot.revision.removeprefix("sha256:")
