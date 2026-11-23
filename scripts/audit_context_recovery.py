"""Real Qwen/WebEditor recovery audit. Never enables Control execution."""
import argparse
import copy
import itertools
import json
import shutil
import time
from pathlib import Path

import httpx
import numpy as np
from robot_agent_brain.batch_service import ServiceBatchRunner
from robot_agent_brain.config import BrainConfig
from robot_agent_brain.web.protocol import digest

CASES = {
    'A01':['把苹果放进篮子。','左边的。'],
    'A02':['把苹果放进篮子。','右边那个。'],
    'A05':['把苹果放进篮子。','两个都要。'],
    'A06':['把苹果放进篮子。','不要篮子，换成托盘，苹果选最左边的。'],
    'A07':['把苹果向右移动5厘米。','最左边那个。'],
    'A08':['把苹果放进篮子。','不放了，改为把最左边的苹果改成蓝色。'],
    'B01':['把苹果放进篮子。','左边的苹果。','右边那个篮子。'],
    'B02':['把苹果放进篮子。','左边的苹果。','不对，改成右边的苹果。','左边篮子。'],
    'B03':['把苹果放进篮子。','最左边的苹果。','换成托盘。'],
    'B04':['把苹果放进篮子。','那两个苹果都要。','放到右边的篮子。'],
    'C01':['新增两个苹果。','把它们都改成蓝色。'],
    'C02':['把最左边的苹果改成蓝色。','把另一个苹果也改成蓝色。'],
    'C03':['把最左边的苹果放进篮子。','苹果现在在哪里？'],
    'C04':['把最左边苹果改成蓝色。','右边那个。'],
    'C05':['新增一个苹果。','再来一个。'],
    'D01':['把苹果放进篮子。','有几个香蕉？'],
    'D02':['把苹果放进篮子。','算了。','查询桌面有几个苹果。'],
    'D03':['把苹果放进篮子。','把左边的苹果放进篮子。'],
    'D04':['把苹果放进篮子。']+['哪个我也不知道。']*4+['左边那个。','有几个香蕉？'],
    'D05':['把苹果放进篮子。','最左边那个。'],
    'E01':['新增一个香蕉，然后把苹果放进篮子。','最左边那个苹果。'],
    'E02':['新增香蕉，然后新增托盘，然后删除苹果。','最左边那个。'],
    'E03':['在原始场景中把苹果改成蓝色。','最左边的。'],
}

def save(p, value):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(value, ensure_ascii=False, indent=2)+'\n')

def comp(o):
    return {c['component_type']:c['properties'] for c in o['components']}

def fixture(config, case):
    root=Path(config.asset_library_root)
    scene=json.loads((root/'scenes/3/ur5_table_sorting.json').read_text())
    lookup={o['object_id_in_scene']:o for o in scene['objects']}
    scene['objects']=[o for o in scene['objects'] if o['object_id_in_scene'] in (0,1,2,3,4,5,6,14)]
    # Keep the actual OLS platform, create independent fixture instances only.
    spec=[(7,7,-.25,-.23,'AppleA'),(7,15,.25,-.23,'AppleB'),
          (12,12,-.5,.17,'BasketC'),(13,13,0,.17,'TrayD'),(8,8,.5,-.23,'BananaE')]
    if case.startswith('B'):
        spec.append((12,16,.5,.17,'BasketRight'))
    if case=='E02':
        spec=[s for s in spec if s[1]!=13]  # this case creates its own tray
    boxes={}
    for src,oid,x,y,name in spec:
        obj=copy.deepcopy(lookup[src]); obj['object_id_in_scene']=oid; obj['object_name_in_scene']=name
        c=comp(obj); t=c['Transform']; t['position'][:2]=[x,y]
        mid=c['MetadataRef']['path'].split('/')[-1]
        meta=next(json.loads(p.read_text()) for p in (root/'models'/mid).glob('*.json') if 'geometric_properties' in json.loads(p.read_text()))
        a=meta['geometric_properties']['AABB']; lo=np.array([min(a[i:i+2]) for i in (0,2,4)]); hi=np.array([max(a[i:i+2]) for i in (0,2,4)])
        # All copied OLS fixture assets have the verified +90 degree Z rotation.
        corners=np.array(list(itertools.product(*zip(lo,hi))))
        corners=corners @ np.array([[0,1,0],[-1,0,0],[0,0,1]])
        t['position'][2]=float(.6-corners[:,2].min())
        corners+=np.array(t['position']); mn=corners.min(axis=0); mx=corners.max(axis=0)
        assert mn[0]>=-.75 and mx[0]<=.75 and mn[1]>=-.375 and mx[1]<=.375
        for other,(omin,omax) in boxes.items():
            assert not np.all((mx>omin+1e-8)&(mn<omax-1e-8)), (oid,other,'fixture_collision')
        boxes[oid]=(mn,mx); scene['objects'].append(obj)
    # Preserve registered OLS platform identity; the fixture changes task objects only.
    scene['scene_version']=1
    return scene,{str(k):[a.tolist(),b.tolist()] for k,(a,b) in boxes.items()}

def main():
    p=argparse.ArgumentParser(); p.add_argument('--output',required=True,type=Path)
    p.add_argument('--runtime',type=Path,default=Path('var/perf/u-strict-20261119/web'))
    p.add_argument('--cases',default=','.join(CASES)); p.add_argument('--repeat',type=int,default=1)
    p.add_argument('--restart-brain',action='store_true')
    args=p.parse_args(); config=BrainConfig.load(args.runtime/'brain.json')
    assert not config.execution_enabled and config.conversation_recovery_enabled and not config.prefer_auto_resolve
    assert config.understanding_wire_format=='compact_v1'
    health=httpx.get('http://127.0.0.1:8503/health',timeout=30).json()
    assert health['control_reason']=='execution_disabled' and not health['tasks']['active_task_id']
    browser=health['browser_id']; args.output.mkdir(parents=True,exist_ok=True)
    save(args.output/'health.json',health); save(args.output/'cases.json',CASES)
    runner=ServiceBatchRunner(agent_url='http://127.0.0.1:8503',gateway_url='http://127.0.0.1:8096',output_dir=args.output,browser_id=browser,task_timeout=360,screenshot_required=False)
    runner.client.headers['X-WebEditor-Browser-ID']=browser
    rows=json.loads((args.output/'results.json').read_text()) if (args.output/'results.json').exists() else []
    try:
        for case in args.cases.split(','):
            for repetition in range(1,args.repeat+1):
                d=args.output/f'{case}-{repetition}'; d.mkdir(exist_ok=True)
                if sum(r['case']==case and r['repeat']==repetition for r in rows)==len(CASES[case])+(case=='E03'):
                    continue
                scene,boxes=fixture(config,case); save(d/'fixture.json',scene); save(d/'fixture_aabbs.json',boxes)
                if (d/'activation.json').exists():
                    activation=json.loads((d/'activation.json').read_text()); world=runner._world(browser)
                else:
                    activation=runner._activate(browser,scene); save(d/'activation.json',activation)
                    world=runner._load_preset(d/'fixture.json',browser); save(d/'initial_world.json',world)
                sid=activation['sessionID']
                instructions=CASES[case]
                if case=='E03': instructions=['把香蕉改成绿色。']+instructions
                for turn,instruction in enumerate(instructions,1):
                    if any(r['case']==case and r['repeat']==repetition and r['turn']==turn for r in rows): continue
                    e=d/f'turn-{turn}'; e.mkdir(exist_ok=True); before=world
                    if case=='D05' and turn==2:
                        if not args.restart_brain: raise RuntimeError('D05_requires_explicit_restart_flag')
                        # External supervisor may restart only this isolated service.
                        save(d/'restart_requested.json',{'session_id':sid,'port':8503})
                        print('RESTART_REQUIRED '+str(d),flush=True)
                        deadline=time.monotonic()+300
                        while not (d/'restart_completed.json').exists():
                            if time.monotonic()>deadline: raise RuntimeError('restart_not_confirmed')
                            time.sleep(.5)
                    if (e/'scene_before.json').exists(): before=json.loads((e/'scene_before.json').read_text())
                    else: save(e/'scene_before.json',before)
                    (e/'instruction.txt').write_text(instruction)
                    sp=Path(config.output_dir)/sid/'session_state.json'
                    if sp.exists(): shutil.copy2(sp,e/'session_before.json')
                    start=time.monotonic()
                    if (e/'accepted.json').exists():
                        accepted=json.loads((e/'accepted.json').read_text()); rid='resumed-existing-task'
                    else:
                        rid,accepted=runner._start_task(sid,browser,instruction,world)
                        save(e/'accepted.json',accepted)
                    print(json.dumps({'case':case,'repeat':repetition,'turn':turn,'task_id':accepted.get('taskID'),'state':'running'},ensure_ascii=False),flush=True)
                    state,result=runner._wait_task(accepted['taskID']); save(e/'task_state.json',state); save(e/'task_result.json',result)
                    world=runner._world(browser); save(e/'scene_after.json',world)
                    if sp.exists(): shutil.copy2(sp,e/'session_after.json')
                    try: runner._download_artifacts(result,e)
                    except Exception as exc: save(e/'artifact_download_error.json',{'error':str(exc)})
                    source=Path(config.output_dir)/sid
                    # Preserve per-request debug/commands and persisted original evidence.
                    if source.exists(): shutil.copytree(source,e/'brain_evidence',ignore=shutil.ignore_patterns('*.png','*.npy','*.npz'),dirs_exist_ok=True)
                    try:
                        saved_session=json.loads(sp.read_text()) if sp.exists() else {}
                        camera=result.get('camera_id') or saved_session.get('camera_id')
                        capture=runner._capture(browser,world,e/'screenshot.png',camera)
                    except Exception as exc: capture={'status':'blocked','reason':str(exc)}
                    save(e/'screenshot_metadata.json',capture)
                    row={'case':case,'repeat':repetition,'turn':turn,'instruction':instruction,'session_id':sid,'task_id':accepted.get('taskID'),'client_request_id':rid,'outcome':result.get('outcome'),'reply':result.get('reply'),'error':result.get('error'),'executed':result.get('executed'),'changed':digest(before)!=digest(world),'seconds':time.monotonic()-start,'capture':capture,'evidence':str(e.resolve())}
                    rows.append(row); save(args.output/'results.json',rows); print(json.dumps({k:row[k] for k in ('case','turn','outcome','error','changed')},ensure_ascii=False),flush=True)
                    assert result.get('executed') is not True,'unexpected_execution'
    finally: runner.client.close()

if __name__=='__main__': main()
