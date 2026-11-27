"""Read-only live custom-layout protocol smoke; never publishes or executes."""
import argparse
import json
from pathlib import Path
from datetime import datetime, timezone

import httpx
from robot_agent_brain.models.qwen_http import QwenHTTPProvider
from robot_agent_brain.models.layout_planning import LayoutPlanningRequest
from robot_agent_brain.contracts.arrangement import ArrangementSpec
from robot_agent_brain.planning.layout_planner import plan_arrangement


def shape_matches(number, points):
    """Independent orientation oracle for these three named smoke cases only."""
    if number == 1:
        return len(points) == 2 and points[0][0] < points[1][0] and abs(points[0][1] - points[1][1]) < 1e-6
    if number == 2:
        return (len(points) == 3 and points[0][0] < points[1][0] < points[2][0]
                and points[1][1] < min(points[0][1], points[2][1]))
    return (len(points) == 4 and points[0][0] < points[1][0] and points[2][0] < points[3][0]
            and abs(points[0][1] - points[1][1]) < 1e-6
            and abs(points[2][1] - points[3][1]) < 1e-6 and points[0][1] > points[2][1])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8080/v1")
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=False)
    results = []
    requests = []
    def capture(request):
        if request.method == "POST":
            requests.append(json.loads(request.content))
    with httpx.Client(timeout=120, event_hooks={"request": [capture]}) as client:
        response = client.get(args.base_url.rstrip("/") + "/models")
        response.raise_for_status()
        model = response.json()["data"][0]["id"]
        provider = QwenHTTPProvider(args.base_url, model, client=client, live_catalog=True)
        for number, description in enumerate([
            "一条从左到右的水平直线", "三个顶点组成的V形开放折线", "四个顶点组成的Z形开放折线"
        ], 1):
            directory = args.output_dir / f"case-{number:02d}"
            directory.mkdir()
            request = LayoutPlanningRequest(description=description, requested_count=6)
            result = {"case": number, "description": description, "model": model,
                      "control_called": False, "scene_published": False}
            start = len(provider.calls)
            wire_start = len(requests)
            try:
                draft = provider.plan_layout(request)
                spec = ArrangementSpec(arrangement_id=f"arr-live-{number}",
                    pattern={"kind": "custom", "description": description, "path": draft.points()},
                    items={"assets": [{"alias": "apple"}], "requested_count": 6},
                    region={"surface_ref": "table"}, spacing={"mode": "auto", "auto": True})
                plan = plan_arrangement(spec)
                result.update(status="protocol_pass", draft=draft.model_dump(mode="json"),
                              plan=plan.model_dump(mode="json"))
                result["shape_orientation_pass"] = shape_matches(number, draft.points())
                if not result["shape_orientation_pass"]:
                    result.update(status="failed", error_code="layout_smoke_shape_orientation_mismatch")
            except Exception as error:
                result.update(status="failed", error_type=type(error).__name__,
                              error_code=getattr(error, "code", None), error=str(error))
            result.update(calls=provider.calls[start:], wire_requests=requests[wire_start:],
                          raw_values=provider.last_raw_values)
            (directory / "evidence.json").write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str))
            results.append({k: v for k, v in result.items() if k not in {"calls", "wire_requests", "raw_values", "plan", "draft"}})
            print(number, result["status"], flush=True)
    report = {"timestamp": datetime.now(timezone.utc).isoformat(), "cases": results,
              "scope": "live custom-path schema and deterministic sampling, not U routing, geometry or browser acceptance"}
    (args.output_dir / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
    return int(any(r["status"] != "protocol_pass" for r in results))


if __name__ == "__main__":
    raise SystemExit(main())
