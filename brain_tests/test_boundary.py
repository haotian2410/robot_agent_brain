import ast
from pathlib import Path


def test_brain_source_has_no_physics_or_legacy_control_imports():
    root = Path(__file__).parents[1] / "src" / "robot_agent_brain"
    forbidden = {"mujoco", "robot_agent_control", "executionbundle", "interaction_registry", "mjcf", "ikfast", "ompl", "fcl"}
    for path in root.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [item.name.casefold() for item in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [(node.module or "").casefold()]
            else:
                continue
            assert not forbidden.intersection(names), f"forbidden import in {path}: {names}"
