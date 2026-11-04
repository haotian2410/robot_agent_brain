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


def _validate_plan_schema(plan: dict, schema_path: Path) -> None:
    """Validate the checked-in machine-readable plan, not only its counts.

    The workbook and the exported plan are two independently consumed
    artifacts.  A count match cannot detect a wrong schema discriminator,
    malformed ``first_five`` list, or an invalid status value.  Keep this
    validator in the offline tool so C0 can be run without starting any
    service; ``jsonschema`` is already an optional development dependency of
    the integration environment.
    """
    try:
        from jsonschema import Draft202012Validator
    except ModuleNotFoundError as exc:  # pragma: no cover - environment error
        raise SystemExit("semantic_test_plan_schema_dependency_missing:jsonschema") from exc
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    errors = sorted(Draft202012Validator(schema).iter_errors(plan),
                    key=lambda error: list(error.path))
    if errors:
        first = errors[0]
        path = ".".join(str(part) for part in first.path) or "$"
        raise SystemExit(f"semantic_test_plan_schema_invalid:{path}:{first.message}")


def main() -> int:
    workbook = Path(__file__).with_name("02_semantic_test_matrix.xlsx")
    plan = Path(__file__).with_name("03_semantic_test_plan.json")
    schema_path = Path(__file__).with_name("04_test_plan.schema.json")
    spec = read_semantic_matrix_v2(workbook, strict_counts=True)
    data = json.loads(plan.read_text(encoding="utf-8"))
    _validate_plan_schema(data, schema_path)
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
