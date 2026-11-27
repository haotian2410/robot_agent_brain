"""Replay saved layout U evidence into private OLS scene candidates only."""
import argparse
import json
from pathlib import Path
from robot_agent_brain.config import BrainConfig
from robot_agent_brain.application import BrainApplication
from robot_agent_brain.adapters.scene_file_codec import SceneFileCodec
from robot_agent_brain.contracts.turn import BrainTurn
from robot_agent_brain.planning.layout_planner import plan_arrangement
from robot_agent_brain.scene.scene_manager import SceneManager
from robot_agent_brain.web.protocol import digest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--evidence-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    config = BrainConfig.load(args.config, overrides={"vision": False})
    app = BrainApplication(config, provider=object())
    scene = SceneFileCodec(app.assets).load(config.default_scene)
    catalog_revision = app.assets.catalog_snapshot(registered_profiles=[]).revision
    args.output_dir.mkdir(parents=True, exist_ok=False)
    summary = []
    for path in sorted(args.evidence_dir.glob("case-*.json")):
        saved = json.loads(path.read_text())
        output = args.output_dir / path.stem
        output.mkdir()
        before = scene.model_dump(mode="json")
        result = {"source": str(path.resolve()), "instruction": saved["instruction"],
                  "scene_published": False, "control_called": False, "before_digest": digest(scene)}
        (output / "scene_before.json").write_text(json.dumps(before, ensure_ascii=False, indent=2))
        try:
            turn = BrainTurn.model_validate(saved["canonical"])
            if turn.turn_kind != "scene_layout" or turn.status != "accepted":
                raise ValueError("layout_audit_requires_accepted_layout")
            if turn.asset_catalog_revision != catalog_revision:
                raise ValueError("asset_catalog_revision_conflict")
            plan = plan_arrangement(turn.arrangement_spec, font_registry=config.layout_fonts)
            candidate = app.pipeline.scene_editor.layout_result(turn.arrangement_spec, plan, scene,
                                                               defaults=app.defaults)
            manager = SceneManager(scene)
            manager.apply_patch(candidate.patch)
            assert scene.model_dump(mode="json") == before
            assert manager.scene.scene_version == scene.scene_version + 1
            assert len(candidate.created_object_ids) == turn.arrangement_spec.items.requested_count
            (output / "scene_candidate.json").write_text(json.dumps(manager.scene.model_dump(mode="json"), ensure_ascii=False, indent=2))
            (output / "patch.json").write_text(candidate.patch.model_dump_json(indent=2))
            result.update(status="candidate_valid", after_digest=digest(manager.scene),
                          created_ids=candidate.created_object_ids, assumptions=candidate.assumptions)
        except Exception as error:
            assert scene.model_dump(mode="json") == before
            result.update(status="rejected", error_type=type(error).__name__, error=str(error))
        (output / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2))
        summary.append(result)
        print(path.stem, result["status"], result.get("error", ""), flush=True)
    (args.output_dir / "report.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2))
    return int(not summary or any(r["status"] != "candidate_valid" for r in summary))


if __name__ == "__main__":
    raise SystemExit(main())
