"""Versioned, schema-directed U transport codec. Never rewrites user values."""
from __future__ import annotations

from copy import deepcopy
import json
import re

from jsonschema import Draft202012Validator

from .task_understanding import TaskParseWireOutput
from ..contracts.turn import SceneLayoutRelation
from ..contracts.scene_edit_rules import (
    MOTION_ALLOWED, REQUIRED, SCALE_FIELDS, SCALE_MODES, DISTANCE_FIELDS,
    LAYOUT_OPERATIONS, RELATION_PAIR, wire_fields,
)

VERSION = "u.compact.v1"
# Frozen protocol registry, shared by schema, prompt and codec. Do not renumber.
FIELDS = dict(zip(
    "action aliases all_available angle_deg arm arm_usage asset_choices asset_key assignment_mode axis camera_asset category category_only clarification_question color coordinate_frame count depends_on destination dialogue_ref dialogue_ref_set direction distance_m entities entity_id evidence_source exclude_scene_object_ids explicit_robot gripper_asset hold_constraints holder_arm holder_operation initial_robot_asset kind mode motion_direction motion_scale object_entity operation operation_id operations parallel_group parallel_required pivot placement_goal placement_hint placement_region placement_target posture predicate profile_id properties protocol_version quantity_mode query_type reference region region_entity relation relations replacement_entity robot_asset robot_asset_switch robot_setup_request scale_amount scale_direction scale_mode scale_xyz scene_basis scene_edit scene_object_ids scene_query scope select_count_from_candidates semantic_name session_control source status subject tags target while_operation".split(),
    "ac al aa ad ar au ch ak am ax ca c co q cl cf ct dp ds dr dz di dm e id es ex er ga hc ha ho ir ki mo md ms oe op oi o pg pr pi pl ph rg pt po pd pf p v qm qt rf re rn rl r rp ra rs rq sa sd sm sx sb se si sq sc sf n ss sr s su tg t wo".split(),
    strict=True,
))
FIELDS.update({
    "same_arm_group": "sg",
    "min_count": "ql", "max_count": "qu",
    "arrangement_spec": "at", "arrangement_id": "ai", "basis": "bs", "pattern": "pn",
    "items": "it", "assets": "as", "spacing": "sp", "orientation": "ot", "constraints": "cn", "seed": "zz", "auto": "ao",
    "source": "sr", "rows": "rw", "cols": "cx", "order": "od", "radius_m": "rm",
    "inner_radius_m": "ri", "outer_radius_m": "ro", "angle_span_deg": "ag", "text": "tx", "font": "ft",
    "description": "de", "path": "pa", "requested_count": "rc", "count_mode": "cm",
    "sequence": "uq", "auto_count": "af", "surface_ref": "sv", "anchor_ref": "ah", "side": "yd",
    "width_m": "wm", "depth_m": "wd", "margin_m": "mg", "value_m": "vm", "yaw_deg": "yw",
    "support": "sy", "keep_inside_region": "kr", "avoid_existing": "ae", "min_clearance_m": "mc",
    "allow_scale": "az", "mode": "mo", "alias": "ay",
})
FIELDS["turn_kind"] = "k"
assert len(set(FIELDS.values())) == len(FIELDS)


def _base(*, strict_layout=True):
    schema = TaskParseWireOutput.model_json_schema()
    # Unlike the legacy grammar, do not require inactive null payloads.
    schema["required"] = ["protocol_version", "turn_kind", "status"]
    schema["properties"]["protocol_version"] = {"const": VERSION, "type": "string"}
    schema["$defs"]["TaskEntityWire"]["required"] = ["entity_id", "semantic_name", "category"]
    for name in ("ArrangementSpacing", "ArrangementItems"):
        definition = schema["$defs"][name]
        definition["required"] = list(dict.fromkeys([*definition.get("required", []), "mode"]))
    definition = schema["$defs"]["ArrangementSpec"]
    definition["required"] = list(dict.fromkeys([*definition.get("required", []), "operation", "basis"]))
    definition = schema["$defs"]["ArrangementRegion"]
    definition["required"] = list(dict.fromkeys([*definition.get("required", []), "kind"]))
    if not strict_layout:
        return schema
    from ..contracts.arrangement import PATTERN_FIELDS, PATTERN_REQUIRED
    pattern = schema["$defs"]["ArrangementPattern"]
    branches = []
    for kind, allowed in PATTERN_FIELDS.items():
        for required in PATTERN_REQUIRED.get(kind, ((),)):
            properties = {key: deepcopy(value) for key, value in pattern["properties"].items()
                          if key in allowed | {"kind", "description"}}
            properties["kind"] = {"const": kind, "type": "string"}
            for key in required:
                properties[key] = _nonnull(properties[key])
            branches.append({"type": "object", "properties": properties,
                "required": ["kind", *required], "additionalProperties": False})
    schema["$defs"]["ArrangementPattern"] = {"anyOf": branches}
    from ..contracts.arrangement import ANCHOR_REGION_KINDS
    region = schema["$defs"]["ArrangementRegion"]
    branches = []
    for kind in region["properties"]["kind"]["enum"]:
        properties = deepcopy(region["properties"])
        properties["kind"] = {"const": kind, "type": "string"}
        required = ["kind", "surface_ref"]
        if kind in ANCHOR_REGION_KINDS:
            properties["anchor_ref"] = _nonnull(properties["anchor_ref"])
            required.append("anchor_ref")
        else:
            properties.pop("anchor_ref")
        if kind == "relative":
            properties["side"].pop("default", None)
            properties["side"]["enum"] = [side for side in properties["side"]["enum"]
                                           if side not in {"center", "any"}]
            required.append("side")
        branches.append({"type": "object", "properties": properties,
                         "required": required, "additionalProperties": False})
    schema["$defs"]["ArrangementRegion"] = {"anyOf": branches}
    # Layout modes have inter-field requirements that Pydantic's generated
    # field schema alone does not represent. Constrain transport before decode;
    # never infer missing modes from an otherwise invalid response.
    spacing = schema["$defs"]["ArrangementSpacing"]
    branches = []
    for mode in ("center", "edge", "auto"):
        branch = deepcopy(spacing)
        branch["properties"]["mode"] = {"const": mode, "type": "string"}
        branch["required"] = ["mode", "auto"] if mode == "auto" else ["mode", "value_m"]
        branch["properties"]["auto"] = {"const": mode == "auto", "type": "boolean"}
        if mode != "auto":
            branch["properties"]["value_m"] = _nonnull(branch["properties"]["value_m"])
        else:
            branch["properties"]["value_m"] = {"type": "null"}
        branches.append(branch)
    schema["$defs"]["ArrangementSpacing"] = {"anyOf": branches}
    items = schema["$defs"]["ArrangementItems"]
    branches = []
    for mode in ("single", "counts", "sequence"):
        branch = deepcopy(items)
        branch["properties"]["mode"] = {"const": mode, "type": "string"}
        branch["required"] = list(dict.fromkeys([*branch.get("required", []), "mode"]))
        if mode == "single":
            branch["properties"]["assets"]["maxItems"] = 1
        if mode == "sequence":
            branch["required"].append("sequence")
            branch["properties"]["sequence"] = _nonnull(branch["properties"]["sequence"])
            branch["properties"]["sequence"]["minItems"] = 1
        branches.append(branch)
    schema["$defs"]["ArrangementItems"] = {"anyOf": branches}
    return schema


def _schema(node):
    if isinstance(node, list):
        return [_schema(v) for v in node]
    if not isinstance(node, dict):
        return node
    result = {}
    for key, value in node.items():
        if key in {"title", "description"}:
            continue
        if key == "properties":
            result[key] = {FIELDS[k]: _schema(v) for k, v in value.items()}
        elif key == "required":
            result[key] = [FIELDS[k] for k in value]
        elif key in {"default", "enum", "const"}:
            result[key] = deepcopy(value)
        else:
            result[key] = _schema(value)
    return result


def _nonnull(field):
    """Remove null only, never select an arbitrary operation union branch."""
    field = deepcopy(field)
    if "anyOf" in field:
        choices = [x for x in field["anyOf"] if x.get("type") != "null"]
        field = choices[0] if len(choices) == 1 else {"anyOf": choices}
    field.pop("default", None)
    return field


def _edit_schema(base):
    """Closed disjoint operation branches, generated from canonical rules.

    Enumerate structural alternatives rather than relying on if/then or
    dependentRequired, which are not enforced by all grammar backends.
    Scene/entity equality and placement-goal conflicts remain Python checks.
    """
    properties = base["properties"]
    branches = []
    for operation in MOTION_ALLOWED:
        fields = wire_fields(operation)
        modes = [({}, set(), set())]
        if operation == "scale":
            modes = [({}, set(mode), set(SCALE_FIELDS) - set(mode)) for mode in SCALE_MODES]
        elif operation == "translate":
            modes = [({}, set(), set(DISTANCE_FIELDS))] + [
                ({}, {key}, set(DISTANCE_FIELDS) - {key}) for key in DISTANCE_FIELDS]
        elif operation in LAYOUT_OPERATIONS:
            modes = [({"relation": {"type": "string", "const": "on"}}, set(RELATION_PAIR), set()),
                     ({"relation": {"type": "string", "enum": [
                         r.value for r in SceneLayoutRelation if r != SceneLayoutRelation.ON]}},
                      set(RELATION_PAIR), {"placement_region"})]
            if operation != "move_relative":
                modes.insert(0, ({}, set(), {*RELATION_PAIR, "placement_region"}))
            # A goal is an alternative canonical representation of the pair.
            if operation == "move_relative":
                modes.append(({}, {"placement_goal"}, {*RELATION_PAIR, "placement_region"}))
        for overrides, extra_required, excluded in modes:
            selected = fields - excluded
            # llama.cpp emits object keys in grammar property order. Put the
            # discriminator BEFORE operation-specific required parameters;
            # otherwise an op-first model response cannot choose rotate.
            ordered = ["operation", "target", *sorted(selected - {"operation", "target"})]
            props = {FIELDS[key]: _nonnull(properties[FIELDS[key]]) for key in ordered}
            props[FIELDS["operation"]] = {"type": "string", "const": operation}
            props.update({FIELDS[key]: value for key, value in overrides.items()})
            required = {"operation", "target", *REQUIRED.get(operation, ()), *extra_required} - excluded
            branches.append({"type": "object", "properties": props,
                             "required": [FIELDS[key] for key in sorted(required)],
                             "additionalProperties": False})
    return {"anyOf": branches}


def compact_schema():
    schema = _schema(_base())
    # This is an opaque Scene property dictionary, not an entity's color
    # selector. Keep the public key intact and reject accidental aliasing.
    schema["$defs"]["SceneEditIntent"]["properties"]["p"] = {
        "type": "object", "properties": {"color": {"type": "string"}},
        "additionalProperties": False,
    }
    schema["$defs"]["SceneEditIntent"] = _edit_schema(schema["$defs"]["SceneEditIntent"])
    props = schema["properties"]
    variants = []
    routes = {
        "robot_task": ("e o", "e o r au hc rq ir"),
        "scene_edit": ("se", "se ir"),
        "scene_layout": ("at", "at"),
        "scene_query": ("sq", "sq ir"),
        "session_control": ("ss", "ss ir"),
    }
    for kind, (required, allowed) in routes.items():
        keys = "v s k " + allowed
        fields = {key: deepcopy(props[key]) for key in keys.split()}
        fields["k"] = {"const": kind, "type": "string"}
        fields["s"] = {"const": "accepted", "type": "string"}
        for key in required.split():
            if fields[key].get("type") == "array":
                fields[key]["minItems"] = 1
            if "anyOf" in fields[key]:
                fields[key] = next(b for b in fields[key]["anyOf"] if b.get("type") != "null")
        variants.append({"type": "object", "properties": fields,
                         "required": ["v", "s", "k", *required.split()], "additionalProperties": False})
    for config_field in ("rs", "rq"):
        fields = {key: deepcopy(props[key]) for key in ("v", "s", "k", config_field)}
        fields["k"] = {"const": "robot_config", "type": "string"}
        fields["s"] = {"const": "accepted", "type": "string"}
        fields[config_field] = next(b for b in fields[config_field]["anyOf"] if b.get("type") != "null")
        variants.append({"type": "object", "properties": fields,
                         "required": ["v", "s", "k", config_field], "additionalProperties": False})
    fields = {key: deepcopy(props[key]) for key in ("v", "s", "k", "q")}
    fields["s"] = {"enum": ["clarification_required", "unsupported_task"], "type": "string"}
    fields["q"] = {"type": "string", "minLength": 1}
    variants.append({"type": "object", "properties": fields,
                     "required": ["v", "s", "k", "q"], "additionalProperties": False})
    return {"anyOf": variants, "$defs": schema["$defs"]}


def _walk(value, node, root, *, encode):
    if "$ref" in node:
        node = root["$defs"][node["$ref"].split("/")[-1]]
    if "anyOf" in node:
        # The codec walks canonical field types, NOT the operation union in
        # the wire grammar. Only unwrap nullable types; never pick branch 0.
        options = [option for option in node["anyOf"] if option.get("type") != "null"]
        if value is None and len(options) < len(node["anyOf"]):
            return None
        if len(options) != 1:
            raise ValueError("u_wire_ambiguous_schema_node")
        return _walk(value, options[0], root, encode=encode)
    if isinstance(value, list) and "items" in node:
        return [_walk(v, node["items"], root, encode=encode) for v in value]
    if isinstance(value, dict) and "properties" in node:
        props = node["properties"]
        mapping = {k: FIELDS[k] for k in props} if encode else {FIELDS[k]: k for k in props}
        result = {}
        for key, item in value.items():
            if key not in mapping:
                raise ValueError(f"u_wire_unknown_field:{key}")
            canonical = key if encode else mapping[key]
            field = props[canonical]
            # Only omit declared defaults and optional default-factory arrays.
            if encode and canonical not in node.get("required", []):
                if ("default" in field and item == field["default"]) or (
                        item == [] and field.get("type") == "array"):
                    continue
            result[mapping[key]] = _walk(item, field, root, encode=encode)
        return result
    # Open dictionaries (e.g. color properties) and strings are opaque data.
    return deepcopy(value)


def encode(value):
    value = deepcopy(value)
    value["protocol_version"] = VERSION
    root = _base(strict_layout=False)
    return _walk(value, root, root, encode=True)


def decode(value):
    Draft202012Validator(compact_schema()).validate(value)
    root = _base(strict_layout=False)
    canonical = _walk(value, root, root, encode=False)
    canonical["protocol_version"] = "task_understanding.v3.1"
    edit = canonical.get("scene_edit") or {}
    for index, operation in enumerate(edit.get("operations", [])):
        if bool(operation.get("relation")) != bool(operation.get("reference")):
            raise ValueError(f"u_wire_relation_reference_pair:scene_edit.operations[{index}]")
    # Route validity, defaults, pairing, targets and assets remain authoritative
    # in the existing canonical parser and request-scoped catalog validator.
    return canonical


def compact_prompt(prompt):
    """Translate output examples and identifiers, preserving enum/data values."""
    # Remove the legacy envelope/null instructions, retaining routing rules.
    start, end = prompt.index("## 1. 顶层输出"), prompt.index("## 2. Turn 路由")
    header = (
        "## 1. 紧凑输出协议\n"
        f'只输出紧凑 JSON，v="{VERSION}"；k(任务类型)、s(状态)必须存在。\n'
        "accepted 必须包含对应路由的完整有效数据；其他路由字段省略。"
        "k=robot_task 时 e 和 o 都必填且非空，选择关系 r 不能替代操作 o；"
        "k=scene_edit 时 se 必填；k=scene_layout 时 at 必填；k=scene_query 时 sq 必填；k=session_control 时 ss 必填。"
        "clarification_required/unsupported_task 必须有具体 q，不带可执行数据。\n"
        "省略可选 null、空数组及 Schema 中已声明的默认值；不得省略操作目标、"
        "必需参照物或新增/替换的资产选择。关系和参照必须同时存在或同时省略。\n"
        "动作、关系、资产名等值不缩写；输入 scene_context/目录的字段不改变。\n"
        "每个实体必须有 id(本轮标识)、n(规范资产名称)、c(类别)。"
        "ex 是用户明确排除的已有场景实例编号；没有明确排除时完全省略 ex，"
        "绝不能枚举数字或生成场景中没有的编号。si 同样只用于用户明确指定编号。\n"
        '实体颜色筛选字段为 cl；编辑属性 p 内部不缩写，改色必须写 p={"color":"blue"}，不能写 p.cl。\n'
    )
    body = prompt[:start] + prompt[end:]
    body = body.replace("未指定型号时 initial_robot_asset=null", "未指定型号时省略 initial_robot_asset")
    body = body.replace("`posture` 是每个场景操作的必填字段", "`posture` 仅在 orient 操作必填")
    body = body.replace("其他操作写 `posture=null`", "其他操作省略 posture")
    body = body.replace("为 null/空数组", "省略").replace("同时为 `null`", "同时省略")
    body = body.replace("必须为 `null`", "必须省略").replace("为 null。", "省略。")
    # JSON code blocks are transformed structurally when complete.
    def block(match):
        text = match.group(2)
        try:
            value = json.loads(text)
        except (ValueError, TypeError):
            return match.group(0)
        def keys(v):
            if isinstance(v, dict):
                return {FIELDS.get(k, k): (VERSION if k == "protocol_version" else
                                          x if k == "properties" else keys(x)) for k, x in v.items()
                        if x is not None and x != []}
            if isinstance(v, list):
                return [keys(x) for x in v]
            return v
        return '```json\n' + json.dumps(keys(value), ensure_ascii=False, separators=(",", ":")) + '\n```'
    body = re.sub(r"```(json|text)\n(.*?)\n```", block, body, flags=re.S)
    # Protect JSON values, enum names, input-field paths, and already converted
    # JSON blocks; transform remaining output identifiers in prose.
    enums = set()
    def enum_values(node):
        if isinstance(node, dict):
            enums.update(v for v in node.get("enum", []) if isinstance(v, str))
            for v in node.values(): enum_values(v)
        elif isinstance(node, list):
            for v in node: enum_values(v)
    enum_values(_base())
    pattern = r'```.*?```|"[^"\n]*"|\b(?:properties|scene_context|workspace|asset_catalog)\.[\w.]+|\b[a-z_][a-z_0-9]*\b'
    def token(match):
        word = match.group(0)
        if word.startswith("properties."):
            return "p." + word.removeprefix("properties.")
        if word.startswith('"'):
            return '"' + FIELDS.get(word[1:-1], word[1:-1]) + '"' if body[match.end():].lstrip().startswith(':') else word
        if word in enums:
            return word
        return FIELDS.get(word, word)
    body = re.sub(pattern, token, body, flags=re.S)
    # Enum names can also name payload fields; an explicit generated table
    # disambiguates these few prose references without changing semantic values.
    table = json.dumps(FIELDS, ensure_ascii=False, separators=(",", ":"))
    example = encode({"status": "accepted", "turn_kind": "robot_task",
        "entities": [{"entity_id": "apple", "semantic_name": "apple", "category": "fruit"},
                     {"entity_id": "basket", "semantic_name": "basket", "category": "container"}],
        "operations": [{"operation": "pick_and_place", "source": "apple", "destination": "basket",
                        "placement_target": {"kind": "container_interior", "reference": "basket", "relation": "inside"}}]})
    add_example = encode({"status": "accepted", "turn_kind": "scene_edit", "scene_edit": {
        "entities": [{"entity_id": "apple", "semantic_name": "apple", "category": "fruit", "count": 2, "quantity_mode": "all"},
                     {"entity_id": "tray", "semantic_name": "tray", "category": "container"}],
        "operations": [{"operation": "add", "target": name, "relation": "on", "reference": "table"}
                       for name in ("apple", "tray")],
        "asset_choices": [{"entity_id": "apple", "asset_key": "model:1"},
                          {"entity_id": "tray", "asset_key": "model:17"}]}})
    return header + "字段对应表（仅字段名转换，值不转换）：" + table + "\n" + body + (
        "\n紧凑输出完整示例：让机械臂把苹果放进篮子\n" +
        json.dumps(example, ensure_ascii=False, separators=(",", ":")) +
        "\n在桌面增加两个苹果和一个托盘（示例资产键仅为格式演示，必须使用本次目录的实际键）：\n" +
        json.dumps(add_example, ensure_ascii=False, separators=(",", ":")) +
        "每个 add/replace 必须有 se.ch 资产选择；可选字段不需要为了完整而输出。\n" +
        "\n没有用到的字段不输出，禁止为了凑齐字段生成排除编号、额外动作或默认参数。\n")
