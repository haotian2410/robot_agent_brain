"""Alternating real-Qwen U-only benchmark: never obtains a lease or runs Control."""
import argparse
from dataclasses import replace
import importlib.util
import json
from pathlib import Path
import random
import shutil
import statistics
import time

from robot_agent_brain.application import BrainApplication
from robot_agent_brain.config import BrainConfig
from robot_agent_brain.contracts.scene import SceneConfig
from robot_agent_brain.models.qwen_http import QwenHTTPProvider
from robot_agent_brain.models.task_understanding import TaskUnderstandingRequest


def dump(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str) + "\n")


def check(case, turn):
    kind, status = turn.turn_kind.value, turn.status.value
    if case == "clarification":
        return status == "clarification_required" and bool(turn.clarification_question)
    if status != "accepted":
        return False
    if case in {"robot", "recovered"}:
        task = turn.task_intent
        return kind == "robot_task" and bool(task.operations)
    if case == "query":
        return kind == "scene_query" and turn.scene_query.query_type == "relation"
    if kind != "scene_edit":
        return False
    ops = turn.scene_edit.operations
    if case == "color":
        return len(ops) == 1 and ops[0].operation == "update_properties" and ops[0].properties.get("color") in {"blue", "蓝色", "#0000FF", "#0000ff"}
    return {e.semantic_name: e.count for e in turn.scene_edit.entities} == {"apple": 2, "tray": 1} and all(o.operation == "add" for o in ops)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--config", type=Path, required=True)
    p.add_argument("--scene", type=Path, required=True)
    p.add_argument("--baseline", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--repeat", type=int, default=5)
    p.add_argument("--cases", default="add,color,query,robot,clarification,recovered")
    p.add_argument("--groups", default="baseline,dedup,compact")
    p.add_argument("--reuse-completed", type=Path, help="Reuse completed samples only when the exact request matches")
    p.add_argument("--max-tokens", type=int, default=2048)
    p.add_argument("--bootstrap", action="store_true", help="Use the actual first-turn bootstrap context")
    p.add_argument("--add-instruction", default="在桌面上增加两个苹果和一个托盘")
    args = p.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    config = BrainConfig.load(args.config)
    assert not config.execution_enabled
    def no_platform(*a, **kw):
        raise AssertionError("benchmark_platform_access_forbidden")
    app = BrainApplication(config, platform_factory=no_platform)
    pipeline = app.pipeline
    scene = None if args.bootstrap else SceneConfig.model_validate_json(args.scene.read_text())
    context = pipeline._understanding_scene_context(None if args.bootstrap else scene)
    spec = importlib.util.spec_from_file_location("robot_agent_brain.models._old_prompts", args.baseline / "prompts.py")
    old = importlib.util.module_from_spec(spec); spec.loader.exec_module(old)
    # The archived module resolves templates in its own directory.
    old_catalog, _ = old.build_asset_catalog_prompt(pipeline.asset_catalog)
    instructions = {
        "add": args.add_instruction,
        "color": "把苹果改成蓝色",
        "query": "苹果在篮子左边吗？",
        "robot": "让机械臂把苹果放进篮子",
        "clarification": "把它放到那里",
        "recovered": "让机械臂把最左边的苹果放进篮子",
    }
    providers = {name: QwenHTTPProvider(config.base_url, config.model,
        timeout=config.timeout, understanding_wire_format="compact_v1" if name == "compact" else "full",
        asset_catalog=pipeline.asset_catalog) for name in args.groups.split(",")}
    baseline = providers.get("baseline")
    if baseline:
        original_build = baseline.build_understanding_request
        def build(request):
            return replace(original_build(request), prompt=old.TASK_UNDERSTANDING_PROMPT + old_catalog,
                           content=old.prompt_payload(request.model_dump(mode="json", exclude_none=True)))
        baseline.build_understanding_request = build
    for provider in providers.values():
        builder = provider.build_understanding_request
        provider.build_understanding_request = lambda request, builder=builder: replace(
            builder(request), max_completion_tokens=args.max_tokens)
    rng = random.Random(20261119)
    schedule = []
    for repeat in range(args.repeat):
        for case in args.cases.split(","):
            groups = list(providers); rng.shuffle(groups)
            schedule.extend((repeat + 1, case, group) for group in groups)
    dump(args.output / "schedule.json", schedule)
    results = []
    for repeat, case, group in schedule:
        provider = providers[group]
        request = TaskUnderstandingRequest(instruction=instructions[case], asset_catalog=pipeline.asset_catalog,
                                          workspace=pipeline.workspace_context, scene_context=context)
        directory = args.output / f"{case}-{repeat}-{group}"
        stage = provider.build_understanding_request(request)
        if args.reuse_completed:
            previous = args.reuse_completed / directory.name
            if (previous / "result.json").exists():
                if json.loads((previous / "request.json").read_text()) != stage.payload(provider.model):
                    raise ValueError(f"reuse_request_mismatch: {previous}")
                shutil.copytree(previous, directory)
                row = json.loads((previous / "result.json").read_text())
                row["reused_from"] = str(previous.resolve())
                dump(directory / "result.json", row)
                results.append(row)
                dump(args.output / "results.json", results)
                print(json.dumps(row, ensure_ascii=False), flush=True)
                continue
        directory.mkdir()
        provider.begin_turn(f"u-bench-{case}-{repeat}-{group}")
        start_index = len(provider.calls)
        stage = provider.build_understanding_request(request)
        dump(directory / "request.json", stage.payload(provider.model))
        row = {"case": case, "repeat": repeat, "group": group, "instruction": request.instruction,
               "first_provider_call": start_index == 0, "cache_hit": "not_assumed", "control_called": False}
        start = time.monotonic()
        try:
            turn = provider.understand_turn(request)
            dump(directory / "canonical.json", turn.model_dump(mode="json"))
            row.update(valid=True, expected_semantics=check(case, turn), status=turn.status.value, outcome=turn.turn_kind.value)
        except Exception as exc:
            row.update(valid=False, expected_semantics=False, error=str(exc), error_code=getattr(exc, "code", type(exc).__name__))
        row["seconds"] = time.monotonic() - start
        calls = provider.calls[start_index:]
        dump(directory / "calls.json", calls)
        dump(directory / "raw.json", provider.last_raw_text)
        row.update(calls=len(calls), prompt_tokens=sum(c.get("prompt_tokens", 0) for c in calls),
                   completion_tokens=sum(c.get("completion_tokens", 0) for c in calls))
        dump(directory / "result.json", row)
        results.append(row)
        dump(args.output / "results.json", results)
        print(json.dumps(row, ensure_ascii=False), flush=True)
    summary = {}
    for group in providers:
        rows = [r for r in results if r["group"] == group]
        summary[group] = {"n": len(rows), "valid": sum(r["valid"] for r in rows),
            "expected_semantics": sum(r["expected_semantics"] for r in rows),
            "retries": sum(max(0, r["calls"] - 1) for r in rows),
            **{k + "_median": statistics.median(r[k] for r in rows) for k in ["seconds", "prompt_tokens", "completion_tokens"]}}
    dump(args.output / "summary.json", summary)


if __name__ == "__main__":
    main()
