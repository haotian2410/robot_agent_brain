"""Independent Scene/Commands oracle for the recovery browser audit."""
import json
import hashlib
from pathlib import Path
from audit_context_recovery import CASES, comp, save, digest

ROOT=Path('var/context-recovery-audit/20261119')
EXPECTATIONS={
 'A01':'左苹果 #7 → 篮子 #12；只生成计划', 'A02':'右苹果 #15 → 篮子 #12',
 'A05':'两个苹果 #7/#15 都进入计划', 'A06':'左苹果 #7；目的地改为托盘 #13',
 'A07':'只将左苹果 +X 移动 0.05m', 'A08':'只改左苹果蓝色，不生成抓放 Commands',
 'B01':'累计左苹果、右篮子；#7 → #16', 'B02':'最新修订替代旧选择；#15 → #12',
 'B03':'保留左苹果，只改目的地；#7 → #13', 'B04':'数量不丢失；#7/#15 → #16',
 'C01':'只将新增加的两个苹果改蓝', 'C02':'第二轮选择另一只苹果',
 'C03':'未执行计划不改变 Scene、不建立失败链；查询依据实际 Scene',
 'C04':'成功后的短句不得重放编辑', 'C05':'探索项：再新增一个或合理澄清',
 'D01':'独立查询香蕉数量', 'D02':'取消失败链后正常查询', 'D03':'完整新任务无重复副作用',
 'D04':'首次失败计入五次上限；第六轮不得恢复；完整新任务仍可用',
 'D05':'仅重启隔离 Brain，保留原失败链和场景',
 'E01':'香蕉只新增一次；恢复抓放步骤', 'E02':'香蕉、托盘只新增一次；仅删除左苹果',
 'E03':'继承原始场景授权，原始快照不变，当前香蕉改色不混入派生结果',
}

def objects(scene, model):
    return {o['object_id_in_scene']:o for o in scene['objects'] if comp(o).get('MetadataRef')=={'type':'model','path':f'$LIBRARY_SERVER/{model}'}}

def color(scene,oid):
    obj=next((o for o in scene['objects'] if o['object_id_in_scene']==oid),None)
    return comp(obj).get('MeshRenderer',{}).get('forceOverrideColor') if obj else None

def evaluate(group):
    last=group[-1]; case=last['case']; d=Path(last['evidence']); initial=json.loads((d.parent/'initial_world.json').read_text()); final=json.loads((d/'scene_after.json').read_text())
    checks={'all_unexecuted':all(r['executed'] is False for r in group),'screenshots':all(r['capture'].get('status')=='captured' for r in group)}
    identities=[]; versions=[]; states=[]
    for row in group:
        folder=Path(row['evidence'])
        old=json.loads((folder/'scene_before.json').read_text())
        new=json.loads((folder/'scene_after.json').read_text())
        state=json.loads((folder/'session_after.json').read_text())
        result=json.loads((folder/'task_result.json').read_text())
        identities.append(digest(state['scene'])==digest(new) and (not result.get('sceneDigest') or result['sceneDigest']==digest(new)))
        states.append(state['sync_state']=='synchronized')
        delta=2 if case=='E02' and row['turn']==1 else int(row['changed'])
        versions.append(new['scene_version']==(1 if new['scene_id']!=old['scene_id'] else old['scene_version']+delta))
    checks.update(brain_gateway_digest_match=all(identities),synchronized=all(states),version_changes_exact=all(versions))
    cmdpath=d/'artifacts/commands.json'; commands=json.loads(cmdpath.read_text()).get('commands',[]) if cmdpath.exists() else []
    picks=[c.get('parameters',{}).get('target') for c in commands if c.get('skill_name')=='pick']
    puts=[c.get('parameters',{}).get('target') for c in commands if c.get('skill_name')=='put']
    plans={'A01':([7],[12]),'A02':([15],[12]),'A05':([7,15],[12,12]),'A06':([7],[13]),'B01':([7],[16]),'B02':([15],[12]),'B03':([7],[13]),'B04':([7,15],[16,16]),'D03':([7],[12]),'D05':([7],[12]),'E01':([7],[12])}
    if case in plans:
        a,b=plans[case]; checks.update(plan_ready=last['outcome']=='plan_ready',sources=sorted(picks)==a,destinations=sorted(puts)==b)
        if case!='E01': checks['unchanged']=all(not r['changed'] for r in group)
    if case=='A07':
        old=objects(initial,1); new=objects(final,1)
        checks['move_5cm']=abs(comp(new[7])['Transform']['position'][0]-comp(old[7])['Transform']['position'][0]-.05)<1e-6
        checks['only_A']=all(o==next(n for n in final['objects'] if n['object_id_in_scene']==o['object_id_in_scene']) for o in initial['objects'] if o['object_id_in_scene']!=7)
    if case=='A08': checks.update(blue_A=color(final,7)=='#0000FF',B_unchanged=color(final,15)==color(initial,15),no_commands=not commands)
    if case=='C01':
        added=set(objects(final,1))-set(objects(initial,1))
        checks.update(two_added=len(added)==2,new_blue=all(color(final,i)=='#0000FF' for i in added),old_unchanged=all(color(final,i)==color(initial,i) for i in objects(initial,1)))
    if case=='C02': checks['both_blue']=all(color(final,i)=='#0000FF' for i in (7,15))
    if case=='C03':
        first_result=json.loads((Path(group[0]['evidence'])/'task_result.json').read_text())
        checks.update(first_plan=group[0]['outcome']=='plan_ready',no_failure_chain=first_result.get('conversation',{}).get('chain_state') in (None,'resolved'),unchanged=all(not r['changed'] for r in group),answer_or_clarify=last['outcome'] in ('answered','clarification_required'))
    if case=='C04': checks.update(no_replay=not last['changed'],no_commands=not commands,safe_reply=last['outcome'] in ('clarification_required','answered'))
    if case=='C05': checks['safe_exploration']=(last['outcome']=='clarification_required' and not last['changed']) or (last['outcome']=='scene_updated' and len(objects(final,1))==len(objects(initial,1))+2)
    if case in ('D01','D02','D04'): checks.update(query_answered=last['outcome']=='answered',unchanged=all(not r['changed'] for r in group))
    if case=='D02': checks['cancelled']=(group[1].get('error') or {}).get('code')=='failure_chain_cancelled'
    if case=='D04': checks['exhausted']=(group[5].get('error') or {}).get('code')=='conversation_recovery_exhausted'
    if case=='D05': checks['restart_recorded']=(d.parent/'restart_completed.json').exists()
    if case in ('E01','E02'):
        checks['first_failure_is_clarification']=group[0]['outcome']=='clarification_required'
        checks['correct_ambiguity_reason']=(group[0].get('error') or {}).get('code') in (None,'grounding_ambiguous')
        checks['banana_only_once']=len(objects(final,2))==len(objects(initial,2))+1
        if case=='E01': checks['resume_no_patch']=not last['changed']
        else: checks.update(tray_only_once=len(objects(final,17))==1,only_A_deleted=set(objects(final,1))=={15},delete_success=last['outcome']=='scene_updated')
    if case=='E03':
        # Derivation intentionally allocates new object IDs. Identify original
        # fixture objects by their unique preserved name, not obsolete IDs.
        mapped={o['object_name_in_scene']:o['object_id_in_scene'] for o in final['objects']}
        checks.update(blue_A=color(final,mapped.get('AppleA'))=='#0000FF',B_unchanged=color(final,mapped.get('AppleB'))==color(initial,15),original_basis=color(final,mapped.get('BananaE'))==color(initial,8),derived_scene=final['scene_id']!=initial['scene_id'])
    # Compare the actual pinned original across all per-turn snapshots.
    originals=[]
    for r in group:
        p=Path(r['evidence'])/'brain_evidence/original_scene.json'
        if p.exists(): originals.append(p.read_bytes())
    checks['original_immutable']=bool(originals) and all(o==originals[0] for o in originals)
    return checks

def main():
    rows=[]; cases=[]
    for run in sorted(ROOT.iterdir()):
        if not (run/'results.json').exists(): continue
        raw=json.loads((run/'results.json').read_text())
        for r in raw:
            r['run']=run.name
            e=Path(r['evidence']); result=json.loads((e/'task_result.json').read_text())
            r['conversation']=result.get('conversation',{})
            world=json.loads((e/'scene_after.json').read_text())
            r['scene_identity']={k:world.get(k,0) for k in ('scene_id','scene_version','scene_sub_version')}
            r['scene_identity']['sceneDigest']=digest(world)
            r['expected']=EXPECTATIONS[r['case']]
            r['screenshot_path']=str(e/'screenshot.png') if (e/'screenshot.png').exists() else None
            r['commit_receipts']=result.get('commitReceipts',[])
            original=e/'brain_evidence/original_scene.json'
            r['original_sha256']=hashlib.sha256(original.read_bytes()).hexdigest() if original.exists() else None
            state=json.loads((e/'session_after.json').read_text())
            chain=(state.get('conversation_memory') or {}).get('active_failure_chain') or {}
            r['semantic_draft']=chain.get('semantic_draft')
            r['step_ledger']=chain.get('step_ledger',[])
            r['model_calls']=result.get('metrics',{}).get('model_call_details',[])
            r['recovery_evidence_files']=[]
            for p in (e/'brain_evidence/conversation/recovery').glob('*.json'):
                rr=json.loads(p.read_text())
                if rr.get('client_request_id')==r.get('client_request_id'):
                    r['recovery_evidence_files'].append(str(p))
                    r['model_calls'].extend(rr.get('model_calls',[]))
            rows.append(r)
        for case,rep in sorted({(r['case'],r['repeat']) for r in raw}):
            group=[r for r in raw if r['case']==case and r['repeat']==rep]
            complete=len(group)==len(CASES[case])+(case=='E03')
            checks=evaluate(group) if complete else {'complete':False}
            cases.append({'run':run.name,'case':case,'repeat':rep,'expected':EXPECTATIONS[case],'passed':all(checks.values()),'checks':checks,'session':group[0]['session_id'],'evidence':str(Path(group[0]['evidence']).parent)})
    save(ROOT/'report.json',{'cases':cases,'turns':rows})
    print(json.dumps(cases,ensure_ascii=False,indent=2))

if __name__=='__main__': main()
