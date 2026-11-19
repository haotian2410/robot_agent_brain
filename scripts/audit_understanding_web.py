"""Check recorded real browser Scenes independently of Brain result text."""
import json
import sys
import math
from pathlib import Path

root = Path(sys.argv[1])
rows = json.loads((root / "results.json").read_text())

def components(obj):
    return {c["component_type"]: c["properties"] for c in obj["components"]}

def instances(scene, asset):
    return [o for o in scene["objects"] if components(o).get("MetadataRef") ==
            {"path": f"$LIBRARY_SERVER/{asset}", "type": "model"}]

for row in rows:
    case = row["case"].removesuffix("-CLEAR")
    directory = root / row["evidence"]
    before = json.loads((directory / "scene_before.json").read_text())
    after = json.loads((directory / "scene_after.json").read_text())
    result = json.loads((directory / "task_result.json").read_text())
    checks = {"no_execution": result.get("executed") is False,
              "screenshot": row["screenshot"]["status"] == "captured"}
    expected = {"P01": "answered", "P02": "scene_updated", "P04": "plan_ready"}.get(row["case"])
    if row["case"] == "U-MULTI":
        expected = "answered" if row["turn"] == 3 else "scene_updated"
    if case in {"U-MOVE", "U-FUZZY", "U-ROTATE", "U-REPLACE", "U-SCALE", "U-ORIGINAL"}:
        expected = "scene_updated"
    if row["case"] == "U-REJECT":
        expected = "answered" if row["turn"] == 2 else "failed"
    if expected:
        checks["expected_outcome"] = result.get("outcome") == expected
    changed = row["scene_before_digest"] != row["scene_after_digest"]
    if result["outcome"] == "scene_updated":
        checks["one_version"] = (after["scene_version"] == before["scene_version"] + 1
                                 if before["scene_id"] == after["scene_id"] else after["scene_version"] == 1)
        checks["changed"] = changed
    else:
        checks["unchanged"] = not changed
    if row["case"] == "U-MULTI":
        checks["two_apples_one_tray"] = len(instances(after, 1)) == 2 and len(instances(after, 17)) == 1
        if row["turn"] == 1:
            before_ids = {o["object_id_in_scene"]: o for o in before["objects"]}
            after_ids = {o["object_id_in_scene"]: o for o in after["objects"]}
            checks["exactly_three_new"] = len(after_ids.keys() - before_ids.keys()) == 3
            checks["non_targets_unchanged"] = all(after_ids[k] == v for k, v in before_ids.items())
        if row["turn"] == 2:
            target = min(instances(before, 1), key=lambda o: components(o)["Transform"]["position"][0])["object_id_in_scene"]
            before_ids = {o["object_id_in_scene"]: o for o in before["objects"]}
            after_ids = {o["object_id_in_scene"]: o for o in after["objects"]}
            checks["leftmost_blue"] = components(after_ids[target]).get("MeshRenderer", {}).get("forceOverrideColor") == "#0000FF"
            checks["non_targets_unchanged"] = all(after_ids[k] == v for k, v in before_ids.items() if k != target)
    if row["case"] == "P04" or (row["case"] == "P06" and row["turn"] == 2):
        checks["plan_ready"] = result["outcome"] == "plan_ready"
        checks["commands"] = any(a.get("name") == "commands" for a in result.get("artifacts", []))
    if row["case"] == "P06" and row["turn"] == 1:
        checks["clarification"] = result["outcome"] == "clarification_required"
    if case in {"U-MOVE", "U-FUZZY", "U-ROTATE"} and (not row["case"].endswith("-CLEAR") or row["turn"] == 2):
        a, b = instances(before, 1)[0], instances(after, 1)[0]
        ta, tb = components(a)["Transform"], components(b)["Transform"]
        checks["same_target"] = a["object_id_in_scene"] == b["object_id_in_scene"]
        old, new = ({o["object_id_in_scene"]: o for o in scene["objects"]} for scene in (before, after))
        checks["non_targets_unchanged"] = old.keys() == new.keys() and all(v == new[k] for k,v in old.items() if k != a["object_id_in_scene"])
        if case == "U-ROTATE":
            x,y,z,w = ta["quaternion_xyzw"]
            s = math.sqrt(.5)
            expected_q = [s*(x-y), s*(x+y), s*(z+w), s*(w-z)]
            checks["rotation_90"] = min(max(abs(x-sign*y) for x,y in zip(tb["quaternion_xyzw"],expected_q)) for sign in (1,-1)) < 1e-6
            checks["position_preserved"] = ta["position"] == tb["position"]
        else:
            dx = tb["position"][0] - ta["position"][0]
            checks["move_distance"] = abs(dx - .005) < 1e-6 if case == "U-MOVE" else 0 < dx < .1
            checks["other_axes_preserved"] = ta["position"][1:] == tb["position"][1:]
    if case == "U-REPLACE" and (not row["case"].endswith("-CLEAR") or row["turn"] == 2):
        checks["apple_removed"] = not instances(after, 1)
        checks["one_baseball_added"] = len(instances(after, 3)) == len(instances(before, 3)) + 1
    if row["case"] == "U-SCALE" and row["turn"] == 2:
        baskets = [instances(s, 4) + instances(s, 12) for s in (before, after)]
        assert all(len(items) == 1 for items in baskets), "expected_unique_OLS_basket"
        a, b = (components(items[0])["Transform"]["scale"] for items in baskets)
        checks["scale_1_1"] = all(abs(y - x * 1.1) < 1e-6 for x,y in zip(a,b))
    if row["case"] == "U-ORIGINAL" and row["turn"] == 2:
        checks["new_scene"] = before["scene_id"] != after["scene_id"]
        checks["no_current_apple"] = not instances(after, 1)
        checks["banana_added"] = len(instances(after, 2)) == 1
    row["checks"] = checks
    row["passed"] = all(checks.values())
report = {"total": len(rows), "passed": sum(r["passed"] for r in rows), "rows": rows}
(root / "audit.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
print(json.dumps({"total": report["total"], "passed": report["passed"],
                  "failed_checks": [{"case": r["case"], "turn": r["turn"], "checks": r["checks"]}
                                    for r in rows if not r["passed"]]}, ensure_ascii=False))
