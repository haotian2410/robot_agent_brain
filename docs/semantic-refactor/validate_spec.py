#!/usr/bin/env python3
"""Offline validator for the supplied semantic matrix package.

It validates the workbook shape/counts and the machine-readable plan without
starting Qwen, OLS, Brain, Gateway, or a browser.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from robot_agent_brain.batch_matrix_v2 import read_semantic_matrix_v2  # noqa: E402


def main() -> int:
    workbook = Path(__file__).with_name("02_semantic_test_matrix.xlsx")
    plan = Path(__file__).with_name("03_semantic_test_plan.json")
    spec = read_semantic_matrix_v2(workbook, strict_counts=True)
    data = json.loads(plan.read_text(encoding="utf-8"))
    expected = data["counts"]
    actual = {
        "feature_rows": spec["counts"]["cases"],
        "expressions": spec["counts"]["variants"],
        "regression_invariants": spec["invariant_count"],
    }
    if actual != expected:
        raise SystemExit(f"semantic_test_plan_count_mismatch:{actual}!={expected}")
    print(json.dumps({"status": "valid", "workbook": str(workbook), "counts": actual,
                      "first_five": [str(row["case_id"]) for row in spec["cases"][:5]]},
                     ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
