# failure-context v2 实施报告

## 范围

本轮按 `docs/failure-context-v2/01_implementation_plan.md`、
`02_acceptance_cases.md` 与 `04_source_review.md` 实施。旧 context v1 未执行，FR01–FR69
没有伪造为通过；真实 Control/机器人执行仍需单独授权。

## 阶段提交

| 阶段 | 本地提交 | 内容 | 验证 |
|---|---|---|---|
| M0 | `652ba31` | failure-context.v1 严格 Wire model 与独立 Prompt | schema 导入 |
| M1 | `fa6a99f` | 外层用户轮次、失败链、效果证据持久化 | session store 回归 |
| M2 | `1c90921` | 恢复护栏与默认关闭的歧义自动选择 | recovery 单测 |
| M3 | `374a286` | 独立 Qwen `failure_context` 调用阶段 | Qwen HTTP 回归 |
| M4 | `a47ee9b` | 会话恢复/自动选择配置与协议字段 | Web protocol 回归 |
| M5 | `93d5da7` | Web 外层最终化、R 只读恢复和链状态 | Web service 回归 |
| M6 | `7aa9a3c` | 五轮上限、payload 禁止、完成步骤保护测试 | failure-context 单测 |
| M7 | `1f8b22f` | 保留当前原子规划与 OLS 集成修复；补充用户日志、恢复证据、步骤账本和受控自动选择接缝 | 全量基线分类 |
| M8 | `a4ce8e6` | 控制端部分/未知执行结果不自动重放；仅对明确全失败且无持物的可重采样拒绝保留有限重试 | 组合编排与专项回归 |
| M9 | `8117210` | 分步副作用前持久化 pending ledger；持久化自动选择决策；增加 R→U scope/authority 护栏与证据摘要 | 专项回归 |
| M10 | `c41753c` | 对外报告使用配置的失败链上限，避免展示与实际策略不一致 | 专项回归 |
| M11 | `eac185a` | 在普通 U 副作用前核对 R 已接受字段，丢失条件时阻断；补回归测试 | 专项回归 |
| M12 | `e66b2b2` | 恢复上下文超过预算时拒绝截断并要求用户简化；补配置上限 | Web/配置回归 |
| M13 | `69738fd` | 完整 pytest 复核；R→U 条件校验覆盖 Scene Edit 属性颜色/布局字段 | 全量基线仍 11 项 |
| M14 | `5e9113e` | 失败链续接复用已持久化的 source/actor 选择；当前 Scene 仍由 Grounder 重新校验 | 专项回归 |
| M15 | `4190c4f` | 增加独立 failure_context.v1 Qwen HTTP 回归，验证 R 的独立 stage/schema | Qwen/失败上下文回归 |
| M16 | `0fcf564` | 恢复复合任务跳过已完成前缀；只为未完成步骤创建新 child request，无法匹配时安全阻断 | 组合编排回归；补充恢复前缀跳过单测 |
| M17 | `a41d44c` | 恢复轮禁止在用户未请求时漂移到 original 场景；补 scope 回归 | failure-context/Web 回归 |
| M18 | 工作区当前提交 | 将 R 接受的修订字段同步写入 `SemanticDraft`，保留字段来源且继续保持 `execution_authority=none`；补恢复草稿回归 | failure-context 专项回归 |

## 阶段证据明细

下表补充每个阶段的代码入口、业务链变化和验证边界。所有阶段均为本地提交，未推送；测试中的模型均为 replay/mock，未产生真实 Qwen token。

| 阶段 | 主要修改文件 | 业务链变化 | 测试命令/结果 | 模型调用统计 | 剩余问题 |
|---|---|---|---|---|---|
| M0 | `models/failure_context.py`、`models/prompt_templates/failure_context_v1.txt` | 建立严格、只读、无执行 payload 的 R Wire 与独立 Prompt | schema 导入通过 | 0（仅 schema） | 尚未接入真实 Provider |
| M1 | `session/conversation_memory.py`、`session/store.py`、`session/brain_session.py` | 外层用户轮次、失败链、最近视图和完整审计分离并持久化 | session store/专项测试通过 | 0 | 真实重启恢复未跑 |
| M2 | `grounding/ambiguity_policy.py`、`semantics/recovery_guard.py` | 默认询问；自动策略只允许受约束 source/actor，恢复决策不能改权限 | `test_failure_context_v2.py` 通过 | 0 | FR31–FR46 未逐例执行 |
| M3 | `models/qwen_http.py`、`models/qwen_failure_context.py` | 失败链下一轮才调用独立 R；正常 U 不拼接失败历史 | `test_qwen_http.py` 通过 | Mock 1 个 R 请求 | 真实 Qwen 路由/耗时/token 未验证 |
| M4 | `config.py`、`web/protocol.py`、`web/task_store.py` | 会话策略、自动选择和恢复配置可由服务端持久化 | `test_web_protocol.py`、`test_session_store.py` 通过 | 0 | 旧持久化库迁移需现场验证 |
| M5 | `web/service.py` | 外层任务完成后再终结用户轮次；R 结果先过 guard 再进入 U/接地/执行 | `test_web_service.py` 通过 | Mock R 按需调用 | unknown/lease 断线实证未跑 |
| M6 | `brain_tests/test_failure_context_v2.py` | 固定根轮、五轮上限、payload 禁止、晚到修订和完成事实保护 | 专项测试通过 | 0 | FR09–FR18 未全部映射执行 |
| M7 | `application.py`、`pipeline.py`、`session/conversation_journal.py`、`grounding/scene_grounder.py` 等 | 保留原子规划/OLS；记录 child request、选择决策和最终事实 | 组合专项回归通过 | replay/mock | 全量旧 fixture 仍有基线失败 |
| M8–M18 | `web/service.py`、`session/store.py`、`semantics/recovery_guard.py`、相关测试/文档 | 控制重试安全、pending ledger、R→U 字段核对、预算保护、选择复用、复合前缀防重放、scene basis 防漂移、SemanticDraft 修订证据 | 组合专项回归通过 | replay/mock | 真实 Qwen、Control、FR01–FR69 未执行 |

专项组合命令：

```bash
conda run --no-capture-output -n robot_agent_integ env PYTHONPATH=src \
  pytest -q \
  brain_tests/test_failure_context_v2.py \
  brain_tests/test_web_service.py \
  brain_tests/test_composite_orchestrator.py \
  brain_tests/test_session_store.py \
  brain_tests/test_web_protocol.py \
  brain_tests/test_qwen_http.py
```

结果：全部通过（当前组合 80 项；不包含真实服务调用）。

## 已验证

```text
pytest -q brain_tests/test_failure_context_v2.py
pytest -q brain_tests/test_qwen_http.py
pytest -q brain_tests/test_session_store.py
pytest -q brain_tests/test_web_protocol.py
pytest -q brain_tests/test_web_service.py
专项文件组合回归通过（composite orchestrator、failure-context、Qwen、session store、Web protocol/service）；当前组合共 80 项测试。
```

普通任务理解不会拼接 failure history；只有存在活动失败链的下一次外层用户轮次才会构造独立
`failure_context.v1` 请求。R 的结果必须再次经过 `RecoveryGuard`，不能直接改写场景、租约、ID、
平台或已完成步骤。失败链包含首个失败轮次，最多 5 个同链用户轮次；达到上限后进入
`exhausted`。

## 全量基线

全量 pytest 在当前 OLS/本地配置下仍有 11 项既有失败，主要是资产目录与历史 fixture 不一致、
双臂/机器人配置旧预期，以及本地配置缺少 geometry cache；它们不属于本轮新协议回归。完整输出
应以运行时日志为准，不将这些失败宣称为 FR 通过。本轮新增 M8 未增加资产/机器人配置之外的失败。

## 未覆盖/边界

- 真实 Qwen 对 R 的多轮联调、FR01–FR69 仍需在服务和浏览器稳定后逐例运行。
- unknown/partial execution/lease/recovery 的真实断线证据尚未在本轮自动注入测试中完成。
- 控制端执行重试已收紧：报告包含成功步骤、持物状态或未知/部分效果时不会自动重放；只有控制端明确返回可重采样的全失败结果才保留现有最多 5 次尝试。
- 复合任务在首个子步骤执行前写入 `pending_step_ledger`；最终外层轮次落档后才清理。重启发现未完成 ledger 时先进入恢复阻塞，不调用 R、不自动重放。
- `SelectionDecision` 已进入 `BrainResult`、Web/CLI `ConversationTurn` 和 `FailureChain`；R 的 scope、authority 字段和用户证据经过独立 guard，恢复证据保存根指令/草稿/决策摘要。
- R→U 条件核对已覆盖颜色、数量、距离、目标/参照、操作和放置字段；缺失时返回 `failure_context_u_condition_lost:*`，不会进入 SceneEditor、Grounder 或 Commands。
- 恢复输入按配置字符预算检查；超限返回 `context_budget_exceeded`，不调用 R、不截断否定/单位/目标条件。
- `prefer_auto_resolve=true` 的已选 source/actor ID 会在同链续接中复用；目的地、参照、破坏性目标和查询集合仍不会自动选择，删除/分支变化会重新触发校验而非换 ID。
- 恢复复合任务要求 R/U 返回完整原始步骤序列；已完成前缀按指令与 ledger 对照后标记 `reused`，不重放、不计入新的 child request。前缀无法匹配时返回 `failure_context_completed_steps_unmatched`。
- R 的 resolved instruction 若未经当前用户明确请求而引入“原始场景/original”，会被 `failure_context_scene_basis_drift` 阻断。
- `prefer_auto_resolve=true` 只允许稳定 ID、非破坏性且非 destination/query 选择；默认值仍为 false。

## 环境与调用统计

| 环境 | 状态 | 说明 |
|---|---|---|
| Mock/replay | 已验证 | 专项 pytest 覆盖 Wire、会话存储、恢复护栏、Web 编排与组合步骤；这些测试不计真实模型 token。 |
| 真实 Qwen | 未执行 | 本轮没有启动或调用真实 Qwen；因此没有可报告的真实调用次数/token。 |
| 隔离执行仿真 | 已验证 | 组合编排使用隔离 execution double，验证全失败可重采样、部分/未知效果不自动重放。 |
| 物理 Control | 未执行 | 未授权，不调用真实机器人或 Control。 |
| Python 3.11 | 已验证 | `python3.11 -m compileall -q src/robot_agent_brain` 通过（Python 3.11.14）。 |
| Python 3.12 | 已验证 | `conda run -n robot_agent_integ python -m compileall -q src/robot_agent_brain` 通过（Python 3.12.14）。 |
| wheel | 阻塞 | `conda run -n robot_agent_integ python -m build --wheel --no-isolation` 因环境缺少 `hatchling.build` 失败；未修改依赖环境。 |

专项 Mock/隔离测试没有 Qwen token 统计；真实 Qwen、Control 和 FR01–FR69 仍必须在独立服务环境中逐项执行后再补报告。
