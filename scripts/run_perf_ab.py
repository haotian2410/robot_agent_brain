"""Alternating A/B on a dedicated, initially stopped Brain port; no production services."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import random
import subprocess
import sys
import time
import httpx


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--runtime",type=Path,required=True)
    p.add_argument("--baseline",type=Path,required=True)
    p.add_argument("--candidate",type=Path,required=True)
    p.add_argument("--browser-id",required=True)
    p.add_argument("--pairs",type=int,default=10)
    p.add_argument("--seed",type=int,default=20261119)
    args=p.parse_args()
    repo=Path(__file__).resolve().parents[1]
    runtime=args.runtime.resolve()
    base=args.baseline.resolve()
    candidate=args.candidate.resolve()
    assert (base/"robot_agent_brain/models/prompts.py").is_file()
    assert (candidate/"robot_agent_brain/models/prompts.py").is_file()
    url="http://127.0.0.1:8503"
    with httpx.Client(timeout=1,trust_env=False) as c:
        try:
            c.get(url+"/health")
        except httpx.ConnectError:
            pass
        else:
            raise SystemExit("isolated_port_8503_must_be_stopped_first")
    rng=random.Random(args.seed)
    schedule=[]
    for i in range(args.pairs):
        order=["A","B"]
        rng.shuffle(order)
        schedule.extend({"pair":i+1,"variant":v} for v in order)
    manifest=runtime/"optimization-ab-schedule.json"
    if manifest.exists():
        raise SystemExit("AB schedule already exists; preserve previous evidence")
    sources={v:{str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted((root/"robot_agent_brain").rglob("*")) if p.is_file() and p.suffix in {".py",".txt",".json"}}
        for v,root in (("A",base),("B",candidate))}
    manifest.write_text(json.dumps({"seed":args.seed,"schedule":schedule,"sources":sources},indent=2)+"\n")
    env={k:v for k,v in os.environ.items() if k.upper() not in {"HTTP_PROXY","HTTPS_PROXY","ALL_PROXY"}}
    env.update(NO_PROXY="127.0.0.1,localhost",ROBOT_BRAIN_PERF_TRACE="1",
               PERF_TRACE_OUTPUT_DIR=str(runtime/"traces"))
    for item in schedule:
        variant=item["variant"]
        label=f"optimization-ab-{variant}{item['pair']:02d}"
        server_env={**env,"PYTHONPATH":str(base if variant=="A" else candidate)}
        cmd=[str(Path(sys.executable).parent/"robot-brain"),"serve","--config",str(runtime/"brain.json"),
             "--gateway-url","http://127.0.0.1:8096","--ols-url","http://127.0.0.1:8000",
             "--joint-inventory",str(repo/"var/webeditor/ols_latest_joint_inventory.json"),"--port","8503"]
        with (runtime/f"{label}-server.log").open("w") as log:
            server=subprocess.Popen(cmd,cwd=repo,env=server_env,stdout=log,stderr=subprocess.STDOUT)
            finished=False
            try:
                ready=False
                deadline=time.monotonic()+90
                with httpx.Client(timeout=30,trust_env=False) as c:
                    while time.monotonic()<deadline and server.poll() is None:
                        try:
                            health=c.get(url+"/health")
                            if health.status_code==200:
                                ready=True
                                break
                        except httpx.TransportError:
                            pass
                        time.sleep(.2)
                if not ready:
                    raise RuntimeError(f"AB server failed: {label}")
                print(json.dumps({**item,"state":"started","pid":server.pid}),flush=True)
                subprocess.run([sys.executable,str(repo/"scripts/run_perf_cases.py"),
                    "--runtime",str(runtime),"--browser-id",args.browser_id,
                    "--label",label,"--cases","P01,P04","--repeat","1"],
                    cwd=repo,env={**env,"PYTHONPATH":str(repo/"src")},check=True)
                print(json.dumps({**item,"state":"completed"}),flush=True)
                finished=True
            finally:
                # Only the child server started by this program is stopped.
                # On an observation error preserve it: a task may still run.
                if finished or server.poll() is not None:
                    server.terminate() if server.poll() is None else None
                    try:
                        server.wait(timeout=30)
                    except subprocess.TimeoutExpired:
                        raise RuntimeError("isolated_server_stop_timeout; inspect before continuing")
                else:
                    print(json.dumps({"state":"preserved_for_inspection","pid":server.pid}),flush=True)
    print("AB completed; isolated Brain port 8503 stopped, Gateway retained",flush=True)


if __name__=="__main__":
    main()
