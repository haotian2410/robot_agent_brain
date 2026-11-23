"""Summarize immutable baseline/retest rows; never replace failed attempts."""
import hashlib
import json
import subprocess
import httpx
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path
from report_context_recovery import ROOT, EXPECTATIONS

def main():
    report=json.loads((ROOT/'report.json').read_text())
    order={'first':0,'fixed':1,'final':2,'proof':3}
    report['cases'].sort(key=lambda c:(order.get(c['run'],99),c['case'],c['repeat']))
    report['turns'].sort(key=lambda r:(order.get(r['run'],99),r['case'],r['repeat'],r['turn']))
    latest={}
    for c in report['cases']:
        failed={k for k,v in c['checks'].items() if not v}
        c['classification']=('合理澄清（探索能力未支持）' if c['passed'] and c['case']=='C05'
                             else '通过' if c['passed']
                             else '环境/测试取证阻塞' if failed=={'screenshots'} else '代码 Bug')
        latest[c['case']]=c
    tests=ET.parse(ROOT/'pytest-final.xml').getroot().find('testsuite')
    report['automatic_tests']={k:tests.attrib[k] for k in ('tests','failures','errors','skipped','time')}
    report['automatic_skips']=dict(Counter(t.find('skipped').get('message') for t in tests.iter('testcase') if t.find('skipped') is not None))
    report['scope']={'gateway':'http://127.0.0.1:8096','brain':'http://127.0.0.1:8503',
                     'u':'compact_v1','r':'failure_context.v1','execution_enabled':False,
                     'transport':'真实 Agent HTTP 请求；真实绑定浏览器渲染，Gateway captureScene RGBD 截图',
                     'not_covered':['实体机器人执行','Control 部分执行的真实反馈','其他页面/账号并发','UI 输入框逐字手动提交']}
    report['latest_cases']=list(latest.values())
    assert len(latest)==23 and all(r['executed'] is False for r in report['turns'])
    service_end={}
    for name,port in [('qwen',8080),('ols',8000),('gateway',8096),('brain',8503)]:
        try:
            response=httpx.get(f'http://127.0.0.1:{port}/health',timeout=15)
            service_end[name]={'port':port,'http_status':response.status_code}
            if name=='brain':
                health=response.json()
                service_end[name].update({k:health.get(k) for k in ('service','qwen','browser','tasks','control_reason')})
                assert health['tasks']['active_task_id'] is None and health['tasks']['queued']==0
                assert health['control_reason']=='execution_disabled'
        except httpx.HTTPError as exc: service_end[name]={'port':port,'error':str(exc)}
    (ROOT/'service-end.json').write_text(json.dumps(service_end,ensure_ascii=False,indent=2)+'\n')
    report['service_end']=service_end
    report['counts']={run:dict(Counter('passed' if c['passed'] else 'not_passed' for c in report['cases'] if c['run']==run)) for run in order}
    report['counts']['latest']=dict(Counter('passed' if c['passed'] else 'not_passed' for c in latest.values()))
    report['classifications']={'latest':dict(Counter(c['classification'] for c in latest.values())),
                               'all_attempts':dict(Counter(c['classification'] for c in report['cases'])),
                               'model_fluctuation_confirmed':0,
                               'note':'不同阶段有输出差异，但本轮已定位失败为代码或取证问题；没有将未定位波动推定为模型不稳定。'}
    report['known_limits']=[
        'C05 再来一个返回合理澄清；不声称已支持所有成功后的省略续接。',
        'C03 查询读取真实 Scene，但位置回复仍是 support 字典，面向用户的自然语言表达仍可改进。',
        'ask_user 协议不携带 amendments：B 组阶段性条件主要由持久化最近对话累计，只有 resolved 时写结构化修订；不是完整的每轮 SemanticDraft 槽位更新器。',
        '首轮及早期复测未单独落盘 R 原始响应，保留了历史及恢复证据；proof 批次新增 R 输入/输出/调用记录，未反推补造旧响应。',
        'fixed/E03-1 使用旧相机 ID 导致取证失败；final/B02 两次使用需认证的错误备用端点导致部分截图失败，均为测试工具问题。保留失败记录，proof 使用当轮 Brain 绑定复测。',
        'D05 首轮在旧进程，续接在第一批修复进程；证明同数据库重启恢复，不宣称所有部署迁移均通过。',
        '早期 E01 的 captureScene 400 在取消无区分依据的视觉调用后不再触发；真正需要视觉时的同类 400 未单独复现，不宣称修好了所有视觉链路。',
        '准备阶段曾给 fixture 使用自定义 scene_name，被平台 profile 校验拒绝；改为保留 OLS 注册场景身份后开始 first 批次。这次未提交任务的准备阻塞不计入23组。',
    ]
    fixes=[
      ['上下文短补充被误判为新查询','B01–B03、E01','recovery_routing.py：将明确的对象补充/修订留给 R，不影响完整新任务入口'],
      ['修订条件校验角色与中文名不一致','A06/A07/E02','application.py：按 source/destination/edit-target 作用域与当前别名比较，禁止跨角色匹配'],
      ['目的地方位误作用于源对象','B04','qwen_http.py：方位修饰哪个明确名词就绑定哪个角色，不把右篮子条件加到苹果'],
      ['复数焦点被当成单对象','C01','scene_grounder.py：只对已确认 dialogue_ref_set 绑定集合展开，不扩大到原有苹果'],
      ['未执行计划错误建立失败链','C03及所有 plan_ready','web/service.py：plan_ready 是规划成功，不是执行失败；unknown 仍保留核验保护'],
      ['original 历史授权无法继承','E03','recovery_guard.py：同链短补充继承原用户授权，独立新任务不能继承'],
      ['无区分条件却触发视觉','E01','pipeline.py：普通名词/等价名称标签不是视觉区分条件，多候选直接询问'],
      ['导入对象宽泛类别丢失候选','E02','semantic_entity_selector.py：仅对通用分类补充 OLS 类别证据，不覆盖明确具体类别'],
      ['多步骤产物下载404','E01','web/service.py：允许当前任务已登记子请求目录，仍拒绝兄弟任务/路径穿越/符号链接逃逸'],
      ['R 审计记录缺失/修订不记角色','proof','web/service.py：在 U 重置诊断前持久化 R 输入输出，修订记录 subject_role'],
    ]
    report['fixes']=[dict(zip(('problem','cases','change'),f)) for f in fixes]
    changed=subprocess.check_output(['git','diff','--name-only'],text=True).splitlines()
    report['code']={'head':subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),
                    'committed':False,'pushed':False,
                    'modified_sha256':{p:hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in changed if Path(p).is_file()}}
    (ROOT/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    lines=['失败上下文与多步骤恢复专项报告','',
           '范围：23组；真实Qwen/Brain/Gateway/浏览器。所有机器人任务仅规划，executed=false，未调用Control。',
           '首次与每次复测分别保留；不以复测覆盖首次失败。',
           f"统计：{json.dumps(report['counts'],ensure_ascii=False)}",
           f"逐轮记录：{len(report['turns'])}；自动测试：{report['automatic_tests']}",'',
           '固定场景：苹果#7(-.25,-.23)、#15(.25,-.23)，篮子#12、托盘#13、香蕉#8；B增加篮子#16。',
           'E02初始无托盘，由第一轮创建；E03先改香蕉绿，再从original派生。真实AABB检查不放宽碰撞/支撑。','',
           '逐例最新验收：']
    for c in latest.values():
        lines.append(f"{c['case']} {'通过' if c['passed'] else '未通过'} [{c['run']}/{c['repeat']}] {EXPECTATIONS[c['case']]}；失败检查：{[k for k,v in c['checks'].items() if not v]}")
    lines+=['','修复内容：']+['；'.join(f) for f in fixes]
    lines+=['','边界与仍需改进：']+report['known_limits']
    lines+=['','服务结束状态见 service-end.json；本轮未提交、未推送；Gateway/前端无业务修改。',
            'Excel：context_recovery_results.xlsx，三列含实际指令、嵌入截图、真实回复；其余字段及逐轮证据可点击查看。']
    (ROOT/'report.txt').write_text('\n'.join(lines)+'\n')
    print(json.dumps(report['counts'],ensure_ascii=False))

if __name__=='__main__': main()
