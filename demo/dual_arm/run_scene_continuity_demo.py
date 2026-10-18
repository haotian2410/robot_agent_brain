"""Deterministic Replay metadata demo, no Qwen and no physical execution."""
import argparse
import hashlib
import json
from pathlib import Path
import uuid

from robot_agent_brain.application import BrainApplication
from robot_agent_brain.config import BrainConfig
from robot_agent_brain.contracts.scene import SceneConfig
from robot_agent_brain.contracts.turn import BrainTurn
from robot_agent_brain.models.task_understanding import TaskParseOutput


class Replay:
    def understand_turn(self, request):
        return self.turn


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", default="var/dual-arm-audit-scenes")
    args = parser.parse_args()
    root = Path(args.output_dir).resolve() / uuid.uuid4().hex[:10]
    root.mkdir(parents=True)
    objects = []
    for identifier, name, category, pos, ref in (
        (0, "table", "surface", [0, 0, -.025], 1),
        (1, "apple", "fruit", [-.25, 0, .045], 2),
        (2, "banana", "fruit", [.25, 0, .025], 3),
    ):
        objects.append({"object_id_in_scene": identifier, "object_name_in_scene": name, "components": [
            {"component_type": "Transform", "properties": {"position": pos, "quaternion_xyzw": [0, 0, 0, 1], "scale": [1, 1, 1], "parent": None}},
            {"component_type": "Semantic", "properties": {"semantic_name": name, "category": category, "support": None if identifier == 0 else 0}},
            {"component_type": "MetadataRef", "properties": {"path": f"$DEMO_LIBRARY/{ref}"}},
        ]})
    scene = SceneConfig(scene_schema_version=1, scene_id=1, scene_version=0, scene_name="synthetic_replay", objects=objects)
    source = root / "input_scene.json"
    source.write_text(scene.model_dump_json(indent=2))
    provider = Replay()
    provider.turn = TaskParseOutput.model_validate({"entities": [{"id": "apple", "name": "apple", "category": "fruit"}],
        "operations": [{"type": "locate", "target": "apple"}]}).to_brain_turn("定位苹果")
    app = BrainApplication(BrainConfig(provider="replay", output_dir=str(root), scene_platform_object_ids={0}), provider=provider)
    reports = [app.handle("定位苹果", scene_path=source)]
    assert reports[0].run_status == "success", reports[0]
    session_id = reports[0].session_id
    baseline = root / session_id / "original_scene.json"
    digest = hashlib.sha256(baseline.read_bytes()).hexdigest()
    for basis, old, new, instruction in (
        ("original", "apple", "banana", "在原始场景把苹果替换为香蕉"),
        ("current", "banana", "apple", "在当前场景把最左边的香蕉替换为苹果"),
        ("original", "apple", "banana", "再次在原始场景把苹果替换为香蕉"),
    ):
        provider.turn = BrainTurn(status="accepted", turn_kind="scene_edit", instruction=instruction,
            scene_edit={"scene_basis": basis,
                "entities": [{"entity_id": "old", "semantic_name": old, "category": "fruit"},
                             {"entity_id": "new", "semantic_name": new, "category": "fruit"}],
                "relations": [{"scope": "selection", "subject": "old", "relation": "leftmost"}] if basis == "current" else [],
                "operations": [{"operation": "replace", "target": "old", "replacement_entity": "new"}]})
        report = app.handle(instruction, session_id=session_id)
        assert report.run_status == "success" and not report.executed, report
        assert "commands" not in report.artifacts
        assert hashlib.sha256(baseline.read_bytes()).hexdigest() == digest
        reports.append(report)
    names = []
    for report in reports:
        value = json.loads(Path(report.artifacts["scene_config"]).read_text())
        names.append(sorted(c["properties"]["semantic_name"] for obj in value["objects"] for c in obj["components"] if c["component_type"] == "Semantic"))
    assert names[1] == names[3] == ["banana", "banana", "table"]
    assert names[2] == ["apple", "banana", "table"]
    summary = {"provider": "replay", "real_qwen": False, "executed": False, "original_sha256": digest,
               "names_by_turn": names, "reports": [r.model_dump(mode="json") for r in reports]}
    output = root / "summary.json"
    output.write_text(json.dumps(summary, ensure_ascii=False, indent=2))
    print(output)


if __name__ == "__main__":
    main()
