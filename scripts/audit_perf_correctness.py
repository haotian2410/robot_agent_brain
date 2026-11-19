"""Independent object/Scene/Commands assertions for completed perf turns."""
import argparse
import copy
import json
from pathlib import Path
import httpx
from robot_agent_brain.contracts.commands_atomic import AtomicCommandsFile
from robot_agent_brain.contracts.grounded_task import GroundedTask
from robot_agent_brain.contracts.scene import SceneConfig
from robot_agent_brain.planning.atomic_plan_validator import AtomicPlanValidator


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--runtime",type=Path,required=True)
    p.add_argument("--output",type=Path,required=True)
    args=p.parse_args()
    rows=[]
    with httpx.Client(timeout=30,trust_env=False) as client:
        for path in sorted(args.runtime.glob("optimization-*/*/turn-*/result.json")):
            row=json.loads(path.read_text())
            response=client.get("http://127.0.0.1:8503/queryTaskResult",params={"taskID":row["task_id"]})
            response.raise_for_status()
            result=response.json()
            (path.parent/"task_result_evidence.json").write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n")
            checks={"executed_false":result.get("executed") is False}
            errors=[]
            unchanged=row["scene_before_digest"]==row["scene_after_digest"]
            if row["case"] in {"P02","P03","P05"} and row["outcome"]=="scene_updated":
                before=json.loads((path.parent/"scene_before.json").read_text())
                after=json.loads((path.parent/"scene_after.json").read_text())
                old={o["object_id_in_scene"]:o for o in before["objects"]}
                new={o["object_id_in_scene"]:o for o in after["objects"]}
                commits=2 if row["case"]=="P05" else 1
                checks["edit_identity_and_version"]=(after["scene_id"]==before["scene_id"]
                    and after["scene_version"]==before["scene_version"]+commits)
                if row["case"]=="P02":
                    apple_ids=[i for i,o in old.items() if any(c["component_type"]=="Semantic" and
                        c["properties"].get("semantic_name","").lower()=="apple" for c in o["components"])]
                    expected=copy.deepcopy(old)
                    for i in apple_ids:
                        mesh=next(c for c in expected[i]["components"] if c["component_type"]=="MeshRenderer")
                        mesh["properties"]["forceOverrideColor"]="#0000FF"
                    checks["only_apple_color_changed"]=len(apple_ids)==1 and expected==new
                else:
                    checks["existing_objects_preserved"]=all(new.get(i)==o for i,o in old.items())
                    added=[o for i,o in new.items() if i not in old]
                    names=[c["properties"].get("semantic_name","").lower() for o in added
                        for c in o["components"] if c["component_type"]=="Semantic"]
                    checks["correct_added_objects"]=sorted(names)==(["apple","banana"] if row["case"]=="P05" else ["apple"])
                    checks["only_expected_new_ids"]=len(added)==commits and set(old)<=set(new)
            if row["outcome"] in {"plan_ready","answered","failed","clarification_required"}:
                checks["no_scene_commit"]=unchanged and result.get("scene_commit_status","unchanged")=="unchanged"
            if row["outcome"]=="plan_ready":
                directory=args.runtime/"tasks"/row["session_id"]/result["request_id"]
                try:
                    commands=AtomicCommandsFile.model_validate_json((directory/"commands.json").read_text())
                    task=GroundedTask.model_validate_json((directory/"debug/grounded_task.json").read_text())
                    scene=SceneConfig.model_validate_json((directory/"scene_config.json").read_text())
                    AtomicPlanValidator().validate(commands,task,scene)
                    checks["strict_atomic_validation"]=True
                    checks["request_and_scene_identity"]=(commands.request_id==result["request_id"]
                        and commands.scene_id==scene.scene_id and commands.scene_version==scene.scene_version)
                    picks=[c.parameters.target for c in commands.commands if c.skill_name.value=="pick"]
                    puts=[c.parameters.target for c in commands.commands if c.skill_name.value=="put"]
                    before=json.loads((path.parent/"scene_before.json").read_text())
                    apples=[]
                    baskets=[]
                    by_name={}
                    for obj in before["objects"]:
                        components={c["component_type"]:c["properties"] for c in obj["components"]}
                        name=components.get("Semantic",{}).get("semantic_name","").lower()
                        by_name.setdefault(name,[]).append(obj["object_id_in_scene"])
                        if name=="apple":
                            transform=components["Transform"]
                            # These fixed OLS fixtures are explicitly root-parented.
                            assert transform.get("parent") is None, "fixture_world_transform_required"
                            apples.append((transform["position"][0],obj["object_id_in_scene"]))
                        if name=="basket":
                            baskets.append(obj["object_id_in_scene"])
                    if row["case"] in {"P04","P07","P06","R02","R04","R-ID","R-COLOR"}:
                        ordered=sorted(apples)
                        if row["case"]=="P06" and row["turn"]==2:
                            assert len(ordered)==2 and ordered[0][0]!=ordered[1][0]
                            expected=[ordered[0][1]]
                        elif row["case"]=="R02" and row["turn"]==2:
                            assert len(ordered)==2 and ordered[0][0]!=ordered[1][0]
                            expected=[ordered[-1][1]]
                        elif row["case"]=="R-ID":
                            expected=[17]
                            assert 17 in [v[1] for v in ordered]
                        elif row["case"]=="R-COLOR":
                            expected=[o["object_id_in_scene"] for o in before["objects"] if o["object_name_in_scene"]=="Apple"]
                            assert len(expected)==1
                        elif row["case"]=="R04":
                            expected=[v[1] for v in ordered]
                        else:
                            assert len(ordered)==1
                            expected=[ordered[0][1]]
                        checks["correct_source_ids"]=sorted(picks)==sorted(expected)
                        checks["correct_destination_ids"]=len(baskets)==1 and puts==baskets*len(expected)
                    if row["case"]=="S06":
                        checks["two_sources_in_order"]=(picks==by_name.get("apple",[])+by_name.get("banana",[]) and len(picks)==2)
                        checks["both_to_same_tray"]=(len(by_name.get("tray",[]))==1 and puts==by_name["tray"]*2)
                        checks["no_intermediate_home"]=not any(getattr(c.parameters,"target",None)=="home" for c in commands.commands)
                        checks["one_s_request"]=sum(m.get("stage")=="skill_planning" for m in row["qwen_calls"])==1
                    if row["case"].startswith("S07-"):
                        expected_skill="pull" if row["case"]=="S07-open" else "push"
                        skills=[c.skill_name.value for c in commands.commands]
                        stroke=["approach","pick",expected_skill,"retreat"]
                        # Control skill.md explicitly allows a final home.
                        checks["drawer_skill_order"]=(skills==stroke or (
                            skills==stroke+["move_to"] and commands.commands[-1].parameters.target=="home"))
                        checks["drawer_target"]=len(by_name.get("drawer",[]))==1 and picks==by_name["drawer"]
                        checks["stroke_positive"]=all(c.parameters.distance>0 for c in commands.commands if c.skill_name.value in {"pull","push"})
                    checks["commands_nonempty"]=bool(commands.commands)
                except Exception as exc:
                    checks["commands_verified"]=False
                    errors.append(f"{type(exc).__name__}: {exc}")
            else:
                checks["no_commands_artifact"]=not any(a.get("name")=="commands" for a in result.get("artifacts",[]))
            rows.append({"task_id":row["task_id"],"case":row["case"],"turn":row["turn"],
                "outcome":row["outcome"],"checks":checks,"checks_passed":all(checks.values()),
                "errors":errors,"evidence":str(path.resolve())})
    args.output.mkdir(parents=True,exist_ok=True)
    (args.output/"correctness.json").write_text(json.dumps(rows,ensure_ascii=False,indent=2)+"\n")
    lines=["# 独立正确性检查", "", "本表检查身份、对象选择及无副作用，不将安全失败算成业务目标成功。编辑几何仍需各用例专项核对。", "",
        "|Task|用例/轮次|业务结果|检查通过|未通过项|", "|---|---|---|---|---|"]
    for r in rows:
        failed=[k for k,v in r["checks"].items() if not v]
        lines.append(f"|{r['task_id']}|{r['case']}/{r['turn']}|{r['outcome']}|{r['checks_passed']}|{failed or r['errors']}|")
    (args.output/"correctness.md").write_text("\n".join(lines)+"\n")
    print(json.dumps({"checked":len(rows),"failed_checks":[r for r in rows if not r["checks_passed"]]},ensure_ascii=False))


if __name__=="__main__":
    main()
