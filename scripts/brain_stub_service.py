"""Deterministic brain-web/2 stub for Gateway contract tests.

This intentionally does not load Qwen or assets.  It exercises task
submission, an unknown running state, terminal results, failure reasons and
the artifact whitelist.
"""
import argparse
import asyncio
from aiohttp import web


class Stub:
    def __init__(self):
        self.tasks = {}
        self.next_id = 1

    async def start(self, request):
        payload = await request.json()
        key = payload.get("clientRequestID")
        for item in self.tasks.values():
            if item["key"] == key:
                return web.json_response({"taskID": item["id"], "state": item["state"], "terminal": item["terminal"]})
        identifier = self.next_id
        self.next_id += 1
        self.tasks[identifier] = {"id": identifier, "key": key, "state": "规划中",
                                  "terminal": False, "polls": 0, "outcome": payload.get("stubOutcome", "plan_ready")}
        return web.json_response({"taskID": identifier, "state": "规划中", "terminal": False, "code": 0})

    def item(self, request):
        identifier = int(request.query.get("taskID", request.match_info.get("taskID", "0")))
        if identifier not in self.tasks:
            raise web.HTTPNotFound()
        return self.tasks[identifier]

    async def state(self, request):
        item = self.item(request)
        item["polls"] += 1
        if item["polls"] >= 2:
            item["state"], item["terminal"] = "已结束", True
        return web.json_response({"taskID": item["id"], "state": item["state"], "terminal": item["terminal"],
                                  "state_detail": "synthetic"})

    async def result(self, request):
        item = self.item(request)
        if not item["terminal"]:
            return web.json_response({"taskID": item["id"], "terminal": False}, status=202)
        result = {"taskID": item["id"], "outcome": item["outcome"], "executed": False,
                  "reply": "synthetic result", "synthetic": True,
                  "real_qwen_tested": False, "metrics": {"model_calls": 0},
                  "artifacts": {}}
        return web.json_response(result)

    async def failure(self, request):
        item = self.item(request)
        return web.json_response({"taskID": item["id"], "terminal": item["terminal"],
                                  "failureReason": "synthetic failure" if item["terminal"] and item["outcome"] == "failed" else None})

    async def health(self, request):
        return web.json_response({"service": "ready", "protocol": "brain-web/2", "executed": False,
            "qwen": "unavailable", "browser": "not_bound", "browser_id": None,
            "assets": "unconfigured", "capabilities": {}, "tasks": {"active_task_id": None, "queued": 0},
            "synthetic": True, "real_qwen_tested": False})

    async def reset(self, request):
        self.tasks.clear()
        self.next_id = 1
        return web.json_response({"reset": True})


def create_app():
    stub = Stub()
    app = web.Application()
    app.router.add_post("/startTask", stub.start)
    app.router.add_get("/queryTaskState", stub.state)
    app.router.add_get("/queryTaskResult", stub.result)
    app.router.add_get("/queryTaskFailureReason", stub.failure)
    app.router.add_get("/health", stub.health)
    app.router.add_post("/reset", stub.reset)
    return app


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8501)
    args = parser.parse_args()
    web.run_app(create_app(), host=args.host, port=args.port)


if __name__ == "__main__":
    main()
