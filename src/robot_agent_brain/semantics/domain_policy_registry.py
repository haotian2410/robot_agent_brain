"""Single source of semantic aliases and capability vocabulary."""
from dataclasses import dataclass, field

from .scene_references import SceneReferenceCatalog, SceneReferenceSpec
from ..contracts.turn import SceneLayoutRelation, TurnKind


@dataclass
class DomainPolicyRegistry:
    reference_catalog: SceneReferenceCatalog = field(default_factory=SceneReferenceCatalog)
    scene_relations: set[str] = field(default_factory=lambda: {item.value for item in SceneLayoutRelation})
    robot_actions: set[str] = field(default_factory=lambda: {
        "locate", "search", "move", "grasp", "release", "pick_and_place", "press", "open", "close",
    })

    def supported_turn_kinds(self):
        return set(TurnKind)

    def supported_scene_relations(self):
        return set(self.scene_relations)

    def supported_robot_actions(self):
        return set(self.robot_actions)

    def known_scene_reference_specs(self):
        return list(self.reference_catalog.specs())

    def prompt_rules_for(self, route):
        relation_rules = "场景编辑规范关系：" + ", ".join(sorted(self.scene_relations))
        action_rules = "机器人能力名称：" + ", ".join(sorted(self.robot_actions))
        if route == TurnKind.SCENE_EDIT:
            return relation_rules + "。" + action_rules + "。场景编辑引用由 SceneReferenceCatalog 绑定；几何和能力由 Python 校验。"
        if route == TurnKind.SCENE_QUERY:
            return relation_rules + "。场景查询只读取当前确认快照，不产生编辑或机器人操作。"
        if route == TurnKind.ROBOT_TASK:
            return action_rules + "。机器人任务在语义抽取后再由能力 registry 判定可执行性。"
        return ""
