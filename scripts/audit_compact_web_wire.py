"""Verify saved raw responses, retries, original hashes and schema for C5."""
import hashlib
import json
import sys
from copy import deepcopy
from pathlib import Path

from robot_agent_brain.models.understanding_wire import compact_schema, decode


root = Path(sys.argv[1])
runtime = root.parent
audit = json.loads((root / "audit.json").read_text())
schema = compact_schema()
(root / "wire_schema.json").write_text(json.dumps(schema, ensure_ascii=False, indent=2))
schema_hash = hashlib.sha256(json.dumps(schema, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
schema_order_hash = hashlib.sha256(json.dumps(schema, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()
for row in audit["rows"]:
    directory = Path(row["evidence"])
    result = json.loads((directory / "task_result.json").read_text())
    task = runtime / "tasks" / row["session_id"] / result["request_id"]
    raw = json.loads((task / "debug/raw_model_response.txt").read_text())
    wire = json.loads(raw["task_understanding"])
    expanded = decode(wire)
    (directory / "raw_qwen.json").write_text(json.dumps(wire, ensure_ascii=False, indent=2))
    (directory / "expanded_wire.json").write_text(json.dumps(expanded, ensure_ascii=False, indent=2))
    ops = wire["se"]["o"]
    checks = row["checks"]
    checks["wire_ops"] = (len(ops) == 2 and all(o["op"] == "add" and "ax" not in o and "ad" not in o for o in ops)
                         if row["turn"] == 1 else len(ops) == 1 and ops[0]["op"] == "rotate" and ops[0]["ax"] == "z" and ops[0]["ad"] == 90)
    calls = result["metrics"]["model_call_details"]
    checks["one_u_no_retry"] = len(calls) == 1 and calls[0]["stage"] == "task_understanding"
    checks["matching_schema"] = calls[0]["schema_sha256"] == schema_hash
    if row["turn"] == 2:
        before = json.loads((directory / "scene_before.json").read_text())
        after = json.loads((directory / "scene_after.json").read_text())
        def component(obj, kind):
            return next(c["properties"] for c in obj["components"] if c["component_type"] == kind)
        apples = [o for o in before["objects"] if any(c["component_type"] == "MetadataRef" and
                  c["properties"] == {"path": "$LIBRARY_SERVER/1", "type": "model"} for c in o["components"])]
        selected = min(apples, key=lambda o: component(o, "Transform")["position"][0])
        actual = next(o for o in after["objects"] if o["object_id_in_scene"] == selected["object_id_in_scene"])
        expected = deepcopy(selected)
        component(expected, "Transform")["quaternion_xyzw"] = component(actual, "Transform")["quaternion_xyzw"]
        checks["only_rotation_changed_on_target"] = expected == actual
    original = runtime / "tasks" / row["session_id"] / "original_scene.json"
    row["original_sha256"] = hashlib.sha256(original.read_bytes()).hexdigest()
    row["source_debug"] = str(task / "debug")
    row["commit_receipts"] = result.get("commitReceipts")
    checks["one_commit"] = len(result.get("commitReceipts", [])) == 1
    row["passed"] = all(checks.values())
audit.update(passed=sum(row["passed"] for row in audit["rows"]), schema_sha256=schema_hash, schema_order_sha256=schema_order_hash)
(root / "audit-wire.json").write_text(json.dumps(audit, ensure_ascii=False, indent=2))
print(json.dumps({"total": len(audit["rows"]), "passed": audit["passed"],
                  "failures": [r for r in audit["rows"] if not r["passed"]]}, ensure_ascii=False))
