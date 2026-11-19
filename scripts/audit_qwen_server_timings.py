"""Read llama-server timing lines; no request text or uncertain client-ID joins."""
import argparse
import json
import re
from pathlib import Path


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--log",type=Path,required=True)
    p.add_argument("--output",type=Path,required=True)
    p.add_argument("--last",type=int,default=30)
    args=p.parse_args()
    pattern=re.compile(r"id\s+(\d+)\s*\| task (\d+)\s*\|\s*(prompt eval|eval|total) time\s*=\s*([\d.]+) ms /\s*(\d+) tokens")
    tasks={}
    lines={}
    for line in args.log.read_text(errors="replace").splitlines():
        found=pattern.search(line)
        if found:
            slot,task,phase,ms,tokens=found.groups()
            key=int(task)
            tasks.setdefault(key,{"server_task_id":key,"slot":int(slot)})
            tasks[key][phase.replace(" ","_")]=dict(ms=float(ms),tokens=int(tokens))
            lines.setdefault(key,[]).append(line)
    selected=[v for _,v in sorted(tasks.items()) if all(k in v for k in ("prompt_eval","eval","total"))][-args.last:]
    args.output.mkdir(parents=True,exist_ok=True)
    result={"source":str(args.log),"scope":"recent server tasks; not joined to Brain task IDs",
        "notes":["prompt_eval measures processed prompt tokens, not total context tokens",
            "eval measures output generation; client HTTP time includes other overhead",
            "slot reuse is visible but exact KV-cache-hit token count is not asserted"],"tasks":selected}
    (args.output/"qwen-server-timings.json").write_text(json.dumps(result,indent=2)+"\n")
    (args.output/"qwen-server-timing-lines.txt").write_text("\n".join(line for row in selected for line in lines[row["server_task_id"]])+"\n")
    print(json.dumps({"recorded_tasks":len(selected),"last":selected[-1] if selected else None}))


if __name__=="__main__":
    main()
