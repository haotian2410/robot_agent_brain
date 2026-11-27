"""Regenerate public layout/DAG schemas from the canonical Python models.

Run from the repository environment; --check is a read-only drift gate.
Semantic validators (graph cycles, references, physical layout) still run in
Python and are not falsely represented as JSON Schema guarantees.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from robot_agent_brain.contracts.arrangement import ArrangementSpec, LayoutPlan, LayoutResolution
from robot_agent_brain.contracts.commands_dag_v4 import CommandsFileV4


MODELS = {
    "arrangement_spec.schema.json": ArrangementSpec,
    "layout_plan.schema.json": LayoutPlan,
    "layout_resolution.schema.json": LayoutResolution,
    "commands_dag_v4.schema.json": CommandsFileV4,
    "commands_sequence_v41.schema.json": CommandsFileV4,
}


def schema_documents():
    return {name: {"$schema": "https://json-schema.org/draft/2020-12/schema",
                   "$id": name, **model.model_json_schema()}
            for name, model in MODELS.items()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--output", type=Path,
                        default=Path(__file__).resolve().parents[1] / "schemas")
    args = parser.parse_args()
    mismatches = []
    for name, document in schema_documents().items():
        path = args.output / name
        encoded = json.dumps(document, ensure_ascii=False, indent=2) + "\n"
        if args.check:
            if not path.exists() or path.read_text(encoding="utf-8") != encoded:
                mismatches.append(name)
        else:
            args.output.mkdir(parents=True, exist_ok=True)
            path.write_text(encoded, encoding="utf-8")
    if mismatches:
        parser.exit(1, "schema drift: " + ", ".join(mismatches) + "\n")


if __name__ == "__main__":
    main()
