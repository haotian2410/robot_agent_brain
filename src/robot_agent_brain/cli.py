import argparse
import json
import sys
import uuid
from pathlib import Path
from .application import BrainApplication
from .config import BrainConfig
from .presentation import format_report, exit_code
from .contracts.commands import CommandsFile
from .contracts.scene import SceneConfig
from .contracts.run_report import BrainRunReport


def parser():
    root = argparse.ArgumentParser(prog="robot-brain", description="Brain native planning CLI; no robot execution")
    commands = root.add_subparsers(dest="command", required=True)
    for name in ("run", "chat", "batch"):
        cmd = commands.add_parser(name)
        if name == "run":
            cmd.add_argument("instruction")
        if name == "batch":
            cmd.add_argument("--cases", required=True)
            cmd.add_argument("--transport", choices=["direct", "service"], default="direct")
            cmd.add_argument("--agent-url", default="http://127.0.0.1:8500")
            cmd.add_argument("--gateway-url", default="http://127.0.0.1:8099")
            cmd.add_argument("--browser-id")
            cmd.add_argument("--task-timeout", type=float, default=300)
            cmd.add_argument("--allow-missing-screenshots", action="store_true")
        options = ["config", "assets", "defaults", "base-url", "model", "output-dir", "replay-file"]
        if name != "batch":
            options.extend(["scene", "session"])
        for option in options:
            cmd.add_argument("--" + option)
        cmd.add_argument("--provider", choices=["qwen", "replay"])
        cmd.add_argument("--planner", choices=["recipe", "qwen", "auto"])
        cmd.add_argument("--planner-max-completion-tokens", type=int)
        cmd.add_argument("--structured-output", choices=["json_schema", "off"])
        cmd.add_argument("--timeout", type=float)
        cmd.add_argument("--seed", type=int)
        cmd.add_argument("--debug", action="store_true", default=None)
        cmd.add_argument("--json", action="store_true")
    schema = commands.add_parser("schemas")
    schema.add_argument("--output-dir", default="var/schemas")
    serve = commands.add_parser("serve", help="Local WebEditor Agent; plans only, no Control")
    serve.add_argument("--config", required=True)
    serve.add_argument("--port", type=int, default=8500)
    serve.add_argument("--gateway-url", default="http://127.0.0.1:8099")
    serve.add_argument("--ols-url", default="http://127.0.0.1:8000")
    serve.add_argument("--joint-inventory", required=True)
    serve.add_argument("--camera-id", type=int, default=5)
    return root


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        if args.command == "serve":
            from .web.service import serve
            return serve(args)
        if args.command == "schemas":
            from .contracts.commands_v3 import CommandsFileV3
            from .contracts.feedback_v3 import ExecutionFeedbackV3
            from .contracts.robot_profile import RobotProfileRegistry
            directory = Path(args.output_dir).resolve()
            directory.mkdir(parents=True, exist_ok=True)
            for name, model in (("commands", CommandsFile), ("commands_v3", CommandsFileV3),
                                ("execution_feedback_v3", ExecutionFeedbackV3), ("robot_profiles", RobotProfileRegistry),
                                ("scene_config", SceneConfig), ("run_report", BrainRunReport)):
                path = directory / (name + ".schema.json")
                path.write_text(json.dumps(model.model_json_schema(), ensure_ascii=False, indent=2), encoding="utf-8")
                print(path)
            return 0
        if args.command == "batch" and args.transport == "service":
            from .batch_service import ServiceBatchRunner
            runner = ServiceBatchRunner(agent_url=args.agent_url, gateway_url=args.gateway_url,
                                        browser_id=args.browser_id, task_timeout=args.task_timeout,
                                        screenshot_required=not args.allow_missing_screenshots,
                                        output_dir=args.output_dir or "var/batch-runs")
            summary, directory = runner.run(args.cases)
            print(json.dumps({**summary, "output_dir": str(directory)}, ensure_ascii=False)
                  if args.json else f"{summary['totals']}\n{directory}")
            return 5 if summary["totals"]["blocked"] else (4 if summary["totals"]["failed"] else (2 if summary["totals"]["skipped"] else 0))
        options = {key:value for key,value in vars(args).items() if key in BrainConfig.model_fields and value is not None}
        if args.structured_output is not None:
            options["structured_output"] = args.structured_output == "json_schema"
        config_path = args.config
        if config_path is None and args.assets is None and args.provider != "replay":
            candidate = Path.cwd() / "config" / "final_models.json"
            if candidate.is_file():
                config_path = candidate
        config = BrainConfig.load(config_path, overrides=options)
        provider = None
        if config.provider == "replay":
            if not config.replay_file:
                raise ValueError("config_missing: replay requires --replay-file")
            from .models.replay import ReplayProvider
            provider = ReplayProvider(config.replay_file)
        app = BrainApplication(config, provider=provider)
        if args.command == "batch":
            from .batch import run_batch
            summary, path = run_batch(app, args.cases)
            print(json.dumps({**summary, "summary_path":str(path)}, ensure_ascii=False) if args.json
                  else f"Provider: {config.provider}\n{summary['totals']}\n{path}")
            return 4 if summary["totals"]["failed"] else (2 if summary["totals"]["skipped"] else 0)
        if args.command == "run":
            report = app.handle(args.instruction, session_id=args.session, scene_path=args.scene)
            print(report.model_dump_json() if args.json else format_report(report))
            return exit_code(report)
        session_id = args.session or uuid.uuid4().hex
        if args.scene:
            app.load_scene(session_id, args.scene)
        print(f"Session: {session_id}; /help /status /load PATH /exit", file=sys.stderr)
        while True:
            try:
                if sys.stdin.isatty():
                    print("> ", end="", file=sys.stderr, flush=True)
                line = sys.stdin.readline()
                if not line:
                    return 0
                line = line.strip()
                if not line:
                    continue
                if line == "/exit":
                    return 0
                if line == "/help":
                    print("/exit 退出客户端（不关闭语义会话）；/status；/load PATH", file=sys.stderr)
                    continue
                if line == "/status":
                    session = app.get_session(session_id)
                    print(f"scene={session.scene.scene_id if session.scene else None}; action={session.session_action}; sync={session.sync_state}", file=sys.stderr)
                    continue
                if line.startswith("/load "):
                    app.load_scene(session_id, line[6:].strip())
                    print("场景已加载", file=sys.stderr)
                    continue
                report = app.handle(line, session_id=session_id)
                print(report.model_dump_json() if args.json else format_report(report))
            except (ValueError, OSError) as exc:
                print(str(exc), file=sys.stderr)
    except KeyboardInterrupt:
        print("已中断，未报告成功。", file=sys.stderr)
        return 130
    except Exception as exc:
        if getattr(args, "json", False):
            print(json.dumps({"run_status":"failed", "error":{"code":"startup_failed", "message":str(exc)}}, ensure_ascii=False))
        else:
            print(str(exc), file=sys.stderr)
        return 4
