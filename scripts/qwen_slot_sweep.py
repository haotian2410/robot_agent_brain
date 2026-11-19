#!/usr/bin/env python3
"""Run the fixed-catalog Qwen slot sweep after a baseline benchmark finishes."""
from __future__ import annotations

import argparse
import csv
import json
import os
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SERVER = Path("/home/cscvlab/llama.cpp/build/bin/llama-server")
DEFAULT_MODEL = Path("/home/cscvlab/models/qwen3.8-27b/Qwen3.8-27B-UD-Q4_K_M.gguf")
DEFAULT_MMPROJ = Path("/home/cscvlab/models/qwen3.8-27b/mmproj-BF16.gguf")
DEFAULT_IMAGE = next(iter(sorted((ROOT / "var").rglob("screenshot.png"))), None)


def _alive(pid: int) -> bool:
    try:
        if Path(f"/proc/{pid}/stat").read_text(encoding="utf-8").split()[2] == "Z":
            return False
    except (FileNotFoundError, PermissionError, IndexError):
        pass
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _wait_exit(pid: int, timeout: float) -> None:
    deadline = time.monotonic() + timeout
    while _alive(pid) and time.monotonic() < deadline:
        time.sleep(.5)
    if _alive(pid):
        os.kill(pid, signal.SIGKILL)
        time.sleep(1)


def _wait_server(base_url: str, expected_slots: int, timeout: float) -> dict:
    deadline = time.monotonic() + timeout
    origin = base_url.rstrip("/").rsplit("/v1", 1)[0]
    with httpx.Client(timeout=httpx.Timeout(5, connect=2), trust_env=False) as client:
        last = None
        while time.monotonic() < deadline:
            try:
                health = client.get(f"{origin}/health").json()
                props = client.get(f"{origin}/props").json()
                slots = client.get(f"{origin}/slots").json()
                last = {"health": health, "props": props, "slots": slots}
                if props.get("total_slots") == expected_slots and not any(
                        item.get("is_processing") for item in slots if isinstance(item, dict)):
                    return last
            except Exception as exc:
                last = {"error": str(exc)}
            time.sleep(1)
    raise RuntimeError(f"server_preflight_failed: expected_slots={expected_slots} last={last}")


def _start_server(args: argparse.Namespace, slot: int, log_path: Path, ctx_size: int) -> subprocess.Popen:
    command = [
        str(args.server), "--model", str(args.model), "--mmproj", str(args.mmproj),
        "--host", args.host, "--port", str(args.port), "--ctx-size", str(ctx_size),
        "--n-gpu-layers", str(args.n_gpu_layers), "--image-min-tokens", str(args.image_min_tokens),
        "--reasoning", "off", "--parallel", str(slot),
    ]
    log = log_path.open("w", encoding="utf-8")
    process = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT, cwd=ROOT)
    process._slot_sweep_log = log  # type: ignore[attr-defined]
    return process


def _latest_run(root: Path) -> Path:
    runs = sorted(item for item in root.iterdir() if item.is_dir())
    if not runs:
        raise RuntimeError(f"benchmark_output_missing:{root}")
    return runs[-1]


def _write_sweep_summary(output: Path, rows: list[dict]) -> None:
    (output / "slot_summary.json").write_text(
        json.dumps(rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    fields = sorted({key for row in rows for key in row})
    with (output / "slot_summary.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    columns = ["slots", "ctx_size", "test_mode", "status", "stage", "input_kind", "concurrency", "requests",
               "http_success", "contract_success", "contract_success_rate",
               "p95_ttfb_seconds", "p95_total_seconds", "requests_per_second",
               "input_tokens_per_second", "output_tokens_per_second", "oom_or_timeout"]
    lines = ["# Qwen fixed system/catalog slot sweep", "",
             "Only task_understanding is measured; system prompt, OLS catalog, workspace and scene are fixed.", "",
             "| " + " | ".join(columns) + " |", "|" + "|".join("---" for _ in columns) + "|"]
    for row in rows:
        lines.append("| " + " | ".join(str(row.get(key, "")) for key in columns) + " |")
    (output / "slot_summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--baseline-pid", type=int, default=3468867)
    p.add_argument("--base-url", default="http://127.0.0.1:8080/v1")
    p.add_argument("--server", type=Path, default=DEFAULT_SERVER)
    p.add_argument("--model", type=Path, default=DEFAULT_MODEL)
    p.add_argument("--mmproj", type=Path, default=DEFAULT_MMPROJ)
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8080)
    p.add_argument("--ctx-size", type=int, default=32768)
    p.add_argument("--per-slot-ctx", type=int, default=32768,
                   help="context reserved per slot; total --ctx-size is slots * this value")
    p.add_argument("--n-gpu-layers", type=int, default=999)
    p.add_argument("--image-min-tokens", type=int, default=1024)
    p.add_argument("--slots", default="4,8,16,32")
    p.add_argument("--concurrency", default="1,3,5,10,20,30,50,70,100")
    p.add_argument("--warmup", type=int, default=1)
    p.add_argument("--repeats", type=int, default=3)
    p.add_argument("--timeout", type=float, default=600)
    p.add_argument("--vision-image", type=Path, default=DEFAULT_IMAGE)
    p.add_argument("--output-dir", type=Path, default=ROOT / "var" / "qwen-benchmark-slot-sweep")
    p.add_argument("--server-wait-timeout", type=float, default=180)
    p.add_argument("--smoke-concurrency", default="1,3,5")
    p.add_argument("--smoke-repeats", type=int, default=1)
    return p


def main() -> None:
    args = parser().parse_args()
    args.slots = tuple(int(item) for item in args.slots.split(",") if item.strip())
    args.concurrency = ",".join(item.strip() for item in args.concurrency.split(",") if item.strip())
    args.smoke_concurrency = ",".join(item.strip() for item in args.smoke_concurrency.split(",") if item.strip())
    if not args.vision_image or not args.vision_image.is_file():
        raise SystemExit("--vision-image must point to a real PNG fixture")
    output = args.output_dir.resolve() / datetime.now().strftime("%Y%m%d-%H%M%S")
    output.mkdir(parents=True, exist_ok=False)
    while _alive(args.baseline_pid):
        print(f"waiting for baseline pid {args.baseline_pid} to finish", flush=True)
        time.sleep(10)
    rows: list[dict] = []
    current_server_pid = None
    smoke_passed = False
    for index, slot in enumerate(args.slots):
        ctx_size = slot * args.per_slot_ctx
        if current_server_pid is None:
            current_server_pid = next((int(value) for value in os.popen("pgrep -f 'llama-server.*--port " + str(args.port) + "'" ).read().split()), None)
        if current_server_pid and _alive(current_server_pid):
            os.kill(current_server_pid, signal.SIGTERM)
            _wait_exit(current_server_pid, 30)
        slot_dir = output / f"slot-{slot}"
        slot_dir.mkdir()
        server = _start_server(args, slot, slot_dir / "llama-server.log", ctx_size)
        current_server_pid = server.pid
        try:
            try:
                preflight = _wait_server(args.base_url, slot, args.server_wait_timeout)
            except Exception as exc:
                log_text = (slot_dir / "llama-server.log").read_text(encoding="utf-8", errors="replace")
                status = "confirmed_oom" if any(word in log_text.casefold() for word in
                    ("out of memory", "cuda out of memory", "failed to allocate", "kv cache")) else "server_preflight_failed"
                rows.append({"slots": slot, "ctx_size": ctx_size, "status": status,
                             "error": str(exc), "requests": 0, "http_success": 0,
                             "contract_success": 0})
                if status == "confirmed_oom":
                    print(f"confirmed OOM at slots={slot}; stopping higher slot tiers", file=sys.stderr)
                    break
                raise
            (slot_dir / "server_preflight.json").write_text(
                json.dumps(preflight, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            command = [str(args.server), "--model", str(args.model), "--mmproj", str(args.mmproj),
                       "--host", args.host, "--port", str(args.port), "--ctx-size", str(ctx_size),
                       "--n-gpu-layers", str(args.n_gpu_layers), "--image-min-tokens", str(args.image_min_tokens),
                       "--reasoning", "off", "--parallel", str(slot)]
            (slot_dir / "server_command.json").write_text(json.dumps(command, indent=2) + "\n", encoding="utf-8")
            smoke = index == 0
            bench_concurrency = args.smoke_concurrency if smoke else args.concurrency
            bench_repeats = str(args.smoke_repeats if smoke else args.repeats)
            command = [sys.executable, str(ROOT / "scripts" / "qwen_stage_benchmark.py"),
                       "--base-url", args.base_url, "--model", "Qwen3.8-27B",
                       "--config", str(ROOT / "config" / "webeditor.json"),
                       "--scene", str(ROOT.parent / "ObjectLibraryServer" / "data" / "scenes" / "3" / "ur5_table_sorting.json"),
                       "--stages", "understanding", "--vision-image", str(args.vision_image),
                       "--concurrency", bench_concurrency, "--warmup", str(args.warmup),
                       "--repeats", bench_repeats, "--timeout", str(args.timeout),
                       "--gpu-mode", "dual", "--output-dir", str(slot_dir / "benchmark")]
            result = subprocess.run(command, cwd=ROOT, check=False)
            run = _latest_run(slot_dir / "benchmark")
            for row in json.loads((run / "summary.json").read_text(encoding="utf-8")):
                rows.append({"slots": slot, "ctx_size": ctx_size,
                             "test_mode": "smoke" if smoke else "full", **row})
            (slot_dir / "benchmark_run.txt").write_text(str(run) + "\n", encoding="utf-8")
            if result.returncode != 0:
                raise RuntimeError(f"benchmark_failed: slot={slot} returncode={result.returncode}")
            errors = "\n".join(
                item.get("error", "") or "" for item in
                (json.loads(line) for line in (run / "samples.jsonl").read_text().splitlines())
            ).casefold()
            if any(word in errors for word in ("oom", "out of memory", "cuda out of memory")):
                print(f"confirmed OOM at slots={slot}; stopping higher slot tiers", file=sys.stderr)
                break
            if smoke:
                smoke_passed = all(row.get("http_success", 0) == row.get("requests", -1)
                                   and row.get("contract_success", 0) == row.get("requests", -1)
                                   for row in rows if row.get("slots") == slot and row.get("test_mode") == "smoke")
                if not smoke_passed:
                    print("4-slot smoke failed; stopping before higher slot tiers", file=sys.stderr)
                    break
        finally:
            if _alive(server.pid):
                os.kill(server.pid, signal.SIGTERM)
                _wait_exit(server.pid, 30)
            getattr(server, "_slot_sweep_log", None) and server._slot_sweep_log.close()  # type: ignore[attr-defined]
    _write_sweep_summary(output, rows)
    (output / "environment.json").write_text(json.dumps({
        "created_at": datetime.now(timezone.utc).isoformat(),
        "slots": args.slots, "concurrency": args.concurrency,
        "per_slot_ctx": args.per_slot_ctx,
        "baseline_pid": args.baseline_pid, "vision_image": str(args.vision_image),
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(output)


if __name__ == "__main__":
    main()
