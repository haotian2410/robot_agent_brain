"""Record optimization provenance and separate business diff from prior tracing."""
import argparse
import difflib
import hashlib
import json
import platform
import subprocess
from pathlib import Path


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args()
    repo=Path(__file__).resolve().parents[1]
    output=args.output.resolve()
    baseline=output/"baseline/robot_agent_brain"
    current=repo/"src/robot_agent_brain"
    paths={p.relative_to(root) for root in (baseline,current) for p in root.rglob("*")
        if p.is_file() and p.suffix in {".py",".txt",".json"} and "__pycache__" not in p.parts}
    changed=[]
    diff=[]
    phases={"S-output":[],"R-recovery-routing":[],"OLS-strict-diagnostics":[]}
    for relative in sorted(paths):
        old,new=baseline/relative,current/relative
        if sha(old)==sha(new):
            continue
        changed.append({"file":str(relative),"before_sha256":sha(old),"after_sha256":sha(new)})
        file_diff=list(difflib.unified_diff(old.read_text().splitlines(True) if old.exists() else [],
            new.read_text().splitlines(True) if new.exists() else [],
            fromfile="baseline/"+str(relative),tofile="src/robot_agent_brain/"+str(relative)))
        diff.extend(file_diff)
        phase="S-output" if str(relative)=="models/prompts.py" else (
            "OLS-strict-diagnostics" if str(relative) in {"web/assets.py","web/ols_snapshot.py"} else "R-recovery-routing")
        phases[phase].extend(file_diff)
    (output/"optimization-only.patch").write_text("".join(diff))
    for phase, lines in phases.items():
        (output/(phase+".patch")).write_text("".join(lines))
    repositories={"brain":repo,"control":repo.parent/"robot_agent_control",
        "ols":repo.parent/"ObjectLibraryServer","gateway":repo.parent/"web-frontend-master"}
    heads={name:subprocess.check_output(["git","rev-parse","HEAD"],cwd=root,text=True).strip()
        for name,root in repositories.items()}
    result={"repositories":heads,"python":platform.python_version(),"optimization_changes":changed,
        "skill_md_sha256":sha(repositories["control"]/"atomic_skill/skill.md"),
        "schema_sha256":sha(current/"contracts/commands_atomic.py"),
        "schema_unchanged":sha(current/"contracts/commands_atomic.py")==sha(baseline/"contracts/commands_atomic.py"),
        "planner":"qwen","execution_enabled":False,"ports":{"gateway":8096,"brain":8503},
        "control_execution":"not_run","model_cold_start":"not_run",
        "AB_code_snapshot":"candidate/ and baseline/; final unknown-state pre-model gates and explicit-ID recovery verification were added afterward and separately tested; they do not run on healthy P01/P04 AB cases",
        "source_note":"optimization-only.patch excludes the instrumentation already present in baseline"}
    (output/"environment.json").write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n")
    print(json.dumps({"changed_business_files":len(changed),"schema_unchanged":result["schema_unchanged"]}))


if __name__=="__main__":
    main()
