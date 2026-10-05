import json
from importlib.resources import files
from ..semantics.robot_interactions import RobotInteractionLexicon


def _load_prompt(filename: str) -> str:
    content = files("robot_agent_brain.models.prompt_templates").joinpath(filename).read_text(encoding="utf-8")
    if not content.strip():
        raise RuntimeError(f"prompt template is empty: {filename}")
    return content


TASK_UNDERSTANDING_PROMPT = _load_prompt("task_understanding_v2.txt") + "\n" + RobotInteractionLexicon.prompt_rules()
VISION_GROUNDING_PROMPT = _load_prompt("vision_grounding_v1.txt")
SKILL_PLANNING_PROMPT = _load_prompt("skill_planning_v2.txt")


def prompt_payload(value) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
