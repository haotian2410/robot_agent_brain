"""Public explanations; retain the original issue in per-turn diagnostic evidence."""
from ..asset_name_normalization import canonical_name


def _scene_contains_entity(scene, name):
    """Return whether a scene contains a plausible semantic/name match.

    This is intentionally only a feedback aid; actual grounding remains the
    authoritative selector.  It lets us distinguish "object absent" from a
    present-but-ambiguous reference without guessing an instance.
    """
    if scene is None or not name:
        return False
    needle = canonical_name(name)
    for obj in scene.objects:
        values = [obj.object_name_in_scene or ""]
        for component in obj.components:
            if component.component_type == "Semantic":
                values.append(str(component.properties.get("semantic_name") or ""))
        for value in values:
            normalized = canonical_name(value)
            if needle == normalized or needle in normalized or normalized in needle:
                return True
    return False


def _display_entity_name(name):
    return {"apple": "苹果", "banana": "香蕉", "basket": "篮子", "table": "桌面"}.get(name.casefold(), name)


def explain_issue(issue, exc, scene, assets):
    code = issue.code
    original = issue.message
    question = None
    if code == "robot_asset_unknown":
        name = original.split(":", 1)[-1].strip()
        question = (f"当前 OLS 目录中没有找到机械臂型号“{name}”。请核对并提供准确型号。"
                    "若已开启上下文恢复且当前空会话尚未初始化，可直接补充型号，保留原任务继续处理；"
                    "系统不会自动猜测或替换型号。")
    elif code == "asset_missing" or (code == "grounding_missing" and original.split(":", 1)[-1].strip().casefold() in {"box", "盒子"}):
        name = original.split(":", 1)[-1].strip()
        candidates = assets.find_by_category("container") if name.casefold() in {"box", "盒子"} else []
        names = list(dict.fromkeys(m.semantic_name + ("（" + "/".join(m.tags) + "）" if m.tags else "") for m in candidates))
        question = f"资产库中没有唯一对应“{name}”的模型。" + (
            "请明确选择：" + "、".join(names) + "；不会自动将盒子替换成篮子或糖盒。" if names else "请提供库中已有的具体模型名称。")
    elif code.startswith(("grounding_ambiguous", "grounding_binding_invalid", "query_reference_ambiguous", "dialogue_")):
        candidates = getattr(exc, "candidates", [])
        try:
            from ..scene.component_access import SceneIndex
            candidate_index = SceneIndex(scene)
        except Exception:
            candidate_index = None
        def candidate_name(item):
            name = str(item.object_name_in_scene or "").strip()
            if not name or name.casefold() in {"not a semantic identifier", "object"}:
                try:
                    semantic = candidate_index.semantic(item.object_id_in_scene) if candidate_index else None
                    name = str(semantic.semantic_name or "").strip() if semantic else name
                except Exception:
                    pass
            return name or "对象"
        choices = "、".join(f"{candidate_name(o)}（#{o.object_id_in_scene}）" for o in candidates)
        # Keep machine-readable candidate evidence with the result.  The UI only
        # needs clarification_question, while an object picker/diagnostic view
        # can use these stable IDs and positions without re-running grounding.
        if candidates:
            try:
                from ..scene.scene_graph import world_transform
                candidate_ids = [item.object_id_in_scene for item in candidates]
                issue.details["candidate_ids"] = candidate_ids
                issue.details["candidate_descriptions"] = [
                    {
                        "id": item.object_id_in_scene,
                        "name": candidate_name(item),
                        "position": {
                            "x": float(world_transform(scene, item.object_id_in_scene).position[0]),
                            "y": float(world_transform(scene, item.object_id_in_scene).position[1]),
                            "z": float(world_transform(scene, item.object_id_in_scene).position[2]),
                        },
                    }
                    for item in candidates
                ]
            except Exception:
                # Feedback must never turn a safe clarification into an internal
                # error merely because optional pose evidence is unavailable.
                issue.details["candidate_ids"] = [item.object_id_in_scene for item in candidates]
        if not choices and code == "query_reference_ambiguous" and "候选：" in original:
            choices = original.split("候选：", 1)[1]
        reason = getattr(exc, "reason", "")
        if reason:
            issue.details["grounding_reason"] = reason
        if reason.endswith("_tie"):
            relation_label = {
                "leftmost_tie": "左右位置相同",
                "rightmost_tie": "左右位置相同",
                "frontmost_tie": "前后位置相同",
                "backmost_tie": "前后位置相同",
                "highest_tie": "高度相同",
                "lowest_tie": "高度相同",
                "nearest_tie": "距离相同",
                "farthest_tie": "距离相同",
            }.get(reason, "比较结果相同")
            question = f"当前候选的{relation_label}，无法唯一选择。"
        elif reason == "vision_ambiguous":
            question = "视觉检测到了多个候选，但无法把它们唯一对应到场景对象。"
        else:
            question = "无法唯一确定你指的是哪个物体。"
        question += ("当前候选：" + choices + "。" if choices else "")
        question += "请补充颜色、比较级方位（如最左边/最右边）、位置或实例编号；已删除对象不能继续作为指代。"
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
    elif code in {"vision_output_schema_invalid", "vision_grounding_schema_invalid"}:
        issue.message = "视觉模型返回的物体框不合法，本轮未执行。请重试或检查相机图像；场景未改变。"
    elif code == "scene_edit_runtime_error":
        issue.message = "场景编辑计算失败，本轮未提交任何修改。请重试；场景未改变。"
    elif code.startswith(("grounding_evidence_missing", "query_geometry", "query_visual", "scene_relation_evidence", "camera_not_configured", "vision_grounding_", "scene_attachment_pose", "asset_geometry_")):
        question = "当前缺少可靠的颜色、几何或图像证据，不能据此给出肯定或否定答案。请补充所需信息或检查场景相机与资产几何。"
    elif code == "asset_ambiguous":
        question = original.split(":", 1)[-1].strip()
    elif code.startswith("scene_scale_"):
        issue.message = "无法执行此缩放：对象必须明确允许缩放，并满足资产范围和局部轴限制；机器人、附件及承载物不能这样缩放。场景未改变。"
    elif code == "scene_edit_workspace_exceeded":
        issue.message = "编辑失败：目标位置超出桌面可用编辑区域，场景未改变。请改用桌面内的位置。"
    elif code in {"scene_edit_support_footprint_exceeded", "scene_edit_support_invalid"}:
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
        relation = str(issue.details.get("relation") or "")
        direction = {
            "left_of": "左侧", "right_of": "右侧", "front_of": "前方", "behind": "后方",
        }.get(relation, "该位置")
        if relation in {"left_of", "right_of", "front_of", "behind"}:
            question = f"将按桌面区域处理“桌子{direction}”；当前无法在桌面找到满足碰撞和工作区约束的位置，请补充更具体的桌面区域。"
        else:
            question = "相对于桌面的位置不明确，请说明左/右/前/后或具体桌面区域。"
    elif code == "scene_edit_support_unknown":
        question = "无法确认目标物应放在哪个支撑面上。请明确桌面、托盘或其他可靠支撑物。"
    elif code == "scene_edit_default_surface_missing":
        question = "当前上传的空场景没有可确认的默认支撑面，无法安全放置对象。请加载包含桌面/工作台的场景，或先明确提供可靠支撑面。"
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
