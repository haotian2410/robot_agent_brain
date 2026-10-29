import json
from importlib.resources import files
from ..semantics.robot_interactions import RobotInteractionLexicon


def _load_prompt(filename: str) -> str:
    content = files("robot_agent_brain.models.prompt_templates").joinpath(filename).read_text(encoding="utf-8")
    if not content.strip():
        raise RuntimeError(f"prompt template is empty: {filename}")
    return content


def _load_task_understanding_v3() -> str:
    route_dir = "task_understanding"
    names = ("common.txt", "route_selection.txt", "scene_edit.txt", "scene_query.txt",
             "robot_task.txt", "session_control.txt", "output_contract.txt")
    return "\n\n".join(files("robot_agent_brain.models.prompt_templates").joinpath(route_dir, name)
                         .read_text(encoding="utf-8") for name in names)


# Keep the mature v2 examples/rules while appending the shorter v3 route
# contract.  The latter is intentionally last so its entity/reference split is
# the live instruction, and v2 providers can still consume the historical file.
TASK_UNDERSTANDING_PROMPT = (_load_prompt("task_understanding_v2.txt") + "\n\n" +
                             _load_task_understanding_v3() + "\n" + RobotInteractionLexicon.prompt_rules())
VISION_GROUNDING_PROMPT = _load_prompt("vision_grounding_v1.txt")
SKILL_PLANNING_PROMPT = _load_prompt("skill_planning_v2.txt")
DUAL_SKILL_PLANNING_PROMPT = _load_prompt("dual_skill_planning_v3.txt")


def prompt_payload(value) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
