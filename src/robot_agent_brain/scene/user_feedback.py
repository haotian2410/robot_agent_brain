"""Public explanations; retain the original issue in per-turn diagnostic evidence."""


def _scene_contains_entity(scene, name):
    """Return whether a scene contains a plausible semantic/name match.

    This is intentionally only a feedback aid; actual grounding remains the
    authoritative selector.  It lets us distinguish "object absent" from a
    present-but-ambiguous reference without guessing an instance.
    """
    if scene is None or not name:
        return False
    needle = name.casefold().replace("-", "_")
    for obj in scene.objects:
        values = [obj.object_name_in_scene or ""]
        for component in obj.components:
            if component.component_type == "Semantic":
                values.append(str(component.properties.get("semantic_name") or ""))
        for value in values:
            normalized = value.casefold().replace("-", "_")
            if needle == normalized or needle in normalized or normalized in needle:
                return True
    return False


def _display_entity_name(name):
    return {"apple": "苹果", "banana": "香蕉", "basket": "篮子", "table": "桌面"}.get(name.casefold(), name)


def explain_issue(issue, exc, scene, assets):
    code = issue.code
    original = issue.message
    question = None
    if code == "asset_missing" or (code == "grounding_missing" and original.split(":", 1)[-1].strip().casefold() in {"box", "盒子"}):
        name = original.split(":", 1)[-1].strip()
        candidates = assets.find_by_category("container") if name.casefold() in {"box", "盒子"} else []
        names = list(dict.fromkeys(m.semantic_name + ("（" + "/".join(m.tags) + "）" if m.tags else "") for m in candidates))
        question = f"资产库中没有唯一对应“{name}”的模型。" + (
            "请明确选择：" + "、".join(names) + "；不会自动将盒子替换成篮子或糖盒。" if names else "请提供库中已有的具体模型名称。")
    elif code.startswith(("grounding_ambiguous", "grounding_binding_invalid", "query_reference_ambiguous", "dialogue_")):
        candidates = getattr(exc, "candidates", [])
        choices = "、".join(f"{o.object_name_in_scene}（#{o.object_id_in_scene}）" for o in candidates)
        if not choices and code == "query_reference_ambiguous" and "候选：" in original:
            choices = original.split("候选：", 1)[1]
        question = "无法唯一确定你指的是哪个物体。" + ("当前候选：" + choices + "。" if choices else "") + "请补充颜色、方位或实例编号；已删除对象不能继续作为指代。"
    elif code.startswith("grounding_missing"):
        original_detail = original.split(":", 1)[-1].strip()
        if original_detail.startswith("insufficient members for "):
            name = original_detail.removeprefix("insufficient members for ").strip()
            question = f"当前场景中“{_display_entity_name(name)}”的数量不足，无法完成本次操作。请先增加足够的对象，或减少数量。"
        elif original_detail and original_detail != "stale binding" and not _scene_contains_entity(scene, original_detail):
            question = f"当前场景中没有可绑定的“{_display_entity_name(original_detail)}”对象。请先增加该物体，或改用场景中已有的对象。"
        else:
            question = "当前场景无法确定所需对象或参照物。请说明场景中已有物体的名称、颜色或编号。"
    elif code in {"scene_reference_unresolved", "scene_reference_ambiguous"}:
        if code == "scene_reference_ambiguous":
            candidates = issue.details.get("candidates") or getattr(exc, "candidates", [])
            choices = "、".join(f"#{item}" for item in candidates)
            question = "当前场景中有多个可能的参照物" + (f"（{choices}）" if choices else "") + "，请明确参照物或编号。"
        else:
            raw = issue.value or original
            question = f"当前场景无法找到参照物“{raw}”。请说明场景中已有物体的名称、颜色或编号；不会猜测成桌面。"
    elif code.startswith(("scene_edit_reference", "scene_relation_reference", "query_subject_reference")):
        question = "当前场景无法确定所需参照物。请说明场景中已有物体的名称、颜色或编号。"
    elif code.startswith(("grounding_evidence_missing", "query_geometry", "query_visual", "scene_relation_evidence", "camera_not_configured", "vision_grounding_", "scene_attachment_pose", "asset_geometry_")):
        question = "当前缺少可靠的颜色、几何或图像证据，不能据此给出肯定或否定答案。请补充所需信息或检查场景相机与资产几何。"
    elif code == "asset_ambiguous":
        question = original.split(":", 1)[-1].strip()
    elif code.startswith("scene_scale_"):
        issue.message = "无法执行此缩放：对象必须明确允许缩放，并满足资产范围和局部轴限制；机器人、附件及承载物不能这样缩放。场景未改变。"
    elif code in {"scene_edit_support_footprint_exceeded", "scene_edit_workspace_exceeded", "scene_edit_support_invalid"}:
        issue.message = "编辑失败：目标位置超出原支撑面或可用工作区，或原支撑关系无法确认。请减小移动距离或选择桌面内的位置；场景未改变。"
    elif code == "scene_edit_inside_geometry_missing":
        question = "当前容器缺少可靠的内部空间数据，无法安全放置。请改用“放到容器旁边”，或选择具有内部几何的容器。"
    elif code == "scene_edit_inside_target_too_large":
        issue.message = "编辑失败：目标物体尺寸超过容器内部空间，场景未改变。"
    elif code == "scene_edit_inside_boundary_invalid":
        issue.message = "编辑失败：没有找到完全位于容器内部且不碰撞的位置，场景未改变。"
    elif code == "scene_edit_on_reference_not_support":
        question = "当前参照物没有可靠的顶部支撑面，无法执行“放在其上”。请改用桌面或明确的支撑面。"
    elif code == "scene_edit_position_ambiguous":
        question = "“桌子右边”未说明是在桌面右侧还是桌外地面。请明确说“桌面右侧”或补充支撑面。"
    elif code == "scene_edit_support_unknown":
        question = "无法确认目标物应放在哪个支撑面上。请明确桌面、托盘或其他可靠支撑物。"
    elif code == "scene_edit_properties_unsupported" or code == "scene_edit_property_unsupported":
        issue.message = "编辑失败：仅支持颜色属性和明确的放置位置字段，不能写入任意 properties；场景未改变。"
    elif code.startswith("unsupported_scene_layout_relation"):
        issue.message = "当前场景编辑关系暂不支持（" + original.split(":", 1)[-1].strip() + "），场景未改变。请使用左/右/前/后、旁边、桌面上或容器内部等明确表达。"
    elif code == "scene_edit_layout_collision":
        issue.message = "编辑失败：目标位置存在碰撞或超出可用范围，场景未改变。"
    elif code in {"provider_error", "model_output_invalid", "validation_failed"}:
        issue.message = "模型响应未通过语义校验，本轮未执行。请重新说明对象、动作和参照物；可凭诊断编号查看详细日志。"
    if question:
        issue.clarification_question = question
        issue.message = question
    if issue.message != original:
        issue.details["diagnostic_message"] = original
