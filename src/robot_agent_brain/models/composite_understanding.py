"""One U response containing ordered, independently validated wire payloads."""
from copy import deepcopy


def composite_wire_schema(turn_schema):
    payload = deepcopy(turn_schema)
    definitions = payload.pop("$defs", {})
    schema = {
        "type": "object", "additionalProperties": False, "required": ["phases"],
        "properties": {"phases": {"type": "array", "minItems": 2, "maxItems": 6,
            "items": {"type": "object", "additionalProperties": False,
                      "required": ["instruction", "payload"], "properties": {
                          "instruction": {"type": "string", "minLength": 1}, "payload": payload}}}},
    }
    if definitions:
        schema["$defs"] = definitions
    return schema


COMPOSITE_ENVELOPE_RULES = """
本次是一次理解的“场景阶段→机器人阶段”复合任务。
上面的协议字段规则应用于每个阶段的 payload，而不是最外层。
最外层仅输出 {"phases":[{"instruction":"阶段原文","payload":{...}}]}。
先给出一个或多个 scene_edit/scene_layout 阶段，最后给出一个 robot_task 阶段。
保留整句的对象、数量、指代、显式机械臂、关系和操作顺序，不自行执行或预测场景位姿。
机器人阶段引用新建对象的语义实体，不编造实例 ID；后续 Python 会基于提交后的场景绑定。
不要因为混合编辑和操作要求用户重复确认顺序，不输出分解后仍需重新理解的空 payload。
"""
