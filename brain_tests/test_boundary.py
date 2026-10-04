from pathlib import Path


def test_brain_source_has_no_physics_or_legacy_control_imports():
    root = Path(__file__).parents[1] / "src" / "robot_agent_brain"
    forbidden = ("import mujoco", "from mujoco", "robot_agent_control", "ExecutionBundle", "interaction_registry")
    for path in root.rglob("*.py"):
        text = path.read_text(encoding="utf-8").casefold()
        for token in forbidden:
            assert token.casefold() not in text, f"{token} found in {path}"

