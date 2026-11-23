# robot_agent_brain：失败触发上下文与二值歧义策略实现计划

版本：设计稿 v2.0（待实施，不是验收报告）  
审查基线：`3c568c23752418d9c15321fbd321b3696c8eaef5`  
范围：正常轮次留档；失败轮起点；最多五个失败用户轮次；独立 Qwen 续接理解；询问优先／自动选择优先。  
交付对象：Codex 与 Brain／前端／Control 联调人员。

> 本计划取代旧附件中“每轮把最近五轮交给正常任务理解 Qwen、默认不增加模型调用”的设计。正常处理链不增加聊天历史；只在失败任务的后续用户轮次进入独立上下文理解调用。无需 RAG、向量数据库或新的多 Agent 框架。
>
> 本次只审查源码和设计方案，没有运行本仓库测试、Qwen、OLS、Gateway、浏览器、Control 或真实机器人。所有附带验收用例均为 `not_run`。

## 0. 决策摘要

### 0.1 采纳的产品要求

1. 每个用户轮次都记录：用户原文、系统最终回复、实际结果和版本证据。
2. 第一次任务未完成时记录 `root_failure_turn_id`；后续同一失败链的起点不随新失败前移。
3. 用户后续补充、回答系统问题、修改目标或方法时，独立 Qwen 读取“首失败轮至今”的上下文。
4. 同一失败链最多 **5 个未成功的用户轮次，包含首失败轮**；不是首轮再加五轮，也不是五次模型／Control 请求。
5. 明确的部分任务语义可以形成草稿；最终完整任务仍经过原有理解、接地、编辑／查询／规划和执行校验。
6. 增加二值策略 `prefer_auto_resolve`：false 为询问优先；true 为在受约束的可替代候选中自动选择优先。
7. 原有正常功能、当前 `task_understanding.v3.1`、原子技能 Commands、RSI/Gateway 必填协议不因本功能重写。

### 0.2 必须补充的约束

- “记录失败”不等于“允许模型自动重试”。结果未知、真实执行部分成功、持物、租约不明、发布失败必须先核验现场。
- 随机选择仅处理**满足现有接地规则且允许自动选择的实例身份不唯一**，不能猜目标容器、操作类型、距离、资产或技能参数。**颜色特例沿用原逻辑**：有可靠颜色标签／实例颜色证据时按证据筛选；没有可判断贴图颜色的可靠证据时，允许对无颜色证据的同类候选按原有描述回退机制进行 auto 随机选择（仅 `prefer_auto_resolve=true`）；不能声称选中的对象实际就是指定颜色。
- 当前代码存在拆分并逐步提交；复合任务前缀已经完成时，只续接失败步骤与未执行后缀，绝不整句重放。
- 五轮耗尽表示“本次续接停止”，不是证明系统永久不具备该功能。
- 半成品保存为 `SemanticDraft`，不能保存为可下载／可执行的 Commands。
- 正常功能与续接模块分离，但共用权威 Scene、候选校验、发布策略、事务和执行安全边界，不能建立旁路执行器。

### 0.3 推荐初始配置（拟新增）

```json
{
  "conversation_recovery": {
    "enabled": true,
    "max_failed_user_turns": 5,
    "recent_turns_retained": 5,
    "max_context_input_tokens": 6000,
    "max_recovery_output_tokens": 1500,
    "semantic_repair_retries": 0
  },
  "ambiguity_policy": {
    "prefer_auto_resolve": false
  }
}
```

Token 数是部署起始建议，不是模型硬限制；使用实际 tokenizer 测量。不得截掉 root 用户指令中的否定、数量、单位或尚待执行步骤以满足预算。超限时有诊断地拒绝或要求缩短任务，不偷偷丢条件。

二值标记建议默认 false 以保持询问行为；用户可在会话建立前开启 true。该建议并不改变“自动选择优先”模式的用途。

## 1. 最新代码对设计的影响

本节为当前源码观察，后续章节是拟议实现。

| 已有位置 | 当前行为 | 本方案落点 |
|---|---|---|
| `session/dialogue_state.py` | 最近实体／集合焦点，代词与“另一个”处理；无完整五轮记忆 | 保留，不把失败链放进 last_entity_ids |
| `session/store.py::SessionState` | Scene、Dialogue、计划、unknown／recovery 状态的 checkpoint | 增加兼容的 conversation_memory 字段 |
| `application.py::_handle()` | 理解、接地、产物发布；每次子调用生成 request_id | 产出子步骤证据，不承担 Web 整轮最终成功判定 |
| `web/service.py::execute()` | 获取租约，选择单步或拆分执行，释放租约后终结外层 Task | 用户轮次的最终汇总与失败链更新入口 |
| `web/service.py::_run_step()` | `app.handle()` 后还可能 dispatch Control | 不能把 app 的 plan_ready 当作整轮最终成功 |
| `web/service.py::_run_steps()` | 成功前缀保留，遇到失败停止；记录 not_run 后缀 | 需要稳定 step_id 和可恢复步骤账本 |
| `MAX_STEP_ATTEMPTS=5` | 某些执行错误最多五次内部尝试 | 与新“五个用户失败轮次”彻底分开 |
| `pipeline.py::decompose()` | 可选整句拆分模型调用 | 续接不能重新拆分已完成的整条原指令 |
| `SceneGrounder.GroundingAmbiguous` | 已携带 entity、candidates | 可扩展成类型化 AmbiguityIssue，复用现有候选发现 |
| `semantic_entity_selector.py` | 存在颜色证据缺失／不匹配回退及 tag 排序 | 保留原有颜色回退：有颜色标签／覆盖证据优先匹配；贴图颜色不可验证时允许从无颜色证据的同类对象中 auto 选择；其他硬约束仍需严格校验 |
| `ports/execution.py::ExecutionOutcome` | ok、步骤结果、moved、holding_object、轨迹 | 增加内部副作用证据视图；ok=false 不足以证明无动作 |
| `contracts/release_policy.py` | 平台换装与 RobotSetup 禁令仍在；执行能力由当前执行配置控制 | 不照抄旧方案“始终禁止 Control”的前提，也不自动启用现有关闭能力 |

**当前不是纯 Commands 导出的旧版本。**必须以目前 `_run_step → dispatch → feedback/writeback → release lease` 的完整结果写记忆。

## 2. 三个概念严格分开

### 2.1 用户轮次 UserTurn

一次用户提交及其最终系统回复。Web 唯一键为 `(sessionID, clientRequestID)`；一个 Web Task 可以包含多次 `app.handle()`、多个 request_id、多个 Control attempt，但仍是一轮。

建议增加服务端生成的 `turn_id`，固定绑定 TaskStore 幂等记录。`root_failure_turn_id` 指向它，不指向随机变化的最后一个子步骤 request_id。

CLI 由最外层用户调用分配 turn_id。内部 `_run_step()` 透传执行上下文并禁止重复创建用户轮次。

### 2.2 正常记忆 Journal / RecentTurns

每轮都记。持久审计沿用现有请求产物并增加统一轮次索引；Session 中只保留最近五轮轻量视图。正常任务理解请求不因此收到这五轮聊天。

正常成功后的“它／另一个”继续使用已有 DialogueState。本期不承诺新增通用成功后闲聊记忆；“再来一个”在无失败链时仍属于原系统能力范围。以后若需要可单独扩展，不混入本次失败续接。

### 2.3 失败链 FailureChain

同一未完成意图的有限续接。根轮不变，最多一个 active chain；完整日志不受五轮窗口删除限制。失败链使用自己的引用列表，不能只拿 `recent_turns[-5:]` 代替根轮起切片。

首失败用户原句若含“它”，要保留当时已确认的焦点／语义展开证据；无需附带所有首失败轮之前的聊天，但也不能丢掉原指代出处。

## 3. 五轮的唯一计数规则

| 用户轮次 | 同链结果 | failed_user_turns | 后续 |
|---|---|---:|---|
| 根轮 T1 | 第一次歧义／可改写失败 | 1 | 提问并等待 |
| T2 | 用户补充后仍未完成 | 2 | 允许继续 |
| T3 | 再次失败 | 3 | 允许继续 |
| T4 | 再次失败 | 4 | 最后一次补充机会 |
| T5 | 再次失败 | 5 | EXHAUSTED，停止自动续接 |
| 任一 Tn | 整个待办范围完成 | 不再累加 | RESOLVED |

约束：

- 一个已接纳并最终处理的同链用户消息，最多累加一次。
- 一个用户消息中的 R 调用、U 调用、二次规划、视觉、Control attempt 不各自计轮。
- 同 `clientRequestID` 的网络重发、轮询、回执补到、重启恢复不增加轮次。
- 第三步失败、下一轮第三步成功但第四步失败，仍是原失败链；本轮整体未完成而加一，不能因局部成功重置计数。
- 新的独立任务经判定后，旧链 SUPERSEDED；新任务失败才创建新的根轮。
- 取消不算一次失败，记取消事实后清除 active pointer。
- 未接纳的鉴权／会话忙／已知隔离状态拒绝不是一次业务尝试，不消耗额度；若已接纳后发生模型或环境失败，记录该用户轮次。基础设施阻断进入 BLOCKED，不循环消耗五次请求。
- 当前第五轮输入前，最多四个已失败用户轮次加当前输入；当前终态失败后形成五条记录。不存在偷偷加入第六轮。
- 用户只是换了一种说法继续同一失败目标，不能重置根轮。耗尽后不能由 Qwen 自行创建新链；需要明确新的完整请求或前端显式“新任务”。

推荐提示：

> 本任务已连续 5 轮未完成，已停止本次上下文续接。已完成：…；尚未完成：…；当前阻塞原因：…。可以重新提交完整任务，或先处理上述环境／能力问题。

不要统一写“功能无法做到”，否则会把“指代还不明确”错误说成永久不支持。

## 4. 失败分类：全记录，分流续接

新增 `FailureClassifier`，基于类型化错误、阶段与副作用证据，不只匹配 error.code 字符串。

| 分类 | 例子 | 下一轮处理 |
|---|---|---|
| USER_REVISABLE | 对象／参照歧义，数量不明，Qwen 主动澄清 | WAITING_USER；可调用 R |
| SAFE_REJECTED | 编辑碰撞／越界、容器不足、规划前安全拒绝，确认未提交 | 可让用户修改目标／距离／位置，再全链校验；不能放宽原安全约束 |
| MODEL_INVALID | 输出缺字段、非法 JSON，且未发生副作用 | 保存原指令与诊断；下轮可重述；不把坏 JSON 伪装为有效草稿 |
| CAPABILITY_BLOCKED | 动态换臂、双臂不支持、未注册技能 | 记录失败；不可绕过开关。用户明确改成可支持任务时可 R 判 revise/new |
| ENVIRONMENT_BLOCKED | OLS／几何缓存损坏、服务离线、配置缺失 | 暂停续接执行；先修环境。不要让 Qwen“生成正确缓存” |
| SYSTEM_DEFECT | internal_error、不可解释异常 | BLOCKED；保留诊断，不能靠补充语言掩盖程序错误 |
| EFFECT_UNKNOWN | commit ACK 丢失、unlock 未确认、Control 超时或状态未知 | BLOCKED_RECONCILIATION；既有事务核验优先，禁止自动执行 |
| PARTIAL_EXECUTION | 有步骤实际运行、持物、移动状态未确认 | 先获得权威现场与安全恢复点，不重新运行整段 Commands |
| SIMULATION_DISCARDED | 已证实独立仿真 scratch 被丢弃、无写回、无真实机器人动作 | 当前 Scene 确认后才可按用户修改重新规划；不能仅由失败码推定 |

`ExecutionOutcome.ok=false`、`executed=false`、浏览器 digest 未改变，分别都不足以证明物理设备完全没动。

拟新增内部 `EffectEvidence`：

```text
scene_effect: none_confirmed | committed | unknown
execution_effect: not_started | simulation_discarded | partial_confirmed | completed | unknown
execution_environment: isolated_simulation | physical_robot | unknown
holding_state: empty_confirmed | holding_confirmed | unknown
publication_state: none | published | failed | unknown
lease_state / transaction_id / control_run_id / evidence_source
```

这些由服务、Gateway 与 ExecutionPort 证据生成，模型不可填。外部旧协议没有提供的数据默认 unknown；不能为了省事假设 not_started。可先用兼容的内部适配视图，不必修改 Control 强制字段。

## 5. 新模块与调用架构

### 5.1 推荐架构

```text
用户提交（分配稳定 turn_id，读取会话策略）
  │
  ├─ 没有 active failure chain
  │    └─ 原 decomposition / understanding / editor-query-planner / dispatch 链
  │         └─ 整轮最终记录；未完成则建立 failure chain
  │
  └─ 存在 active failure chain
       ├─ 检查安全状态、链轮数、权威 Scene 与版本
       ├─ 新增 Qwen R：failure_context.v1（只读，独立 Prompt/Schema）
       ├─ Python RecoveryValidator
       └─ R 决策
            ├─ ask_user：记录问题，不调用原业务处理
            ├─ cancel：取消未完成部分，保持已完成事实
            ├─ new_task：关闭旧链，用当前独立请求走原流程
            └─ continue / revise：只恢复合法剩余范围
                    └─ 原 Qwen U 输出完整 task_understanding.v3.1
                         └─ 结构差异／语义证据验证
                              └─ 原 Grounding / 编辑 / 查询 / Planner / 执行
  │
  └─ dispatch、回写、发布、租约结果确定后 finalize_user_turn()
```

R 是恢复理解（Recovery understanding），U 是当前原有任务理解。R 不产出可执行 Commands，不直接提交 Scene，不绕过 U。正常 Prompt 与正常消息体不追加恢复历史。

### 5.2 调用次数

- 正常路径：保持当前实际调用数，包括已有可选 decomposition、每子任务 U、skill planner、视觉与有界修复；不是承诺固定只有一次调用。
- 续接到可执行完整意图：本轮额外一个 R，再进入原 U 和后续链。
- R 决定追问／取消：只有 R，不调用 U／Planner／Control。
- 禁止 `R→失败→R→失败` 无界自循环。首失败产生后等待用户回复，不立刻自动开 R。
- 独立 Provider 实例或独立诊断通道，避免 `begin_turn()`、last_raw_values、call trace 被后续子步骤清空。
- 原有模型修复和 Control 重试沿用单独预算；不要再包一个五次自动恢复循环，形成 5×5 的隐式重试风暴。

### 5.3 不推荐的捷径

- 不把失败后五轮原文拼进旧 `instruction`。
- 不让 R 同时担任规划器、执行器和错误修复器。
- 不让 R 直接返回手工拼装的 Commands，跳过接地。
- 不把原任务从头重新 decompose 再执行；成功前缀不能重演。
- 不用 R 接管所有正常任务的路由，避免每轮多一次模型调用和行为漂移。

## 6. 存储模型与草稿

以下为拟议模型，不是仓库已有接口。以 Pydantic 严格模型落地，不用任意 dict 贯穿所有层。

### 6.1 ConversationTurn

```text
turn_id, session_id, web_task_id?, client_request_id?, sequence
raw_user_text, effective_instruction?, assistant_final_text
final_outcome, final_error_code?, final_stage?
scene_before, scene_after                 # identity + digest，不复制完整场景
child_request_ids[], step_ledger_ref?
scene_commit_status, execution_status, executed
publication_status, lease_status, effect_evidence
context_chain_id?, root_failure_turn_id?
auto_selection_decisions[]
finalization_revision, created_at, finalized_at
```

必须分别记录 raw 与 effective：用户回答“左边的”仍是用户原话；R 重建的“将左侧苹果放入托盘”是模型派生文本。

已确认执行反馈与计划分开：`plan_ready` 不写成“物体已经移动”。整轮执行成功但截图失败，也不能改写为“此前没有动作”。

### 6.2 FailureChain

```text
chain_id, root_failure_turn_id, root_task_id?
state: waiting_user | blocked_environment | blocked_system |
       blocked_reconciliation | resolving | resolved |
       exhausted | cancelled | superseded
failed_user_turn_ids[]                    # 去重，长度即计数，最大5
last_attempt_turn_id, last_failure_request_id?
root_instruction, latest_question
accepted_task_revision, semantic_draft_ref?
step_ledger[]                            # 成功前缀、失败步、not_run后缀
current_failed_step_id?, remaining_step_ids[]
scene_binding, catalog_revision, platform_signature, config_fingerprint
policy_snapshot                          # prefer_auto_resolve 等
selection_decisions[]
constraint_revision, lifecycle_revision
```

root 不变；最新版语义草稿可以变化，必须留变更记录。状态 `resolving` 仅表示服务正在处理当前回复，不应在等待用户期间占用 Gateway 租约。

### 6.3 SemanticDraft

```text
source_request_id
validity: validated_turn | partial_semantics | unparsed
canonical_turn?                          # 只有原 BrainTurn 已通过 schema 才存在
known_fields[]                           # 路由、操作、对象语义、数量、落点等
unresolved_slots[]                       # 角色、原因、允许补充类型
confirmed_bindings[]                     # 来源、验证场景、有效性
candidate_evidence[]                     # 严格候选、硬条件、缺失证据
field_provenance[]                       # 来源turn/span/模型提议/程序确认
execution_authority: none                # 常量，不给模型控制
```

例：原任务是 source=apple，destination=tray，inside；仅 apple 身份不唯一。draft 保存这些字段和苹果候选，但不会预先生成 grasp/place command_id、轨迹、关节状态或 Commands 文件。

Qwen 原本返回 clarification/null payload 时，允许没有 canonical_turn。不要用 `model_construct()` 造一个看似 accepted 的半成品。使用独立 partial draft 类型，未知值显式标记。

### 6.4 保存位置与一致性

- `SessionState` 增加 `conversation_memory`，缺省为空，旧 checkpoint 可加载。
- 现有 request 目录仍保存完整业务证据；新增 `conversation/turns/<turn_id>.json` 保存用户层结果视图，或者复用现有持久原子 JSON 工具。
- active chain 的权威版本放在 Session checkpoint，其他文件只是可校验引用／证据；不要在 TaskStore 和另一个 chain JSON 中各维护一套独立状态机。
- 用户层 finalizer 只按 turn_id upsert 一条记录。内层 `app.handle()` 只更新 child evidence。
- 崩溃时先按已有 PublicationStore／Gateway transaction 恢复事实，再修复历史视图，绝不为了补记忆而执行任务。
- 需要跨 TaskStore/checkpoint 的一致性时，采用持久化 prepare/finalized 标记和重启对账，不假装两份文件写入天然是一个事务。
- late feedback 更新事实修订号，不增加 failed_user_turns，也不重复插入 recent_turns。

## 7. 独立 Qwen 续接协议

新文件建议：`models/failure_context.py`、`models/qwen_failure_context.py`、`models/prompt_templates/failure_context_v1.txt`。

### 7.1 输入 FailureContextRequest

```text
protocol_version = failure_context.v1
current_user_text
root_failure_turn_id
history[]                 # 根失败轮到当前之前，各含user/assistant/outcome/effects
latest_task_draft
step_ledger               # completed 是只读事实
unresolved_slots
current_scene_context
current_catalog_revision / 必要的当前目录条目
workspace_semantics
policy_summary            # 只读，不让模型改配置
allowed_recovery_actions
```

只把必要的目录摘要送 R；U 仍按既有规则接收完整当前 OLS 目录。同一用户轮次必须固定目录版本；若后台刷新导致解析器不再使用该快照，应中止并重新核验，不能把旧 asset_key 默默绑定到新资产。

历史和错误信息都作为数据，不是系统指令。错误堆栈不直接给模型；发送白名单错误码、可公开解释和必要现场证据。日志里的“忽略规则”等文字不具有权限。

### 7.2 输出 FailureContextDecision

```json
{
  "protocol_version": "failure_context.v1",
  "decision": "continue_task",
  "source_turn_id": "turn_0007",
  "scope": "failed_step",
  "target_step_id": "step-003",
  "resolved_instruction": "把左侧的苹果放进托盘。",
  "amendments": [
    {
      "subject_role": "source",
      "field": "selection",
      "value": {"relation": "left"},
      "evidence": {"turn_id": "current", "text": "左边的"}
    }
  ],
  "question": null
}
```

上例是示意数据。真正实施要为 selection／quantity／goal／distance／operation 等 amendment 定义有限的 typed union，不接受任意 JSON Patch 路径。

`decision` 仅允许：continue_task、revise_task、new_task、ask_user、cancel_chain。

- continue：补充原未完成语义，不变的字段保留。
- revise：明确修改原目标／数量／方法；每个修改有当前用户证据。
- new_task：独立任务，不自动继续旧失败链。
- ask_user：当前信息不足，只有 question，无可执行 instruction。
- cancel：停止未完成部分，不关闭 Session、不撤销已完成编辑。

模型不得输出：新的 scene_id/object_id、机器人状态、平台授权、计数、commit receipt、成功断言、Commands 或绕过检查标记。

允许模型引用系统提供的角色／step_id／来源 turn_id；必须校验属于当前会话当前链。具体实例绑定由现有 selector 或用户显式 ID 的受控解析完成。

`resolved_instruction` 必须能独立进入正常U，不允许用“同上”“按照刚才的”“原任务那个”代替缺少的动作、对象或目标。已确认实例身份通过服务端验证的绑定／证据传递，不靠在新句子中伪造实例编号。恢复输入的指代焦点以失败步骤的角色证据为准，不能误用之后某个查询更新的 DialogueState 焦点。

### 7.3 输出验证顺序

1. JSON／Schema／版本／来源合法。
2. source_turn_id、step_id 必须在服务端提供的上下文中。
3. 只允许修改尚未完成部分。completed 步骤不可出现在本轮执行计划。
4. amendments 的用户证据必须来自有效原轮或当前原文。字符串确实存在只是必要条件，不是充分授权。
5. R 提议与原草稿对照；continue 只补槽，revise 才可改明确提出的目标、数量或方法。
6. 将通过核验的完整派生指令送原 U，得到原 v3.1 完整语义。
7. 比较 U 结果与服务端接受的草稿／修订，检测遗漏条件、增加步骤、未经授权的 route 或 scene_basis 改变。
8. 原有全部策略、Grounding、几何、Planner、执行前校验继续生效。

对用户明确改成新任务，不用“强制保留原操作”拦死。恢复协议负责标明这个区别，Python 验证它，不通过关键词拼接复原任务。

## 8. 解决运动证据与多轮修订

当前解析和后处理会扫描 instruction 验证方向、距离、original basis 等。直接用“左边的”复验旧任务“向右移动5厘米”会丢失证据；把所有历史拼进去又会产生左右／5厘米与2厘米冲突。

新增内部 `RecoveryEvidence`：

```text
raw_current_user_text
source_turn_ids
base_instruction / validated_base_turn?
effective_instruction                   # R派生，不能作为独立用户授权
accepted_amendments
field_sources                           # 每个当前有效条件来自哪轮
superseded_fields                       # 被用户新解释明确替换的旧值
scene_basis_authorization
scope: failed_step | remaining_steps | new_task
```

接入要求：

- 普通请求完全沿用原 Evidence 路径。
- 恢复请求以派生完整 instruction 提供原 U 所需表达，但在解析与执行前用 RecoveryEvidence 再核验。
- 原“右移5厘米”＋“左边的苹果”保持 motion=right/0.05，新增的是目标筛选，不是把移动方向改成 left。
- 原“右移5厘米”＋“改成2厘米”只替换 distance，方向和对象保持。
- 原目标 tray＋“不是托盘，是篮子”允许修改 destination，但必须检查新容器存在、唯一、能力与几何合规。
- original/current basis、平台配置、工具权限不能因为 R 重写而无证据改变。
- 用户仅换一种表述不代表同意删除颜色、数量、空间或样式条件。
- 断言改色、移动等正常 request 在功能关闭、没有链时，其 Prompt/schema/payload 和路由与基线一致。

## 9. 自动选择优先：一个开关，受限适用范围

### 9.1 开关不是“任何失败都随机”

```text
prefer_auto_resolve = false → 身份不唯一时询问，创建/更新失败链。
prefer_auto_resolve = true  → 先验证是否允许自动选；允许才选，否则照常询问/拒绝。
```

两种模式共享硬约束与安全检查。flag 只改变满足条件后的决策，不改变用户原意。

### 9.2 首版允许与禁止

| 情况 | auto 模式 |
|---|---|
| 两个满足条件的苹果，要求拿一个放入唯一托盘 | 允许自动选择 source |
| 多个同类物体，仅需一个进行非破坏性普通编辑 | 可在白名单操作中自动选，并公开选择 |
| 明确“任意两个”且契约支持两个 | 无放回抽样两个，检查数量与完整计划；超出首版实现则明确不支持 |
| 所有苹果 | 不抽样，仍是完整集合 |
| 最近／最左并列，用户要求唯一极值 | 首版继续澄清，不把没有唯一极值改成随意挑选 |
| 显式 ID 不存在、可验证颜色明确不匹配、带花纹等非颜色条件不满足 | 禁止自动选其他对象；**唯独无可靠颜色标签／覆盖证据**时允许沿用原回退池进行 auto |
| 两个托盘，目标容器不唯一 | 首版询问 destination；不自动挑不同目的地 |
| 参照物、支撑面、工具、平台、资产型号不唯一 | 询问或拒绝 |
| 删除／替换一个未明确对象 | 首版询问；破坏性操作不得默认随机 |
| 问“有几个／有没有／最近是哪个” | 保持查询语义，不抽样改变答案 |
| 真实执行持物、反馈未知、已在运行 | 禁止自动选择后重发动作 |
| 碰撞／超界／不可达／不支持 | 不通过换对象来掩盖原任务失败 |

这是首版安全范围，而不是说以后永远不能扩展。需要拓展 destructive／destination 时应另行明确授权与测试，不能由同一个 true 隐式覆盖。

### 9.3 严格候选前置：当前代码的必要改动

当前 SceneGrounder 会启用 `allow_description_fallback=True`，selector 在贴图无法提供可靠颜色判断时已有描述回退行为。**本轮保留该行为**：先使用可验证的 `MeshRenderer` 实例颜色覆盖／OLS 颜色 tags；有符合颜色的候选优先选择它们，已知颜色冲突的对象不得进入颜色回退池；如果没有可验证的符合颜色候选，可从颜色证据未知的同类对象中回退，并在 auto 模式下选一个。回退不等于证明对象实际具有指定颜色。

新增 `CandidateEvidence`，每个条件至少有 match／mismatch／unknown。除**贴图颜色不可验证**这一既有例外外，明确用户的 ID、数量、空间、款式／非颜色 tags 等硬条件仍必须匹配，不可自动降级。对颜色：known-match 优先；known-mismatch 排除；unknown 允许按原有颜色回退池参与 auto（仅开关开启），记录 `color_evidence_status=unverifiable_fallback` 和 `color_verified=false`，不将其伪报为 match，也不把它误记成普通 `dropped_constraints`。

颜色标签／实例颜色覆盖用于可验证颜色筛选；缺少颜色标签且贴图颜色不可判断时，沿用已有颜色描述回退。其他 tags 的重叠仍只用于同义识别与候选排序，不能证明多个独立非颜色属性同时满足；“同分”也不是语义等价的证明。

不要把新策略直接写成 `random.choice(exc.candidates)`。补充统一候选入口，复用 SceneIndex／既有颜色证据与颜色回退／空间关系计算：先排除**明确颜色冲突**和其他硬约束不满足的对象，颜色未知者才可进入允许的回退随机池；不另造平行几何实现。

### 9.4 可复现的随机选择

建议使用独立局部 PRNG（非全局 random.seed）：

```text
decision_key = SHA256(session_id + logical_task_id + stable_step_id
                      + entity_role + constraint_revision + scene_digest)
候选 = 按scene object id排序的合格实例（含有明确标记的无颜色证据回退候选）
随机选中的IDs持久化到 SelectionDecision
```

- `logical_task_id` 在同一失败链固定；正常任务使用其 turn_id。
- 不用每次重试生成的 request_id 当唯一 seed，否则每次重试都会换目标。
- 同一请求网络重试／Control perception retry／重启：复用已记的选择，而不是重抽。
- 用户明确改目标后，增加 constraint_revision，丢弃不再合法的旧选择，经新校验后才可重选。
- 候选集变化，重新验证当前选择；不得因为旧对象删除就悄悄随机另一个。
- 循环内最多为每个未绑定角色决策一次；不能为求成功逐个试所有苹果。

对外说明：

> 当前启用了自动选择优先，已从两个候选苹果中选择 #17。若本次依据的是颜色证据缺失回退，应明确提示“当前无法验证贴图颜色，未确认它确实为红色”；随后仍需完成原有规划与执行校验。

成功后根据真实结果说明“计划已生成”或“已执行并写回”；不能在抽中对象时就宣布完成。

### 9.5 与视觉接地和现有 overrides 共存

显式 ID／有效用户指代优先，接着是描述和空间硬约束、已有视觉证据；仍无法唯一识别且符合自动选择规则时才选择。auto 不跳过系统原本必须取得的视觉／几何证据。

选出的 overrides 必须绑定逻辑步骤和角色，在所有后续 attempt 中一致。与 DialogueState 的绑定冲突时返回明确冲突，不以 auto 覆盖。Scene Edit、Robot Task 使用共同策略接口；Query 默认不给自动抽样权限。

## 10. 当前多子任务执行的专门设计

### 10.1 现有语义应保留

当前 `_run_steps()` 是“分一个做一个，成功前缀保留”。本计划不改成整句事务，也不承诺原句整体回滚。

例如：

```text
T1：增加两个苹果；增加一个托盘；把苹果放到托盘里；问还剩几个苹果。
step-1 completed（真实新增）
step-2 completed（真实新增）
step-3 clarification（目标苹果不唯一）
step-4 not_run
```

T2“左边的”只恢复 step-3，再按当前权威场景执行 step-4。不得再增加两个苹果与托盘。

### 10.2 StepLedger

拆分完成、任何副作用开始前，持久化整个步骤列表及稳定 step_id：

```text
step_id, original_step_index, task_revision, user_instruction_span
instruction, route_hint
status: planned | processing | committed | executed_confirmed |
        plan_ready_unexecuted | clarification | rejected | unknown | not_run
request_ids[], attempts[], scene_before/after, receipts[], control_run_ids[]
semantic_draft_ref?, confirmed_effects[], holding_state
```

现有 `metrics.steps` 作为展示不能充当唯一恢复存储：需要把具体草稿、场景与副作用证据关联起来。

### 10.3 续接范围

- 默认继续失败步骤，再执行原来 not_run 后缀。
- R 修改失败步骤的方法／目标时，仅替换该步的未完成语义。
- 用户明确修改剩余计划时，可以为剩余步产生新的 task_revision，但不得动成功前缀；后缀依赖必须重验。
- 用户说“算了，换个任务”：取消未完成后缀，保留已完成场景，新任务以当前 Scene 为基线。
- 用户想撤销已成功步骤：作为新的显式编辑请求，走现有编辑安全校验；绝非记忆自动回滚。
- 如果只生成计划而未执行，下游依赖动作不能当作满足；使用现有 plan_not_executed 门控。
- 若抓取成功但放置失败，不能把整个抓放再次运行；先拿到可信持物／状态，按已有支持能力恢复，否则 BLOCKED_RECONCILIATION。

## 11. Web / CLI 接入与结果协议

### 11.1 用户层统一入口

新增 `ConversationOrchestrator`（内部组件，不是第二个执行器）：

- Web `execute()`：在现有 scene/lease/preflight 核验之后、`decomposition()` 之前处理 active chain。
- 无链：使用当前 request.command。
- 有可续接链：R→guard→恢复范围→原 `_run_step/_run_steps`。
- ask/cancel：生成本次结果，finally 正常释放租约。
- 外层汇总后、按既有不确定性处理完成后，调用 `finalize_user_turn()`；不能在每个 app.handle 后提前终结失败链。
- CLI/batch：最外层添加等价 turn wrapper。内部业务调用标明 `origin=internal_step`，避免两次记忆记录。

### 11.2 二值策略入口

首版配置默认值＋可选 `SessionRequest.prefer_auto_resolve` 即可。当前 Schema `extra=forbid`，新增字段必须显式声明与验证，不能靠前端随便附加 JSON。

已存在会话的值应持久化；未提供字段表示保留原值，不回落覆盖。活动失败链冻结 policy_snapshot。切换策略只在空闲时由明确 UI/API 操作完成；活动链期间首版拒绝切换或显式结束旧链再开始，避免绕过五轮限制。Qwen 无权更改策略。

可添加可选 `StartTask.new_task=true` 作为“明确新任务”的可靠入口，默认 false，不新增必填字段。自然语言“算了”仍可由 R 判断，无需新 API 才能取消。

### 11.3 对外兼容字段

```json
{
  "outcome": "clarification_required",
  "reply": "有两个符合条件的苹果，请说明使用哪一个。",
  "executed": false,
  "conversation": {
    "turn_id": "turn_0007",
    "root_failure_turn_id": "turn_0007",
    "chain_state": "waiting_user",
    "failed_user_turns": 1,
    "max_failed_user_turns": 5,
    "continuation_available": true,
    "prefer_auto_resolve": false
  },
  "auto_selection": null,
  "partial_completion": {"completed_steps": [], "remaining_steps": ["step-001"]}
}
```

仅增加可选字段，保持现有 outcome/state/terminal 用法。等待用户时本次 Task 是 terminal；新回复创建新的 TaskID，同一 Session；不要让 Gateway 锁等用户五轮。

耗尽保持兼容 `outcome=failed`，error.code=`conversation_recovery_exhausted`，conversation.chain_state=exhausted。取消可先用现有 answered 结果加 cancellation 事实，不强迫所有旧前端接受新 outcome。

### 11.4 防重放／并发

- turn_id 在入队时与 clientRequestID 一次性关联，重发回同一记录。
- R 输入使用当时冻结的 Scene/chain revision；模型返回后比较 revision，再执行前重新核验 live identity。
- session lock、active owner、Gateway lease 延续现有顺序；不得跨等待用户长持锁。
- 通过复合任务 child request_ids 定位诊断，但绝不把其中每个都记为失败用户轮。
- 不同 Session 的 history、policy、随机决策必须隔离。
- 效果已提交但 TaskStore 写入失败，重启对账已有 receipt，不能触发重做。

## 12. 具体文件修改表

| 文件／模块 | 新增或修改 | 责任 |
|---|---|---|
| `session/conversation_memory.py` | 新增 | Turn、Chain、Draft、Ledger、SelectionDecision 类型与生命周期 |
| `session/conversation_journal.py` | 新增或复用原子记录工具 | 用户轮次索引与幂等终态记录 |
| `session/store.py` | 修改 | 兼容字段、save/restore、引用校验与崩溃对账 |
| `session/brain_session.py` | 修改 | 初始化 memory；保留原执行恢复状态，不与 chain 混用 |
| `models/failure_context.py` | 新增 | R 专用请求/输出 schema、typed amendments |
| `models/qwen_failure_context.py` | 新增 | 额外 Qwen 适配器；独立 stage/诊断，不侵入原 normal Prompt |
| `models/prompt_templates/failure_context_v1.txt` | 新增 | 只读历史整合、失败续接／新任务／取消决策 |
| `semantics/recovery_guard.py` | 新增 | 来源、修改范围、字段证据、U 输出差异和旧步骤防重放 |
| `grounding/ambiguity_policy.py` | 新增 | false/true 二值模式、候选严格验证、固定随机决策 |
| `grounding/scene_grounder.py` | 修改 | 类型化歧义、部分绑定证据和受控自动选择入口 |
| `grounding/semantic_entity_selector.py` | 修改 | 约束证据、严格候选路径、不可把描述回退当确定匹配 |
| `grounding/scene_object_selector.py` | 按需修改 | Scene Edit 复用同策略／overrides；保护查询语义 |
| `application.py` | 修改 | 业务子步骤结果快照、raw/effective分离、RecoveryEvidence；CLI wrapper |
| `pipeline.py` | 小改 | 恢复路径参数与 validator seam，正常理解请求默认不变 |
| `web/service.py` | 修改重点 | 外层 turn、R门控、续接 step ledger、dispatch最终事实、finalizer |
| `web/protocol.py` | 兼容增加可选字段 | 会话策略、新任务提示、状态回包 |
| `ports/execution.py` 或内部适配视图 | 最小兼容扩展 | 执行副作用／仿真重置证据，缺失默认unknown |
| `config.py` / 配置模板 | 修改 | recovery budget、二值模式、开关 |
| `contracts/run_report.py` / artifact writer | 按需修改 | 草稿引用、最终事实、来源与自动选择说明，不混入Commands |
| `brain_tests/` | 新增测试 | 附带 FR 清单，Mock外部接口但用真实仓库类 |

文件名是拟议命名；Codex 应先核对本地后续代码，已有等价模块优先复用。

## 13. 实施阶段与提交建议

### M0：冻结基线并锁定语义

记录 HEAD、配置、Qwen、OLS、Gateway、Control运行模式和当前 pytest/CI。保留已知基线失败，新增测试不得混淆旧失败。确认 public service 的单臂门控和 execution_enabled，不回退到旧仅导出假设。

提交：`test(context): capture current single and composite execution baselines`

### M1：先做用户轮次记忆，不接 Qwen

实现 UserTurn、journal、五轮缓存、SessionState兼容；Web聚合一次、CLI一次；dispatch后落最终记录；重复clientRequestID不重复计数。

验收：三个子步骤＋五次内部重试只生成一条用户轮次；执行失败不会被记为app的plan_ready成功。

提交：`feat(context): persist final user turns with execution evidence`

### M2：失败链与分类器

实现root固定、draft、ledger、五轮计数、waiting/blocked/exhausted等生命周期；未知副作用禁止重放。

验收：首失败=1，第五失败关闭；partial prefix保留；新任务／取消／重启一致。

提交：`feat(context): track bounded failure chains and safe resume scopes`

### M3：独立 R Provider

建立 failure_context.v1、Prompt、输入预算、输出Schema和诊断。此阶段只生成建议，不执行。

验收：正常路径没有R；根轮历史完整；恶意错误文本不能修改权限；R超时／非法输出可控。

提交：`feat(context): add isolated Qwen recovery understanding stage`

### M4：接回原业务链与证据验证

实现 raw/effective/evidence分离，R→U→guard，失败步与后缀续接；不重放completed；不改变原 normal Prompt。

验收：左边的、改成托盘、改成2厘米、数量修改、多轮反悔均保留正确原语义。修改未授权字段不执行。

提交：`feat(context): resume validated remaining work through the existing pipeline`

### M5：二值歧义策略

严格候选＋局部seed＋持久选择＋操作白名单＋对外说明；不改query集合语义。

验收：两苹果一托盘auto成功选择，ask要求补充；**无颜色标签的两个苹果说“红苹果”时可走原回退随机并标注颜色未验证**；有可靠绿色标签而要求红色时不随机该对象；ID不匹配不选；重试同一对象；托盘歧义不猜。

提交：`feat(grounding): add auditable ask-or-auto ambiguity policy`

### M6：Web、执行安全与幂等收口

策略会话配置、outer finalizer、lease释放、未知事务门控、late feedback修订；把现有代码按错误码重试的判断补上环境和副作用证据。

验收：物理partial不重发；可证明仿真scratch丢弃的情况按策略重规划；不同计数不串；保存失败不重复执行。

提交：`fix(context): fence retries and finalize recovery from authoritative results`

### M7：完整回归与分层联调

执行附带验收清单，Python3.11/3.12、wheel、checkout外运行、Mock Qwen/Gateway/Control。真实Qwen先在 execution disabled 或隔离仿真运行，再由团队明确授权真实Control联调。

提交：`test(context): cover failure dialogue, auto selection, restart and partial execution`

不要自动推送，不改生产OLS；不要通过放宽安全断言、全部skip或自动随机更多对象制造通过率。

## 14. 验收指标与发布门槛

至少分开统计：

- 新功能关闭的基线回归结果；功能开启但无失败链的正常请求一致性。
- R/U/Planner/视觉/Control 调用次数与token，用户轮数与内部attempt数。
- clarification → 用户补充 → 正确绑定/正确场景差分/正确Commands 的闭环。
- auto-policy eligible / selected / fallback_to_ask / blocked_by_constraints。
- Root保留率、第五轮封顶、重复提交幂等、重启还原。
- 已完成步骤重放次数必须为0；未知状态自动派发次数必须为0。
- 候选错误／属性被静默丢弃次数必须为0。
- Mock、真实Qwen、仿真Control、物理Control分开报告；未执行not_run。

是否能生成合法计划与是否能实际抓放成功是不同指标。自动选择不承诺IK、可达性、碰撞或抓取一定成功。

## 15. 明确延期项

- RAG、跨Session长期记忆、向量检索。
- 对已确认执行步骤自动撤销／自动反向轨迹。
- 基于失败自动更换机器人／夹爪／相机／Profile。
- 模型自动降级用户明确的数量、样式、区域条件，或把可验证的颜色冲突当作符合要求；颜色**缺乏可靠证据**时允许现有描述回退，但不得宣称贴图颜色已确认。
- 多失败链同时活跃、复杂跨话题挂起／恢复栈。
- Qwen直接生成执行级command_id、世界坐标或运动控制参数。
- 为求成功在所有候选对象／所有轨迹之间无限搜索。

## 16. 设计检查结论

可以实现，而且比把所有历史塞进正常Prompt更符合本轮“避免影响原功能”的目标。真正必要的新组件是：

1. 用户轮次与最终事实记录。
2. 失败链、结构化草稿和剩余步骤账本。
3. 独立只读 Qwen 恢复理解＋结果验证。
4. 询问／受约束自动选择二值策略。

其中最容易漏掉的不是Prompt，而是 **Web外层最终结果、已完成步骤防重放、除不可验证贴图颜色的既有回退外不能削弱用户条件、五轮与现有五次执行重试的分离**。

## 17. 配套文件与证据

源码核对、固定提交链接及旧附件差异见 `04_source_review.md`。执行用例见 `02_acceptance_cases.md` / `03_acceptance_cases.json`，共69项，全部not_run。示例数据见 `05_contract_examples.json`。Codex入口指令见 `06_codex_task.txt`。
