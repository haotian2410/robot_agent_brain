#!/usr/bin/env python3
"""Render existing Qwen benchmark CSV reports with Chinese column names."""
from __future__ import annotations

import argparse
import csv
from pathlib import Path

MAP = {
    "slots": "Slots槽位数", "ctx_size": "总Context长度(token)", "test_mode": "测试模式",
    "status": "状态", "stage": "阶段", "input_kind": "输入类型", "concurrency": "并发请求数",
    "requests": "正式请求数", "http_success": "HTTP成功数", "contract_success": "Contract成功数",
    "contract_success_rate": "Contract成功率", "wave_wall_seconds": "本并发档运行时间(秒)",
    "requests_per_second": "请求吞吐(请求/秒)", "p50_ttfb_seconds": "首字节时间P50(秒)",
    "p95_ttfb_seconds": "首字节时间P95(秒)", "p50_total_seconds": "总耗时P50(秒)",
    "p95_total_seconds": "总耗时P95(秒)", "prompt_tokens": "输入Token总数",
    "completion_tokens": "输出Token总数", "input_tokens_per_second": "输入Token速率(Token/秒)",
    "output_tokens_per_second": "输出Token速率(Token/秒)", "gpu_mode": "GPU模式",
    "gpu_peaks": "GPU峰值显存与利用率", "oom_or_timeout": "OOM或超时",
    "error": "错误信息",
}


def render_csv(src: Path, dst: Path) -> list[dict[str, str]]:
    with src.open(encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    keys = list(rows[0]) if rows else []
    with dst.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=[MAP.get(k, k) for k in keys])
        writer.writeheader()
        for row in rows:
            writer.writerow({MAP.get(k, k): v for k, v in row.items()})
    return rows


def render_md(rows: list[dict[str, str]], dst: Path) -> None:
    if not rows:
        return
    keys = list(rows[0])
    preferred = ["slots", "ctx_size", "test_mode", "input_kind", "concurrency", "requests",
                 "http_success", "contract_success", "contract_success_rate",
                 "wave_wall_seconds", "requests_per_second", "p50_ttfb_seconds",
                 "p95_ttfb_seconds", "p50_total_seconds", "p95_total_seconds",
                 "prompt_tokens", "completion_tokens", "input_tokens_per_second",
                 "output_tokens_per_second", "gpu_peaks", "oom_or_timeout", "status"]
    keys = [k for k in preferred if k in keys] + [k for k in keys if k not in preferred]
    lines = ["# Qwen Slots 基准中文报告", "", "说明：首字节时间是非流式 HTTP TTFB，不等同于真正的首 Token 时间。", "",
             "| " + " | ".join(MAP.get(k, k) for k in keys) + " |",
             "|" + "|".join("---" for _ in keys) + "|"]
    for row in rows:
        lines.append("| " + " | ".join(str(row.get(k, "")) for k in keys) + " |")
    dst.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("root", type=Path, help="corrected sweep run directory")
    args = p.parse_args()
    root = args.root.resolve()
    slot_csv = root / "slot_summary.csv"
    if slot_csv.exists():
        rows = render_csv(slot_csv, root / "slot_summary_cn.csv")
        render_md(rows, root / "slot_summary_cn.md")
    for src in root.glob("slot-*/benchmark/*/summary.csv"):
        rows = render_csv(src, src.with_name("summary_cn.csv"))
        render_md(rows, src.with_name("summary_cn.md"))
    print(root)


if __name__ == "__main__":
    main()
