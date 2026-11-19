#!/usr/bin/env python3
"""Concurrent benchmark for the production Brain/Qwen request stages.

This tool deliberately stops at the Qwen boundary.  It builds requests with
the same Brain contracts and provider request builders used by production,
then sends those requests concurrently to an already running OpenAI-compatible
server.  It never starts or restarts llama-server.
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import hashlib
import json
import os
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import httpx

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from robot_agent_brain.application import BrainApplication
from robot_agent_brain.config import BrainConfig
from robot_agent_brain.contracts.camera import CameraFrame
from robot_agent_brain.contracts.task_intent import (
    Operation,
    PlacementTarget,
    TaskEntity,
    TaskIntent,
    TaskType,
)
from robot_agent_brain.models.qwen_http import (
    QwenHTTPProvider,
    QwenStageRequest,
    _extract_json,
)
from robot_agent_brain.models.task_understanding import TaskUnderstandingRequest, parse_qwen_turn
from robot_agent_brain.models.vision_grounding import VisionEntity, VisionGroundingRequest, VisionGroundingOutput
from robot_agent_brain.planning.context_builder import build_planner_context
from robot_agent_brain.scene.component_access import SceneIndex
from robot_agent_brain.contracts.scene import SceneConfig
from robot_agent_brain.contracts.commands_atomic import AtomicCommandDraft


DEFAULT_CONCURRENCY = (1, 3, 5, 10, 20, 30, 50, 70, 100)
DEFAULT_CONFIG = ROOT / "config" / "webeditor.json"
DEFAULT_SCENE = ROOT.parent / "ObjectLibraryServer" / "data" / "scenes" / "3" / "ur5_table_sorting.json"


@dataclass(frozen=True)
class StageCase:
    stage: str
    input_kind: str
    request: QwenStageRequest
    fixture_meta: dict[str, Any]


def _sha(value: Any) -> str:
    if isinstance(value, bytes):
        raw = value
    elif isinstance(value, str):
        raw = value.encode("utf-8")
    else:
        raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _origin(base_url: str) -> str:
    parsed = urlsplit(base_url)
    return urlunsplit((parsed.scheme, parsed.netloc, "", "", ""))


def _read_png_size(path: Path) -> tuple[int, int]:
    data = path.read_bytes()
    if data[:8] != b"\x89PNG\r\n\x1a\n" or data[12:16] != b"IHDR" or len(data) < 24:
        raise ValueError(f"vision_image_not_png:{path}")
    width = int.from_bytes(data[16:20], "big")
    height = int.from_bytes(data[20:24], "big")
    if width <= 0 or height <= 0:
        raise ValueError(f"vision_image_dimensions_invalid:{path}")
    return width, height


def _nvidia_sample() -> list[dict[str, Any]]:
    command = [
        "nvidia-smi",
        "--query-gpu=index,name,memory.total,memory.used,utilization.gpu,power.draw",
        "--format=csv,noheader,nounits",
    ]
    try:
        output = subprocess.check_output(command, text=True, stderr=subprocess.STDOUT, timeout=5)
    except (OSError, subprocess.SubprocessError) as exc:
        return [{"error": f"nvidia_smi_unavailable:{exc}"}]
    rows = []
    for line in output.splitlines():
        fields = [item.strip() for item in line.split(",")]
        if len(fields) != 6:
            continue
        try:
            rows.append({
                "index": int(fields[0]), "name": fields[1],
                "memory_total_mib": float(fields[2]), "memory_used_mib": float(fields[3]),
                "utilization_gpu_percent": float(fields[4]), "power_draw_w": float(fields[5]),
            })
        except ValueError:
            rows.append({"raw": line})
    return rows


async def _get_json(client: httpx.AsyncClient, url: str) -> Any:
    response = await client.get(url)
    response.raise_for_status()
    return response.json()


async def _server_preflight(base_url: str, output: Path) -> dict[str, Any]:
    origin = _origin(base_url)
    timeout = httpx.Timeout(10, connect=5)
    async with httpx.AsyncClient(timeout=timeout, trust_env=False) as client:
        health = await _get_json(client, f"{origin}/health")
        props = await _get_json(client, f"{origin}/props")
        slots = await _get_json(client, f"{origin}/slots")
        models = await _get_json(client, f"{base_url.rstrip('/')}/models")
    if isinstance(health, dict) and health.get("status") not in {None, "ok"}:
        raise RuntimeError(f"qwen_health_not_ready:{health}")
    if isinstance(slots, list) and any(item.get("is_processing") for item in slots if isinstance(item, dict)):
        raise RuntimeError("qwen_server_has_active_slots")
    gpu = _nvidia_sample()
    result = {"health": health, "props": props, "slots": slots, "models": models, "gpu": gpu}
    (output / "server_props.json").write_text(json.dumps(props, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (output / "server_slots_before.json").write_text(json.dumps(slots, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result


async def _monitor(base_url: str, stop: asyncio.Event, samples: list[dict[str, Any]]) -> None:
    origin = _origin(base_url)
    async with httpx.AsyncClient(timeout=httpx.Timeout(3, connect=1), trust_env=False) as client:
        while not stop.is_set():
            timestamp = time.time()
            gpu = await asyncio.to_thread(_nvidia_sample)
            try:
                slots = await _get_json(client, f"{origin}/slots")
            except Exception as exc:  # monitoring must never cancel the wave
                slots = {"error": str(exc)}
            samples.append({"timestamp": timestamp, "gpu": gpu, "slots": slots})
            try:
                await asyncio.wait_for(stop.wait(), timeout=.25)
            except asyncio.TimeoutError:
                pass


def _parse_response(stage: str, value: Any, provider: QwenHTTPProvider,
                    request: TaskUnderstandingRequest | None = None) -> Any:
    if stage == "task_understanding":
        parsed = parse_qwen_turn(value, request.instruction if request else "benchmark")
        if request is not None and request.asset_catalog is not None:
            provider._validate_live_asset_choices(value, request)
        return parsed
    if stage == "vision_grounding":
        return VisionGroundingOutput.model_validate(value)
    if stage == "skill_planning":
        return AtomicCommandDraft.model_validate(value)
    raise ValueError(f"unknown_stage:{stage}")


async def _one_request(client: httpx.AsyncClient, base_url: str, model: str,
                       stage_case: StageCase, provider: QwenHTTPProvider,
                       timeout: float, wave: int, concurrency: int,
                       warmup: bool) -> dict[str, Any]:
    request_id = uuid.uuid4().hex
    payload = stage_case.request.payload(model)
    headers = {"X-Request-ID": request_id}
    if provider.api_key:
        headers["Authorization"] = f"Bearer {provider.api_key}"
    started = time.perf_counter()
    first_byte = None
    status = None
    body_bytes = bytearray()
    error = None
    finish_reason = None
    usage = {}
    raw = None
    try:
        async with client.stream(
            "POST", f"{base_url.rstrip('/')}/chat/completions",
            headers=headers, json=payload, timeout=timeout,
        ) as response:
            status = response.status_code
            async for chunk in response.aiter_bytes():
                if first_byte is None:
                    first_byte = time.perf_counter()
                body_bytes.extend(chunk)
            body = json.loads(bytes(body_bytes)) if body_bytes else {}
            if status >= 400:
                raise RuntimeError(f"http_{status}:{json.dumps(body, ensure_ascii=False)[:500]}")
            choice = body["choices"][0]
            finish_reason = choice.get("finish_reason")
            usage = body.get("usage") if isinstance(body.get("usage"), dict) else {}
            raw = choice["message"]["content"]
            if not isinstance(raw, str):
                raise ValueError("response_content_not_text")
            value = _extract_json(raw)
            _parse_response(stage_case.stage, value, provider, stage_case.fixture_meta.get("understanding_request"))
            contract_status = "succeeded"
    except Exception as exc:
        error = str(exc)
        contract_status = "failed"
    ended = time.perf_counter()
    elapsed = ended - started
    result = {
        "request_id": request_id, "stage": stage_case.stage,
        "input_kind": stage_case.input_kind, "wave": wave,
        "concurrency": concurrency, "warmup": warmup,
        "status_code": status, "contract_status": contract_status,
        "error": error, "finish_reason": finish_reason,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "elapsed_seconds": elapsed,
        "http_ttfb_nonstream_seconds": (first_byte - started) if first_byte is not None else None,
        "prompt_tokens": usage.get("prompt_tokens"),
        "completion_tokens": usage.get("completion_tokens"),
        "total_tokens": usage.get("total_tokens"),
        "input_tokens_per_second": ((usage.get("prompt_tokens") / elapsed)
                                     if isinstance(usage.get("prompt_tokens"), int) and elapsed > 0 else None),
        "output_tokens_per_second": ((usage.get("completion_tokens") / elapsed)
                                      if isinstance(usage.get("completion_tokens"), int) and elapsed > 0 else None),
        "payload_sha256": _sha(payload),
        "response_bytes": len(body_bytes),
    }
    return result


async def _run_wave(base_url: str, model: str, stage_case: StageCase,
                    provider: QwenHTTPProvider, concurrency: int, wave: int,
                    warmup: bool, timeout: float, monitor_samples: list[dict[str, Any]]) -> list[dict[str, Any]]:
    limits = httpx.Limits(max_connections=concurrency, max_keepalive_connections=concurrency)
    async with httpx.AsyncClient(limits=limits, trust_env=False) as client:
        started = time.perf_counter()
        tasks = [
            _one_request(client, base_url, model, stage_case, provider, timeout, wave, concurrency, warmup)
            for _ in range(concurrency)
        ]
        results = await asyncio.gather(*tasks)
        wave_elapsed = time.perf_counter() - started
        for result in results:
            result["wave_wall_seconds"] = wave_elapsed
        return results


def _wave_result(stage_case: StageCase, concurrency: int, wave: int,
                 warmup: bool, samples: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate one concurrently-issued wave without dropping failed samples."""
    elapsed = [float(item["elapsed_seconds"]) for item in samples
               if item.get("elapsed_seconds") is not None]
    return {
        "stage": stage_case.stage,
        "input_kind": stage_case.input_kind,
        "concurrency": concurrency,
        "wave": wave,
        "warmup": warmup,
        "requests": len(samples),
        "http_success": sum(item.get("status_code") == 200 for item in samples),
        "contract_success": sum(item.get("contract_status") == "succeeded" for item in samples),
        "timeout_count": sum("timeout" in str(item.get("error", "")).casefold() for item in samples),
        "oom_count": sum(any(word in str(item.get("error", "")).casefold()
                              for word in ("oom", "out of memory")) for item in samples),
        "wave_wall_seconds": max((item.get("wave_wall_seconds", 0) for item in samples), default=None),
        "p50_total_seconds": _percentile(elapsed, 50),
        "p95_total_seconds": _percentile(elapsed, 95),
    }


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(round((percentile / 100) * (len(ordered) - 1)))))
    return ordered[index]


def _fixture_entities(scene: SceneConfig, names: list[str]) -> list[TaskEntity]:
    index = SceneIndex(scene)
    entities = []
    for name in names:
        candidates = []
        for obj in index.semantic_objects():
            semantic = index.semantic(obj.object_id_in_scene)
            if semantic and semantic.semantic_name.casefold() == name.casefold():
                candidates.append(semantic)
        if len(candidates) != 1:
            raise ValueError(f"benchmark_scene_fixture_requires_one:{name}:{len(candidates)}")
        semantic = candidates[0]
        entities.append(TaskEntity(entity_id=name.casefold(), semantic_name=semantic.semantic_name,
                                   category=semantic.category or "object"))
    return entities


def _task_fixture(scene: SceneConfig, instruction: str, multi: bool) -> TaskIntent:
    names = ["Apple", "Basket"] + (["Banana", "Tray"] if multi else [])
    entities = _fixture_entities(scene, names)
    operations = [Operation(
        operation_id="op-1", task_type=TaskType.PICK_AND_PLACE,
        source="apple", destination="basket",
        placement_target=PlacementTarget(kind="container_interior", reference="basket", relation="inside"),
    )]
    if multi:
        operations.append(Operation(
            operation_id="op-2", task_type=TaskType.PICK_AND_PLACE,
            source="banana", destination="tray",
            placement_target=PlacementTarget(kind="container_interior", reference="tray", relation="inside"),
            depends_on=["op-1"],
        ))
    return TaskIntent(instruction=instruction, entities=entities, operations=operations)


def build_cases(config: BrainConfig, provider: QwenHTTPProvider, scene: SceneConfig,
                vision_image: Path | None, app: BrainApplication | None = None) -> tuple[list[StageCase], dict[str, Any]]:
    app = app or BrainApplication(config, provider=provider)
    cases: list[StageCase] = []
    fixture_meta: dict[str, Any] = {"scene_id": scene.scene_id, "scene_version": scene.scene_version}
    instructions = [("simple", "把苹果放进篮子"),
                    ("multi", "用机械臂先把苹果放进篮子，再把香蕉放到托盘右边")]
    for input_kind, instruction in instructions:
        request = TaskUnderstandingRequest(
            instruction=instruction,
            asset_catalog=app.pipeline.asset_catalog,
            workspace=app.pipeline.workspace_context,
            scene_context=app.pipeline._understanding_scene_context(scene),
        )
        stage_request = provider.build_understanding_request(request)
        cases.append(StageCase("task_understanding", input_kind, stage_request,
                               {"understanding_request": request, "instruction": instruction}))

    if vision_image is not None:
        width, height = _read_png_size(vision_image)
        frame = CameraFrame(camera_id="scene_camera", scene_id=scene.scene_id,
                            scene_version=scene.scene_version, scene_sub_version=scene.scene_sub_version,
                            width=width, height=height, rgb=vision_image.read_bytes())
        entities = [VisionEntity(entity_id="apple", semantic_name="Apple")]
        vision_request = VisionGroundingRequest(frame=frame, entities=entities)
        cases.append(StageCase("vision_grounding", "image", provider.build_vision_request(frame, entities),
                               {"vision_request": vision_request, "image": str(vision_image),
                                "image_sha256": _sha(frame.rgb)}))

    for input_kind, instruction in instructions:
        intent = _task_fixture(scene, instruction, input_kind == "multi")
        grounded = app.pipeline.grounder.ground(intent, scene)
        context = build_planner_context(grounded, include_scene_ids=True)
        cases.append(StageCase("skill_planning", input_kind,
                               provider.build_atomic_planning_request(context),
                               {"task_intent": intent, "grounded_task": grounded,
                                "planner_context": context}))
    fixture_meta["case_count"] = len(cases)
    return cases, fixture_meta


def _write_fixture_manifest(output: Path, cases: list[StageCase], meta: dict[str, Any]) -> None:
    rows = []
    for item in cases:
        rows.append({"stage": item.stage, "input_kind": item.input_kind,
                     "payload_sha256": _sha(item.request.payload("fixture-model")),
                     "prompt_sha256": _sha(item.request.prompt),
                     "schema_sha256": _sha(item.request.schema),
                     "response_format": item.request.response_format,
                     "max_completion_tokens": item.request.max_completion_tokens,
                     "fixture": item.fixture_meta.get("image") or item.fixture_meta.get("instruction")})
    (output / "request_fixtures.json").write_text(
        json.dumps({"meta": meta, "cases": rows}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _assert_understanding_fixed_context(cases: list[StageCase]) -> dict[str, Any]:
    """Prove that instruction variants share Brain's fixed system/catalog context."""
    understanding = [item for item in cases if item.stage == "task_understanding"]
    if not understanding:
        return {}
    system_hashes = {_sha(item.request.system_prompt) for item in understanding}
    schema_hashes = {_sha(item.request.schema) for item in understanding}
    fixed_content_hashes = set()
    for item in understanding:
        content = json.loads(item.request.user_content)
        content["instruction"] = "<instruction-variant>"
        fixed_content_hashes.add(_sha(content))
    if len(system_hashes) != 1 or len(schema_hashes) != 1 or len(fixed_content_hashes) != 1:
        raise RuntimeError("understanding_fixed_context_hash_mismatch")
    return {
        "system_prompt_sha256": next(iter(system_hashes)),
        "schema_sha256": next(iter(schema_hashes)),
        "fixed_catalog_workspace_scene_sha256": next(iter(fixed_content_hashes)),
        "instruction_variants": [item.input_kind for item in understanding],
    }


def _summarize(samples: list[dict[str, Any]], gpu_samples: list[dict[str, Any]],
               gpu_mode: str = "unknown") -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str, int], list[dict[str, Any]]] = {}
    for sample in samples:
        if sample.get("warmup"):
            continue
        key = (sample["stage"], sample["input_kind"], sample["concurrency"])
        grouped.setdefault(key, []).append(sample)
    rows = []
    for (stage, input_kind, concurrency), values in sorted(grouped.items()):
        elapsed = [float(v["elapsed_seconds"]) for v in values if v.get("elapsed_seconds") is not None]
        ttfb = [float(v["http_ttfb_nonstream_seconds"]) for v in values if v.get("http_ttfb_nonstream_seconds") is not None]
        prompt = [v["prompt_tokens"] for v in values if isinstance(v.get("prompt_tokens"), int)]
        completion = [v["completion_tokens"] for v in values if isinstance(v.get("completion_tokens"), int)]
        succeeded = sum(v.get("status_code") == 200 for v in values)
        contract_ok = sum(v.get("contract_status") == "succeeded" for v in values)
        wave_wall_by_wave = {
            v.get("wave"): float(v["wave_wall_seconds"])
            for v in values if v.get("wave_wall_seconds") is not None
        }
        wave_wall_total = sum(wave_wall_by_wave.values())
        row = {
            "gpu_mode": gpu_mode, "stage": stage, "input_kind": input_kind, "concurrency": concurrency,
            "requests": len(values), "http_success": succeeded,
            "contract_success": contract_ok,
            "contract_success_rate": contract_ok / len(values) if values else 0,
            "wave_wall_seconds": wave_wall_total or None,
            "requests_per_second": len(values) / wave_wall_total if wave_wall_total > 0 else None,
            "p50_ttfb_seconds": _percentile(ttfb, 50), "p95_ttfb_seconds": _percentile(ttfb, 95),
            "p50_total_seconds": _percentile(elapsed, 50), "p95_total_seconds": _percentile(elapsed, 95),
            "prompt_tokens": sum(prompt) if prompt else None,
            "completion_tokens": sum(completion) if completion else None,
            "input_tokens_per_second": sum(prompt) / wave_wall_total if prompt and wave_wall_total > 0 else None,
            "output_tokens_per_second": sum(completion) / wave_wall_total if completion and wave_wall_total > 0 else None,
            "oom_or_timeout": any(any(word in str(v.get("error", "")).casefold() for word in ("oom", "out of memory", "timeout")) for v in values),
        }
        rows.append(row)
    if gpu_samples:
        peaks = {}
        for sample in gpu_samples:
            for gpu in sample.get("gpu", []):
                if "index" in gpu:
                    current = peaks.setdefault(str(gpu["index"]), {"memory_used_mib": 0, "utilization_gpu_percent": 0})
                    current["memory_used_mib"] = max(current["memory_used_mib"], gpu.get("memory_used_mib", 0))
                    current["utilization_gpu_percent"] = max(current["utilization_gpu_percent"], gpu.get("utilization_gpu_percent", 0))
        for row in rows:
            row["gpu_peaks"] = peaks
    return rows


def _write_outputs(output: Path, samples: list[dict[str, Any]],
                   wave_results: list[dict[str, Any]],
                   gpu_samples: list[dict[str, Any]], rows: list[dict[str, Any]]) -> None:
    with (output / "samples.jsonl").open("w", encoding="utf-8") as handle:
        for item in samples:
            handle.write(json.dumps(item, ensure_ascii=False) + "\n")
    (output / "wave_results.jsonl").write_text(
        "".join(json.dumps(item, ensure_ascii=False) + "\n" for item in wave_results),
        encoding="utf-8",
    )
    (output / "gpu_samples.jsonl").write_text("".join(json.dumps(item, ensure_ascii=False) + "\n" for item in gpu_samples), encoding="utf-8")
    (output / "summary.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    fields = sorted({key for row in rows for key in row})
    with (output / "summary.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    lines = ["# Qwen stage benchmark", "", "`http_ttfb_nonstream` 是非流式 HTTP 首字节，不等同于首 token。", ""]
    if rows:
        columns = ["gpu_mode", "stage", "input_kind", "concurrency", "requests", "http_success",
                   "contract_success", "contract_success_rate",
                   "wave_wall_seconds", "requests_per_second", "p50_ttfb_seconds", "p95_ttfb_seconds",
                   "p50_total_seconds", "p95_total_seconds", "prompt_tokens", "completion_tokens",
                   "input_tokens_per_second", "output_tokens_per_second", "oom_or_timeout"]
        lines.append("| " + " | ".join(columns) + " |")
        lines.append("|" + "|".join("---" for _ in columns) + "|")
        for row in rows:
            lines.append("| " + " | ".join(str(row.get(key, "")) for key in columns) + " |")
    (output / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


async def run(args: argparse.Namespace) -> Path:
    output = Path(args.output_dir).resolve() / (datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:8])
    output.mkdir(parents=True, exist_ok=False)
    config_path = Path(args.config).resolve()
    config = BrainConfig.load(config_path, overrides={"base_url": args.base_url, "model": args.model,
                                                       "output_dir": str(output)})
    provider = QwenHTTPProvider(
        args.base_url, args.model, api_key=args.api_key or "", timeout=args.timeout,
        structured_output=config.structured_output,
        planner_max_completion_tokens=config.planner_max_completion_tokens,
        skill_planning_response_format=config.skill_planning_response_format,
        atomic_skill_prompt_path=config.control_skill_prompt_path(),
    )
    preflight = await _server_preflight(args.base_url, output)
    scene_path = Path(args.scene).resolve()
    # The benchmark sends a real CameraFrame to Qwen but does not render a
    # scene locally.  Disable only BrainApplication's renderer requirement;
    # all asset/workspace/scene context and provider payload construction stay
    # on the production config and contracts.
    app = BrainApplication(config.model_copy(update={"vision": False}), provider=provider)
    scene = app.codec.load(scene_path)
    image = Path(args.vision_image).resolve() if args.vision_image else None
    if image is not None and not image.is_file():
        raise FileNotFoundError(image)
    cases, fixture_meta = build_cases(config, provider, scene, image, app=app)
    selected = set(item.strip() for item in args.stages.split(",") if item.strip())
    cases = [case for case in cases if (case.stage == "task_understanding" and "understanding" in selected)
             or (case.stage == "vision_grounding" and "vision" in selected)
             or (case.stage == "skill_planning" and "atomic" in selected)]
    if "vision" in selected and image is None:
        fixture_meta["vision"] = "skipped_missing_vision_fixture"
    fixture_meta["understanding_fixed_context"] = _assert_understanding_fixed_context(cases)
    _write_fixture_manifest(output, cases, fixture_meta)
    (output / "environment.json").write_text(json.dumps({
        "created_at": datetime.now(timezone.utc).isoformat(), "base_url": args.base_url,
        "model": args.model, "gpu_mode": args.gpu_mode, "concurrency": args.concurrency,
        "warmup": args.warmup, "repeats": args.repeats, "config": config.model_dump(mode="json"),
        "git_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "preflight": preflight,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    samples: list[dict[str, Any]] = []
    wave_results: list[dict[str, Any]] = []
    gpu_samples: list[dict[str, Any]] = []
    for case in cases:
        monitor_samples: list[dict[str, Any]] = []
        stop = asyncio.Event()
        monitor_task = asyncio.create_task(_monitor(args.base_url, stop, monitor_samples))
        try:
            for concurrency in args.concurrency:
                if args.warmup:
                    wave_samples = await _run_wave(
                        args.base_url, args.model, case, provider, concurrency, 0, True,
                        args.timeout, monitor_samples,
                    )
                    samples.extend(wave_samples)
                    wave_results.append(_wave_result(case, concurrency, 0, True, wave_samples))
                for wave in range(1, args.repeats + 1):
                    wave_samples = await _run_wave(
                        args.base_url, args.model, case, provider, concurrency, wave, False,
                        args.timeout, monitor_samples,
                    )
                    samples.extend(wave_samples)
                    wave_results.append(_wave_result(case, concurrency, wave, False, wave_samples))
        finally:
            stop.set()
            await monitor_task
        gpu_samples.extend(monitor_samples)
    rows = _summarize(samples, gpu_samples, args.gpu_mode)
    _write_outputs(output, samples, wave_results, gpu_samples, rows)
    origin = _origin(args.base_url)
    async with httpx.AsyncClient(timeout=httpx.Timeout(10, connect=5), trust_env=False) as client:
        try:
            slots = await _get_json(client, f"{origin}/slots")
            (output / "server_slots_after.json").write_text(json.dumps(slots, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        except Exception as exc:
            (output / "server_slots_after.json").write_text(json.dumps({"error": str(exc)}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(output)
    return output


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description=__doc__)
    value.add_argument("--base-url", default="http://127.0.0.1:8080/v1")
    value.add_argument("--model", required=True)
    value.add_argument("--api-key", default=os.environ.get("ROBOT_BRAIN_API_KEY", ""))
    value.add_argument("--config", default=str(DEFAULT_CONFIG),
                       help="Brain config; defaults to the current ObjectLibraryServer-backed config")
    value.add_argument("--scene", default=str(DEFAULT_SCENE),
                       help="formal scene fixture; defaults to OLS scene 3")
    value.add_argument("--vision-image")
    value.add_argument("--stages", default="understanding,vision,atomic")
    value.add_argument("--concurrency", default=",".join(map(str, DEFAULT_CONCURRENCY)),
                       help="comma-separated concurrency levels")
    value.add_argument("--warmup", type=int, default=1)
    value.add_argument("--repeats", type=int, default=3)
    value.add_argument("--timeout", type=float, default=600)
    value.add_argument("--gpu-mode", choices=("single", "dual", "unknown"), default="unknown")
    value.add_argument("--output-dir", default="var/qwen-benchmark")
    return value


def main() -> None:
    args = parser().parse_args()
    args.concurrency = tuple(int(item) for item in str(args.concurrency).split(",") if item.strip())
    if not args.concurrency or any(item < 1 for item in args.concurrency):
        raise SystemExit("--concurrency must contain positive integers")
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
