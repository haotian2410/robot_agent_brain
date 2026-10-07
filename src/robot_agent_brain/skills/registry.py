from pydantic import BaseModel, ConfigDict
from ..contracts.skill_plan import SkillName
from ..errors import BrainError


class SkillDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    name: SkillName
    description: str
    prompt_signature: str
    requires_target: bool = True
    allowed_regions: tuple[str, ...] = ()
    preconditions: tuple[str, ...] = ()
    effects: tuple[str, ...] = ()
    planner_visible: bool = True


class AtomicSkillRegistry:
    def __init__(self, definitions):
        definitions = tuple(definitions)
        self.definitions = {d.name: d for d in definitions}
        if len(self.definitions) != len(definitions):
            raise ValueError("duplicate skill definition")

    def require(self, name):
        if name not in self.definitions:
            raise BrainError("planner_unknown_skill", "skill_planning", str(name))
        return self.definitions[name]

    def prompt_catalog(self):
        return "\n".join(d.model_dump_json(exclude={"planner_visible"})
                         for d in self.definitions.values() if d.planner_visible)


REGISTRY = AtomicSkillRegistry([
    SkillDefinition(name="locate", description="定位已知语义目标", prompt_signature="locate(target)", effects=("target located",)),
    SkillDefinition(name="move", description="到达语义区域，或按已有操作语义移动握持物体", prompt_signature="move(target, reference?, region?)",
        allowed_regions=("grasp_region", "placement_region", "button_surface"),
        preconditions=("region target located", "placement requires held source", "directional move requires held actor"), effects=("region reached or requested displacement completed",)),
    SkillDefinition(name="grasp", description="抓取目标", prompt_signature="grasp(target)",
        preconditions=("gripper empty", "target reached at grasp_region"), effects=("target held",)),
    SkillDefinition(name="release", description="释放握持物体", prompt_signature="release(target, reference?, region?)",
        allowed_regions=("placement_region",), preconditions=("target held", "placement requires destination reached"), effects=("gripper empty",)),
    SkillDefinition(name="press", description="按压按钮", prompt_signature="press(target)",
        preconditions=("gripper empty", "button_surface reached"), effects=("button pressed",)),
    SkillDefinition(name="pull", description="经已握持接触物拉开目标", prompt_signature="pull(target, reference?)",
        preconditions=("contact target held",), effects=("target opened",)),
    SkillDefinition(name="push", description="推闭目标", prompt_signature="push(target, reference?)",
        preconditions=("target located", "gripper empty"), effects=("target closed",)),
])
