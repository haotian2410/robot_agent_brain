"""Public explanations; retain the original issue in per-turn diagnostic evidence."""


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
    elif code.startswith(("grounding_missing", "scene_edit_reference", "scene_relation_reference", "query_subject_reference")):
        question = "当前场景无法确定所需对象或参照物。请说明场景中已有物体的名称、颜色或编号。"
    elif code.startswith(("grounding_evidence_missing", "query_geometry", "query_visual", "scene_relation_evidence", "camera_not_configured", "vision_grounding_", "scene_attachment_pose", "asset_geometry_")):
        question = "当前缺少可靠的颜色、几何或图像证据，不能据此给出肯定或否定答案。请补充所需信息或检查场景相机与资产几何。"
    elif code == "asset_ambiguous":
        question = original.split(":", 1)[-1].strip()
    elif code.startswith("scene_scale_"):
        issue.message = "无法执行此缩放：对象必须明确允许缩放，并满足资产范围和局部轴限制；机器人、附件及承载物不能这样缩放。场景未改变。"
    elif code in {"provider_error", "model_output_invalid", "validation_failed"}:
        issue.message = "模型响应未通过语义校验，本轮未执行。请重新说明对象、动作和参照物；可凭诊断编号查看详细日志。"
    if question:
        issue.clarification_question = question
        issue.message = question
    if issue.message != original:
        issue.details["diagnostic_message"] = original
