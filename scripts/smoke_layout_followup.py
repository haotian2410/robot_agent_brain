"""Read-only real U follow-up audit against saved Scene and arrangement records."""
import argparse
import json
from pathlib import Path

import httpx
from robot_agent_brain.config import BrainConfig
from robot_agent_brain.application import BrainApplication
from robot_agent_brain.models.qwen_http import QwenHTTPProvider
from robot_agent_brain.adapters.scene_file_codec import SceneFileCodec
from robot_agent_brain.scene.arrangement_index import ArrangementIndex, ArrangementRecord


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    parser.add_argument("--scene", required=True, type=Path)
    parser.add_argument("--session-state", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--original-context-fixture", action="store_true",
                        help="Read-only synthetic branch contrast using saved Scene; does not alter a session")
    parser.add_argument("--explicit-spacing-fixture", action="store_true")
    args = parser.parse_args()
    if args.original_context_fixture and args.explicit_spacing_fixture:
        parser.error("choose one fixture mode")
    config = BrainConfig.load(args.config, overrides={"vision": False, "execution_enabled": False})
    args.output_dir.mkdir(exist_ok=False, parents=True)
    requests, results = [], []
    def record(request):
        if request.method == "POST":
            requests.append(json.loads(request.content))
    with httpx.Client(timeout=120, event_hooks={"request": [record]}) as client:
        response = client.get(config.base_url.rstrip("/") + "/models")
        response.raise_for_status()
        provider = QwenHTTPProvider(config.base_url, response.json()["data"][0]["id"],
            client=client, live_catalog=True, understanding_wire_format="compact_v1")
        app = BrainApplication(config, provider=provider)
        scene = SceneFileCodec(app.assets).load(args.scene)
        index = ArrangementIndex()
        for item in json.loads(args.session_state.read_text())["arrangement_records"]:
            index.put(ArrangementRecord.model_validate(item))
        context = index.understanding_context(scene)
        if len(context) != 1 or not context[0]["members_complete"] or len(context[0]["slots"]) != 6:
            raise ValueError("followup_fixture_requires_one_complete_six_member_group")
        (args.output_dir / "context.json").write_text(json.dumps(context, ensure_ascii=False, indent=2))
        original_context = None
        original_id = context[0]["arrangement_id"]
        instructions = (
            "再新增五个香蕉，在桌面右侧围成一圈",
            "把刚才那组六个苹果重新排成一行，中心间距10厘米",
        )
        if args.original_context_fixture:
            original_context = app.pipeline._understanding_scene_context(scene, index)
            original_context["basis"] = "original"
            replacement = ArrangementIndex()
            replacement.put(index.get(original_id).model_copy(update={"arrangement_id": "arr-current-fixture"}))
            index = replacement
            instructions = (
                "在原始场景中把那组六个苹果重新排成一行，中心间距10厘米",
                "在当前场景中把那组六个苹果重新排成一行，中心间距10厘米",
            )
            (args.output_dir / "fixture_context.json").write_text(json.dumps({
                "synthetic_branch_contrast": True, "current": index.understanding_context(scene),
                "original_snapshot": original_context}, ensure_ascii=False, indent=2))
        if args.explicit_spacing_fixture:
            instructions = ("在桌面新增两个苹果，排成一行，中心间距20厘米",
                            "在桌面新增两个苹果，排成一行，中心间距二十厘米")
        for number, instruction in enumerate(instructions, 1):
            start, wire = len(provider.calls), len(requests)
            item = {"instruction": instruction, "scene_published": False, "control_called": False}
            try:
                turn = app.pipeline.understand_turn(instruction, scene=scene, arrangement_index=index,
                                                   original_context=original_context)
                item["canonical"] = turn.model_dump(mode="json")
                spec = turn.arrangement_spec
                aliases = {asset.alias for asset in spec.items.assets} if spec is not None else set()
                item["passed"] = turn.status == "accepted" and spec is not None and (
                    (number == 1 and spec.operation == "create" and index.get(spec.arrangement_id) is None
                     and spec.items.requested_count == 5 and aliases == {"banana"}
                     and spec.pattern.kind == "circle" and spec.pattern.radius_m is None
                     and spec.spacing.mode == "auto" and spec.region.side == "right_half")
                    or (number == 2 and spec.operation == "rearrange" and index.get(spec.arrangement_id) is not None
                        and spec.items.requested_count == 6 and aliases == {"apple"}
                        and spec.pattern.kind == "line" and spec.spacing.mode == "center"
                        and spec.spacing.value_m == 0.1))
                if args.original_context_fixture:
                    item["passed"] = bool(turn.status == "accepted" and spec is not None
                        and spec.basis == ("original" if number == 1 else "current")
                        and spec.arrangement_id == (original_id if number == 1 else "arr-current-fixture")
                        and spec.operation == "rearrange" and spec.items.requested_count == 6
                        and aliases == {"apple"} and spec.pattern.kind == "line"
                        and spec.spacing.mode == "center" and spec.spacing.value_m == .1)
            except Exception as error:
                item.update(passed=False, error=str(error))
            if args.explicit_spacing_fixture and "canonical" in item:
                item["passed"] = bool(turn.status == "accepted" and spec is not None
                    and spec.operation == "create" and spec.basis == "current"
                    and spec.items.requested_count == 2 and aliases == {"apple"}
                    and spec.spacing.mode == "center" and spec.spacing.value_m == .2
                    and not spec.spacing.auto and spec.pattern.kind == "line")
            item.update(calls=provider.calls[start:], raw_values=provider.last_raw_values,
                        wire_requests=requests[wire:])
            (args.output_dir / f"case-{number:02}.json").write_text(json.dumps(item, ensure_ascii=False, indent=2, default=str))
            results.append({k: item[k] for k in ("instruction", "passed")})
            print(number, item["passed"], item.get("error", ""), flush=True)
    (args.output_dir / "report.json").write_text(json.dumps(results, ensure_ascii=False, indent=2))
    return int(any(not result["passed"] for result in results))


if __name__ == "__main__":
    raise SystemExit(main())
