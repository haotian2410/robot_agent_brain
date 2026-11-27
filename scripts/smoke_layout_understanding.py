"""Real U routing smoke using configured OLS, without scene/Control effects."""
import argparse
import json
from pathlib import Path
import httpx
from robot_agent_brain.config import BrainConfig
from robot_agent_brain.models.qwen_http import QwenHTTPProvider
from robot_agent_brain.pipeline import BrainPipeline


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--missing-count", action="store_true",
                        help="Audit unquantified layouts: must clarify, never invent a quantity")
    parser.add_argument("--dual-semantics", action="store_true",
                        help="Read-only explicit-arm and same-arm understanding audit; no controller claims")
    parser.add_argument("--quantity-range", action="store_true",
                        help="Audit explicit quantity bounds versus exact-count automatic spacing")
    parser.add_argument("--round-dimensions", action="store_true",
                        help="Audit explicit circle/ring/arc dimensions without scene mutation")
    args = parser.parse_args()
    if sum((args.missing_count, args.dual_semantics, args.quantity_range, args.round_dimensions)) > 1:
        parser.error("choose one audit mode")
    config = BrainConfig.load(args.config)
    assets = config.load_assets()
    args.output_dir.mkdir(parents=True, exist_ok=False)
    requests, results = [], []
    def record(request):
        if request.method == "POST":
            requests.append(json.loads(request.content))
    with httpx.Client(timeout=120, event_hooks={"request": [record]}) as client:
        response = client.get(config.base_url.rstrip("/") + "/models")
        response.raise_for_status()
        provider = QwenHTTPProvider(config.base_url, response.json()["data"][0]["id"],
            client=client, live_catalog=True, understanding_wire_format="compact_v1")
        pipeline = BrainPipeline(provider, assets)
        cases = [
            ("在桌面新增六个苹果，排列成两行三列", "scene_layout", "grid", 6),
            ("在桌面新增五个苹果，沿半径20厘米的圆周均匀排列", "scene_layout", "circle", 5),
            ("新增三个苹果和三个香蕉，苹果香蕉交替排成一条线，中心间距10厘米", "scene_layout", "alternating", 6),
            ("在桌面新增五个苹果，均匀围成一圈", "scene_layout", "circle", 5),
        ]
        if args.missing_count:
            cases = [(instruction, None, None, None) for instruction in (
                "在空桌面上用苹果摆成字母A",
                "在空桌面上新增苹果排成一圈",
                "在空桌面上新增苹果和香蕉交替排列",
            )]
        if args.dual_semantics:
            cases = [(instruction, None, None, None) for instruction in (
                "用左臂抓起苹果，用右臂抓起香蕉",
                "用右臂抓起苹果，用左臂抓起香蕉",
                "用同一只机械臂先抓起苹果并放下，再抓起香蕉并放下，不指定左右臂",
            )]
        if args.quantity_range:
            cases = [(instruction, "scene_layout", "line", 10) for instruction in (
                "在桌面新增苹果排成一条线，优先10个，放不下允许自动调整到2至10个，间距自动",
                "在桌面新增苹果排成一条线，允许自动选择2至10个，没有优先数量，间距自动",
                "在桌面新增恰好10个苹果排成一条线，间距自动，但数量不能改变",
            )]
        if args.round_dimensions:
            cases = [
                ("在桌面新增六个苹果排成圆形，半径固定为20厘米", "scene_layout", "circle", 6),
                ("在桌面新增六个苹果，均匀排列在圆环区域内，内半径固定为10厘米，外半径固定为20厘米", "scene_layout", "ring", 6),
                ("在桌面新增六个苹果，沿圆弧均匀排列，半径固定为20厘米，圆心角90度", "scene_layout", "arc", 6),
            ]
        for number, (instruction, route, pattern, count) in enumerate(cases, 1):
            call_start, wire_start = len(provider.calls), len(requests)
            item = {"case": number, "instruction": instruction, "scene_published": False,
                    "control_called": False}
            try:
                turn = pipeline.understand_turn(instruction, scene=None)
                item["canonical"] = turn.model_dump(mode="json")
                spec = turn.arrangement_spec
                item["passed"] = (turn.status == "accepted" and turn.turn_kind == route
                    and spec is not None and spec.pattern.kind == pattern
                    and spec.items.requested_count == count)
                if number == 4 and spec is not None:
                    item["passed"] = (item["passed"] and spec.pattern.radius_m is None
                                      and spec.spacing.mode == "auto" and spec.spacing.auto)
                if args.missing_count:
                    item["passed"] = (turn.status == "clarification_required"
                                      and spec is None)
                if args.quantity_range and spec is not None:
                    if number < 3:
                        item["passed"] = (item["passed"] and spec.items.count_mode == "auto"
                            and spec.items.auto_count and spec.items.min_count == 2
                            and spec.items.max_count == 10)
                    else:
                        item["passed"] = (item["passed"] and spec.items.count_mode == "exact"
                            and spec.items.min_count is None and spec.items.max_count is None)
                if args.round_dimensions and spec is not None:
                    from robot_agent_brain.planning.layout_constraints import validate_explicit_layout_constraints
                    validate_explicit_layout_constraints(instruction, spec)
                    item["dimension_validation"] = "passed"
                    item["passed"] = (item["passed"] and spec.items.count_mode == "exact"
                                      and not spec.items.auto_count)
                if args.dual_semantics:
                    intent = turn.task_intent
                    item["passed"] = False
                    if turn.status == "accepted" and turn.turn_kind == "robot_task" and intent:
                        names = {entity.entity_id: entity.semantic_name for entity in intent.entities}
                        operations = intent.operations
                        item["binding_summary"] = [{"operation": str(op.task_type),
                            "object": names.get(op.source or op.target), "arm": op.arm,
                            "same_arm_group": op.same_arm_group} for op in operations]
                        if number < 3:
                            expected = {"apple": "left", "banana": "right"} if number == 1 else {
                                "apple": "right", "banana": "left"}
                            item["passed"] = len(operations) == 2 and {
                                names.get(op.source or op.target): op.arm for op in operations} == expected and all(
                                    str(op.task_type) == "grasp" for op in operations)
                        else:
                            groups = {op.same_arm_group for op in operations}
                            item["passed"] = (len(operations) == 4 and len(groups) == 1
                                              and None not in groups
                                              and all(op.arm is None for op in operations)
                                              and [(str(op.task_type), names.get(op.source or op.target))
                                                   for op in operations] == [
                                                       ("grasp", "apple"), ("release", "apple"),
                                                       ("grasp", "banana"), ("release", "banana")])
            except Exception as error:
                item.update(passed=False, error_type=type(error).__name__,
                    error_code=getattr(error, "code", None), error=str(error))
            item.update(calls=provider.calls[call_start:], raw_values=provider.last_raw_values,
                        wire_requests=requests[wire_start:])
            (args.output_dir / f"case-{number:02d}.json").write_text(
                json.dumps(item, ensure_ascii=False, indent=2, default=str))
            results.append({k: v for k, v in item.items() if k not in {"canonical", "calls", "raw_values", "wire_requests"}})
            print(number, item["passed"], item.get("error", ""), flush=True)
    (args.output_dir / "report.json").write_text(json.dumps({"cases": results}, ensure_ascii=False, indent=2))
    return int(any(not item["passed"] for item in results))


if __name__ == "__main__":
    raise SystemExit(main())
