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
    for name in ("run", "chat"):
        cmd = commands.add_parser(name)
        if name == "run":
            cmd.add_argument("instruction")
        for option in ("config", "scene", "assets", "defaults", "base-url", "model", "output-dir", "session", "replay-file"):
            cmd.add_argument("--" + option)
        cmd.add_argument("--provider", choices=["qwen", "replay"])
        cmd.add_argument("--structured-output", choices=["json_schema", "off"])
        cmd.add_argument("--timeout", type=float)
        cmd.add_argument("--seed", type=int)
        cmd.add_argument("--debug", action="store_true", default=None)
        cmd.add_argument("--json", action="store_true")
    schema = commands.add_parser("schemas")
    schema.add_argument("--output-dir", default="var/schemas")
    return root


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        if args.command == "schemas":
            directory = Path(args.output_dir).resolve()
            directory.mkdir(parents=True, exist_ok=True)
            for name, model in (("commands", CommandsFile), ("scene_config", SceneConfig), ("run_report", BrainRunReport)):
                path = directory / (name + ".schema.json")
                path.write_text(json.dumps(model.model_json_schema(), ensure_ascii=False, indent=2), encoding="utf-8")
                print(path)
            return 0
        options = {key:value for key,value in vars(args).items() if key in BrainConfig.model_fields and value is not None}
        if args.structured_output is not None:
            options["structured_output"] = args.structured_output == "json_schema"
        config = BrainConfig.load(args.config, overrides=options)
        provider = None
        if config.provider == "replay":
            if not config.replay_file:
                raise ValueError("config_missing: replay requires --replay-file")
            from .models.replay import ReplayProvider
            provider = ReplayProvider(config.replay_file)
        app = BrainApplication(config, provider=provider)
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
