"""Summarize preserved evidence; never turn safe failures into successful tasks."""
import csv
import json
import statistics
import xml.etree.ElementTree as ET
from pathlib import Path


def main():
    repo = Path(__file__).resolve().parents[1]
    root = repo / "var/perf/optimization-20261119"
    ab = json.loads((root / "ab_summary.json").read_text())
    assert len(ab) == 2 and all(r["complete_ten_pairs"] for r in ab)
    checks = json.loads((root / "correctness.json").read_text())
    assert checks and all(r["checks_passed"] for r in checks)
    rows = list(csv.DictReader((root / "cases.csv").open()))
    tests = {}
    for version in ("311", "312"):
        suite = ET.parse(root / f"pytest-release2-py{version}.xml").getroot().find("testsuite")
        tests[version] = {k: int(suite.get(k)) for k in ("tests", "failures", "errors", "skipped")}
        assert not tests[version]["failures"] and not tests[version]["errors"]
    recovery = [r for r in rows if r["group"] in {"optimization-final-recovery", "optimization-final-id"} and r["turn"] == "2"]
    mock = json.loads((root / "mock-P10-release/results.json").read_text())
    wheel = json.loads((root / "wheel-release2-smoke.log").read_text())
    assert wheel["wheel_smoke"] == "passed"
    summary = {"ab": ab, "regression": tests, "wheel": wheel,
        "final_recovery": recovery, "independently_checked_turns": len(checks),
        "mock_p10": mock, "not_run": ["Control execution", "true model cold start",
        "authoritative OLS cache hit", "atomic remote catalog update"],
        "services": "Only isolated Brain8503/Gateway8096 used; original services not restarted",
        "source": "Frozen A/B candidate differs from final source by unknown-state and explicit-ID safety checks; see environment.json"}
    (root / "report.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
    lines = ["# Brain 性能优化与接口修复报告", "", "## 结论", "",
        "建议合并 S 草稿输出约束、R 完整指令提示、有限短补充路由及恢复校验修复。没有启用不安全的 OLS 缓存，没有削减 U 约束，没有修改 Control 技能语义。未提交或推送。",
        "", "## 同时段随机顺序 A/B", "",
        "同一 Qwen、OLS、输入 Scene、Control skill SHA；固定 seed，10 对查询和 10 对规划。共享服务外部负载无法完全排除。每组不足20，不报告 p95。",
        "", "|用例|A中位秒|B中位秒|耗时变化|最终结果|", "|---|---:|---:|---:|---|"]
    for r in ab:
        lines.append(f"|{r['case']}|{r['A_median_ms']/1000:.3f}|{r['B_median_ms']/1000:.3f}|{r['median_change_percent']:.2f}%|A {r['A_outcomes']}；B {r['B_outcomes']}|")
    lines += ["", "规划 S 首答合法率 A 0/10 → B 10/10，模型调用从 U+S+S修复变为 U+S。所有计划再次通过严格 AtomicPlanValidator，并独立核对 Scene 身份、源/目标对象和无提交副作用。不是靠过滤非法字段得到通过。",
        "", "|规划调用指标（每任务中位）|A|B|", "|---|---:|---:|"]
    groups = {v: [r for r in rows if r['group'].startswith('optimization-ab-'+v) and r['case']=='P04'] for v in ('A','B')}
    for key in ('model_calls','prompt_tokens','completion_tokens','ols_http_requests','local_asset_hash_ms','qwen_http_ms'):
        values = [statistics.median(float(r[key]) for r in groups[v]) for v in ('A','B')]
        lines.append(f"|{key}|{values[0]:.2f}|{values[1]:.2f}|")
    lines += ["", "## 恢复正确性", "",
        "原 R 缺 resolved_instruction 已修复。实测左/右选择、目的地改托盘、取消、独立香蕉查询、ask_user 均保留原始证据。目的地修改后两个苹果仍须选择，返回澄清是正确行为。",
        "早期 R04 曾因 selection=all 和 quantity='2' 校验不一致失败，保留 task51/59 的失败记录；最终增加严格角色匹配及正整数等价校验后重测。扩展ID用例发现R输出'ID 17'与U的[17]被误判不一致（task111/113），补充严格ID格式等价校验后另组重测，历史失败不抹除。红色补充两次均进入R后继续ask_user，并未误执行改色；不宣称颜色恢复已自动成功。",
        "", "|最终用例|Task|结果|错误码|", "|---|---|---|---|"]
    for r in recovery:
        lines.append(f"|{r['case']}|{r['task_id']}|{r['outcome']}|{r['error_code']}|")
    lines += ["", "短句只跳过独立 U 预解析，不跳过 R、正常 U 或对象绑定。unknown/租约未知/pending执行先阻断；已执行步骤不重放。完整独立新任务仍重复 U 两次，这是明确保留的性能问题。",
        "额外ID补充仍有语义问题：格式等价检查修复后，Qwen将semantic_name写成apple_17，而非当前OLS的apple，导致grounding_binding_invalid。没有绕过绑定校验，没有生成Commands或修改场景；此扩展用例不列为已支持。",
        "恢复前16秒失败与恢复后约30秒成功不是同一结果，不用二者宣称加速；真正省去的是一轮无效预解析。最终恢复验证期间同时运行回归测试，仅用于正确性、不纳入A/B性能。",
        "", "## Qwen、OLS 与本地哈希", "",
        "首轮 U 约25K输入token。离线字段审计：system 44,794字符，其中基础规则25,544、空间附录1,896、资产目录17,354；user 29,475字符，其中资产目录26,121；Schema 17,017字符。字符数不是token数，资产信息重复是下一轮可评估的优化点，本轮未删除。",
        "服务端日志区分 prompt_eval（输入计算）和 eval（输出生成），可见 slot 复用；不能把 processed prompt tokens 当成完整上下文token，也不能把切换Prompt说成重新加载模型。采样中 U 输入计算约4.5秒、输出约6–12秒，小S输入约0.2–0.5秒、输出约2–7秒；这些服务器任务不能可靠逐一对应Brain taskID，详见原始timing证据。",
        "本地资产哈希约983个文件、678,788,656字节，耗时数百毫秒，低于模型与远端核验；本轮没有绕过哈希。",
        "OLS列表版本依据stat，保持size/mtime的内容变化可得到同版本。不能据此证明完整metadata未变，每轮仍3次list+86次metadata=89请求，约数秒。VerifiedOLSSnapshot仅记录顺序核验摘要，reusable=false，不保证远端并发更新时原子一致。需要OLS提供完整内容revision和按revision读取/原子快照接口后才能安全缓存。",
        "", "## 回归与范围", ""]
    for version, result in tests.items():
        lines.append(f"- Python {version[0]}.{version[1:]}：{result['tests']-result['skipped']} passed，{result['skipped']} skipped，0失败/错误。")
    lines += [f"- 独立wheel：安装目录外运行，planner=qwen + HTTP mock，严格计划校验通过；未调用真实模型/Control。",
        f"- P10：20对Mock tracing开/关，场景等价，耗时中位 {mock['off_median_ms']:.2f}/{mock['on_median_ms']:.2f}ms；包含文件系统噪声，非真实模型加速证据。",
        "- P11：mock成功/失败重发同clientRequestID，不增加模型调用或重复提交；真实重试未另测。",
        f"- {len(checks)}轮独立证据检查通过；其中包括历史预期失败，不能解读为{len(checks)}轮业务全成功。",
        "- Control执行、真正模型冷启动、权威OLS缓存命中、并发原子远端快照：not_run。没有操作真实机器人。",
        "", "## 修改与合并建议", "",
        "1. 合并：S草稿格式附录、R五决策完整示例、有限短句路由。保留严格Schema和有界重试。",
        "2. 合并：恢复选择谓词/角色、all/quantity/显式ID校验，及unknown前置门禁；这是正确性修复。",
        "3. 可合并诊断：严格OLS核验摘要和测试工具，但不得作为缓存性能收益宣传。",
        "4. 后续单独评估：重复U消除、资产目录去重、OLS权威内容revision。当前不做大幅Prompt精简。",
        "5. 不合并捷径：关闭校验、TTL缓存跳过远端核验、recipe替代Qwen、用历史轨迹冒充执行。",
        "", "## 证据入口", "",
        "- acceptance.md：逐条验收和未运行说明。",
        "- before_after.md / cases.csv / model_calls.csv：阶段耗时、token、请求与重试。",
        "- correctness.md / correctness.json：对象、Commands、身份及Scene副作用检查。",
        "- spans.jsonl / timeline.txt：原始span及时间线，不将父子wall重复相加或冒充CPU时间。",
        "- optimization-only.patch / baseline/instrumentation.patch / environment.json：业务修改与原有插桩分离；冻结A/B源哈希位于运行目录optimization-ab-schedule.json。",
        "- pytest-release2-py311/312.xml和log、wheel-release2-*、mock-P10-release/：最终代码测试。",
        "- ../runtime-20261119-01/optimization-*/：每轮输入、前后Scene、任务结果、调用和timeline；tasks/<session>/<request>/为原始模型及Commands产物。",
        "", "服务结束状态以service-end-state.json为准；用户原Qwen/OLS/Gateway/Brain未重启。"]
    (root / "report.md").write_text("\n".join(lines) + "\n")
    print(json.dumps({"report": str(root / 'report.md'), 'regression': tests, 'checked_turns': len(checks)}))


if __name__ == "__main__":
    main()
