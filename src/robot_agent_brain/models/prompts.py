import json
from importlib.resources import files


def _load_prompt(filename: str) -> str:
    content = files("robot_agent_brain.models.prompt_templates").joinpath(filename).read_text(encoding="utf-8")
    if not content.strip():
        raise RuntimeError(f"prompt template is empty: {filename}")
    return content


# There is one runtime source of truth for first-stage understanding.  The
# historical v2 file and route/lexicon fragments remain in the package as
# migration/reference material, but are deliberately not concatenated here:
# fragment order previously made duplicate rules compete and caused Qwen to
# emit a legacy scene_edit envelope.
TASK_UNDERSTANDING_PROMPT = _load_prompt("task_understanding_clean_v3.txt")
VISION_GROUNDING_PROMPT = _load_prompt("vision_grounding_v1.txt")
SKILL_PLANNING_PROMPT = _load_prompt("skill_planning_v2.txt")
DUAL_SKILL_PLANNING_PROMPT = _load_prompt("dual_skill_planning_v3.txt")


def prompt_payload(value) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
