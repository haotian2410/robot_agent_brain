# 失败触发记忆与二值策略：验收规范

基线：`3c568c23752418d9c15321fbd321b3696c8eaef5`。共 **69 个逻辑验收用例**，全部 `not_run`。

用真实仓库的 Application/Session/Pipeline/Editor/Grounder/TaskStore；仅模型网络、Gateway和Control使用可控替身。真实Qwen、独立仿真、物理Control另列结果。所有对象ID和位置均为测试fixture，不是生产资源。

每例证据：user turn_id、root_failure_turn_id、child request_ids、step ledger、R/U调用数、失败轮数、候选与选择、前后scene/digest、commit receipts、execution/environment、最终用户回复。

| 编号 | 类别 | 用例 | 关键期望 | 状态 |
|---|---|---|---|---|
| FR01 | 记忆与最终事实 | 无失败链的正常请求保持旧模型输入 | 原U的Prompt/schema/payload与基线一致；无R调用；只新增一条用户轮次，原业务结果保持 | not_run |
| FR02 | 记忆与最终事实 | 每轮保存用户与系统双向记录 | 分别保存raw_user_text和最终assistant_text；不得只记录用户输入或中间Qwen回复 | not_run |
| FR03 | 记忆与最终事实 | 五轮缓存与完整审计分离 | 最近视图只保留后五轮；已有请求产物不因缓存淘汰删除，当前输入未重复计入history | not_run |
| FR04 | 记忆与最终事实 | 三个子步骤仍为一轮 | child_request_ids有三项，但用户轮次只有一条；final_outcome来自外层汇总 | not_run |
| FR05 | 记忆与最终事实 | 先plan_ready后Control失败 | 不能在app返回plan_ready时清除失败链；最终记录为执行未完成且关联对应child request | not_run |
| FR06 | 记忆与最终事实 | 执行成功后截图失败 | scene_effect=committed保留；后续补截图不重新编辑或执行 | not_run |
| FR07 | 记忆与最终事实 | 旧checkpoint兼容 | 加载为空memory且原Scene/Dialogue/Commands不变；保存再恢复字段一致 | not_run |
| FR08 | 记忆与最终事实 | 晚到回执只修订事实 | 同turn_id upsert事实revision；不新增用户轮次、不再计一次失败 | not_run |
| FR09 | 失败链与轮数 | 首失败轮创建固定根 | root_failure_turn_id等于外层turn_id；failed_user_turns=1，无任务副作用 | not_run |
| FR10 | 失败链与轮数 | 二三轮失败不移动根 | 根ID和原始意图不变；失败计数依次2、3；当前问题可更新 | not_run |
| FR11 | 失败链与轮数 | 第五次失败耗尽 | 首轮包含在总五轮内，第五轮关闭active chain为exhausted；不自动发起第六轮或内部R循环 | not_run |
| FR12 | 失败链与轮数 | 第五轮成功允许完成 | 第五轮可成功，不在收到第五句前直接拒绝；完成后resolved，保留5轮内证据 | not_run |
| FR13 | 失败链与轮数 | 内部Control五次不等于五轮 | MAX_STEP_ATTEMPTS不改变用户轮次计数；本轮全失败后failed_user_turns只加1 | not_run |
| FR14 | 失败链与轮数 | HTTP幂等重发不计轮 | 返回相同Task/turn；无新R/U调用、无新副作用、无新计数 | not_run |
| FR15 | 失败链与轮数 | 局部推进后下一步失败不重置 | root保持原值；本轮整体未完成失败计数加1；step3标completed | not_run |
| FR16 | 失败链与轮数 | 取消不关闭Session | 链cancelled，未执行后缀取消；Session可继续新任务，已完成场景不回滚 | not_run |
| FR17 | 失败链与轮数 | 新任务不错误续接 | R识别new_task，旧链superseded；只处理新增香蕉；若新任务失败则以本轮建新根 | not_run |
| FR18 | 失败链与轮数 | 耗尽后裸补充不得暗开新链 | 不自动恢复已耗尽任务；提示重新提交完整任务；无执行 | not_run |
| FR19 | R理解与语义证据 | 左边的补齐完整抓放 | R→U生成完整原任务；由Python按实际场景选对象；目的地/关系/数量保持；并非只有left筛选片段 | not_run |
| FR20 | R理解与语义证据 | 左右修饰与运动方向区分 | source selection增加left，运动仍right/0.05m；U/运动证据校验不只读取最新短句 | not_run |
| FR21 | R理解与语义证据 | 距离修订优先于旧值 | 仅distance改0.02m；原5cm标superseded，不与新值同时参与校验 | not_run |
| FR22 | R理解与语义证据 | 明确修改目标容器 | 允许revise目标，但重验篮子唯一和几何；不改其余未授权操作 | not_run |
| FR23 | R理解与语义证据 | 用户明确改变任务类型 | 只在明确route修改证据后接受；仍走新route的全套验证 | not_run |
| FR24 | R理解与语义证据 | 第一轮模型澄清无合法Turn | draft.validity=unparsed或partial，不伪造accepted；第二轮重新通过U输出完整合法任务 | not_run |
| FR25 | R理解与语义证据 | R非法JSON或超时 | 没有调用业务U/Control；保存本轮错误，不覆盖原草稿、不进入自循环 | not_run |
| FR26 | R理解与语义证据 | R幻觉改变目标 | guard拒绝无来源的destination修改；零业务写入 | not_run |
| FR27 | R理解与语义证据 | U丢失R已接受的条件 | R→U差异验证阻断；不能仅因U schema合法即提交 | not_run |
| FR28 | R理解与语义证据 | 原始场景授权不得漂移 | 无用户明确原始场景请求则阻断；不衍生新场景或重置平台 | not_run |
| FR29 | R理解与语义证据 | 历史提示注入不改变权限 | 历史作为数据；policy计数/exec权限不可被模型改写；R输出禁止字段触发schema错误 | not_run |
| FR30 | R理解与语义证据 | 预算超限不截断关键条件 | 明确context_budget_exceeded或要求简化；不截掉否定／单位后执行 | not_run |
| FR31 | 自动选择 | 询问优先不随机 | 询问苹果身份，建立root；没有自动实例选择、没有执行 | not_run |
| FR32 | 自动选择 | 自动选择一个合法source | 选择仅来自{17,18}；保存SelectionDecision并公开说明；后续仍通过规划/几何/执行检查 | not_run |
| FR33 | 自动选择 | 已有明确ID不可改选 | 始终选17；auto不覆盖显式ID；ID无效则拒绝而非改18 | not_run |
| FR34 | 自动选择 | 贴图颜色不可验证时沿用回退随机 | 无颜色标签/覆盖证据时auto可从原回退池选一个；保留颜色未验证说明和SelectionDecision | not_run |
| FR35 | 自动选择 | 明确颜色证据冲突时不能乱选 | 有可靠绿色标签/覆盖证据而要求红色时不选该对象；没有其他合格候选则询问/拒绝 | not_run |
| FR36 | 自动选择 | 多个独立tags需全部满足 | 最高tag交集分不等于满足全部条件；无严格匹配则不自动选 | not_run |
| FR37 | 自动选择 | 目的地不唯一不随机 | 首版不自动选destination；询问托盘身份 | not_run |
| FR38 | 自动选择 | 计数查询不抽样 | 结果4而不是1；无选择随机数、无写入 | not_run |
| FR39 | 自动选择 | 所有保持集合 | 目标是3个，不随机一个；不减少用户数量 | not_run |
| FR40 | 自动选择 | 极值并列不任意破局 | 首版保留极值歧义；未启用任意规则不随机 | not_run |
| FR41 | 自动选择 | 破坏性编辑默认不随机 | 首版remove/replace不走自动选择；用户明确编号后才允许 | not_run |
| FR42 | 自动选择 | 重试和重启复用选择 | 不同request_id不重抽目标；保存并恢复同chosen IDs | not_run |
| FR43 | 自动选择 | 候选顺序不影响seed选择 | 候选先canonical排序；相同decision key选择结果相同 | not_run |
| FR44 | 自动选择 | 选择失败不逐个换物体试 | 记录真正失败并交用户修改；不自动改选18掩盖规划问题 | not_run |
| FR45 | 自动选择 | 无放回数量 | 只选2个不同ID，choice记录可复现；不重复抽同一个，不改为全部 | not_run |
| FR46 | 自动选择 | 活动链策略不可被模型修改 | 自然语言不直接修改服务端flag；允许建议UI切换，但不得绕过轮数和安全策略 | not_run |
| FR47 | 部分进度与现场 | 成功前缀不得重放 | 不再新增苹果或托盘；只恢复失败抓放及原not_run后缀 | not_run |
| FR48 | 部分进度与现场 | 后续失败保留累计Ledger | completed step1-3不重放；只改变尚未完成范围 | not_run |
| FR49 | 部分进度与现场 | 取消不是撤销 | 已新增物体保留；仅取消剩余任务并明确告知 | not_run |
| FR50 | 部分进度与现场 | plan-only不当执行 | 原计划不能视为已搬运；保持plan_not_executed门控，不从预期效果推演Scene | not_run |
| FR51 | 部分进度与现场 | 当前Scene变化重新核验 | 旧candidate/选择不直接使用；在当前Scene重新绑定，无法证明一致则澄清 | not_run |
| FR52 | 部分进度与现场 | Scene分支变了 | 不套用旧对象ID；要求明确基线／新任务 | not_run |
| FR53 | 部分进度与现场 | 原对象已删除 | 不能悄悄改选18；给出目标失效说明 | not_run |
| FR54 | 部分进度与现场 | OLS版本在模型调用期间变化 | 执行前发现版本不一致并阻断；不绑定旧key到新资产 | not_run |
| FR55 | 执行与事务 | ACK丢失后禁止续接写入 | BLOCKED_RECONCILIATION；先查询既有transaction，不能新发同编辑 | not_run |
| FR56 | 执行与事务 | 物理部分动作不重放 | 普通对话不能宣告empty或重置机械臂；获取权威状态之前零派发 | not_run |
| FR57 | 执行与事务 | 仿真丢弃有证据才可重规划 | 确认环境和安全证据后R可改目标；重走当前完整校验，不能仅凭错误码放行 | not_run |
| FR58 | 执行与事务 | 旧错误码不证明无动作 | 不按现有五次循环盲目重试；进入blocked并保留日志 | not_run |
| FR59 | 执行与事务 | 成功写回后发布失败 | 保留已提交事实，禁止重做动作；先修发布／checkpoint | not_run |
| FR60 | 执行与事务 | 释放租约失败 | active chain阻断变更；不等待用户期间继续持有逻辑owner或重复加锁执行 | not_run |
| FR61 | 执行与事务 | Control写回PhysicalProperties保持 | 非目标组件逐字/结构保持；无记忆功能引起的组件丢失 | not_run |
| FR62 | Web与交付 | 同Session新TaskID续接 | 新TaskID、新child request，但同root链；不是让首Task持续运行等用户 | not_run |
| FR63 | Web与交付 | 跨Session隔离 | 不能读取另一Session的root/question/选择；外部source_turn_id越界拒绝 | not_run |
| FR64 | Web与交付 | 模型返回期间并发改变chain | CAS检测chain revision冲突；旧R输出不执行 | not_run |
| FR65 | Web与交付 | 记忆关闭快速回退 | 不调用R、不做续接改写；原功能与结果保持，已记录审计不丢失 | not_run |
| FR66 | Web与交付 | 发布策略不被上下文绕过 | 仍capability_unsupported；没有新平台提交 | not_run |
| FR67 | Web与交付 | 公开服务单臂门控保持 | R不能用上下文绕过control_dual_arm_not_ready；底层独立双臂测试不受重写 | not_run |
| FR68 | Web与交付 | 真实Qwen与仿真分层验收 | 真实R/U结果单独记录token/route/IDs；Mock通过不写成真实Control通过 | not_run |
| FR69 | Web与交付 | 独立wheel与版本矩阵 | Python3.11/3.12分别报告；缺资源不掩盖核心测试；wheel内含新Prompt/Schema，源码目录外smoke | not_run |

## 逐例前置条件与输入

### FR01 · 无失败链的正常请求保持旧模型输入
前提：固定Qwen/Scene/目录快照，关闭自动选择
策略：prefer_auto_resolve=false；层级：mock_integration
输入：增加一个苹果
断言：原U的Prompt/schema/payload与基线一致；无R调用；只新增一条用户轮次，原业务结果保持。
结果：not_run

### FR02 · 每轮保存用户与系统双向记录
前提：空会话
策略：prefer_auto_resolve=false；层级：mock_integration
输入：增加苹果 → 有几个苹果
断言：分别保存raw_user_text和最终assistant_text；不得只记录用户输入或中间Qwen回复。
结果：not_run

### FR03 · 五轮缓存与完整审计分离
前提：连续六个独立查询
策略：prefer_auto_resolve=false；层级：mock_integration
输入：查询1 → 查询2 → 查询3 → 查询4 → 查询5 → 查询6
断言：最近视图只保留后五轮；已有请求产物不因缓存淘汰删除，当前输入未重复计入history。
结果：not_run

### FR04 · 三个子步骤仍为一轮
前提：Mock拆分输出三步且全部完成
策略：prefer_auto_resolve=false；层级：mock_integration
输入：增加苹果；改成蓝色；查询颜色
断言：child_request_ids有三项，但用户轮次只有一条；final_outcome来自外层汇总。
结果：not_run

### FR05 · 先plan_ready后Control失败
前提：execution_enabled，Mock Control安全失败
策略：prefer_auto_resolve=false；层级：mock_integration
输入：把苹果放托盘
断言：不能在app返回plan_ready时清除失败链；最终记录为执行未完成且关联对应child request。
结果：not_run

### FR06 · 执行成功后截图失败
前提：Mock提交已确认，渲染失败
策略：prefer_auto_resolve=false；层级：mock_integration
输入：移动苹果
断言：scene_effect=committed保留；后续补截图不重新编辑或执行。
结果：not_run

### FR07 · 旧checkpoint兼容
前提：旧SessionState没有conversation_memory
策略：prefer_auto_resolve=false；层级：unit
输入：程序化构造场景／事件。
断言：加载为空memory且原Scene/Dialogue/Commands不变；保存再恢复字段一致。
结果：not_run

### FR08 · 晚到回执只修订事实
前提：同turn先unknown后权威回执到达
策略：prefer_auto_resolve=false；层级：mock_integration
输入：程序化构造场景／事件。
断言：同turn_id upsert事实revision；不新增用户轮次、不再计一次失败。
结果：not_run

### FR09 · 首失败轮创建固定根
前提：两个候选苹果、唯一托盘
策略：prefer_auto_resolve=false；层级：mock_integration
输入：把苹果放到托盘里
断言：root_failure_turn_id等于外层turn_id；failed_user_turns=1，无任务副作用。
结果：not_run

### FR10 · 二三轮失败不移动根
前提：已有失败链
策略：prefer_auto_resolve=false；层级：mock_integration
输入：那个 → 还是那个
断言：根ID和原始意图不变；失败计数依次2、3；当前问题可更新。
结果：not_run

### FR11 · 第五次失败耗尽
前提：相同未完成任务且始终无唯一目标
策略：prefer_auto_resolve=false；层级：mock_integration
输入：把苹果放托盘 → 那个 → 就那个 → 之前那个 → 你看着办
断言：首轮包含在总五轮内，第五轮关闭active chain为exhausted；不自动发起第六轮或内部R循环。
结果：not_run

### FR12 · 第五轮成功允许完成
前提：前四轮失败，第五轮明确对象
策略：prefer_auto_resolve=false；层级：mock_integration
输入：把苹果放托盘 → 那个 → 前面那个 → 还是那个 → ID 17 的苹果
断言：第五轮可成功，不在收到第五句前直接拒绝；完成后resolved，保留5轮内证据。
结果：not_run

### FR13 · 内部Control五次不等于五轮
前提：隔离仿真且每次重试有安全证据
策略：prefer_auto_resolve=false；层级：mock_integration
输入：抓取苹果
断言：MAX_STEP_ATTEMPTS不改变用户轮次计数；本轮全失败后failed_user_turns只加1。
结果：not_run

### FR14 · HTTP幂等重发不计轮
前提：同session/clientRequestID重复POST
策略：prefer_auto_resolve=false；层级：mock_integration
输入：左边的 → 左边的（相同clientRequestID重发）
断言：返回相同Task/turn；无新R/U调用、无新副作用、无新计数。
结果：not_run

### FR15 · 局部推进后下一步失败不重置
前提：根轮step3歧义，第二轮step3完成但step4失败
策略：prefer_auto_resolve=false；层级：mock_integration
输入：左边的
断言：root保持原值；本轮整体未完成失败计数加1；step3标completed。
结果：not_run

### FR16 · 取消不关闭Session
前提：存在waiting_user链
策略：prefer_auto_resolve=false；层级：mock_integration
输入：算了
断言：链cancelled，未执行后缀取消；Session可继续新任务，已完成场景不回滚。
结果：not_run

### FR17 · 新任务不错误续接
前提：苹果任务未完成
策略：prefer_auto_resolve=false；层级：mock_integration
输入：先不管苹果，新增一个香蕉
断言：R识别new_task，旧链superseded；只处理新增香蕉；若新任务失败则以本轮建新根。
结果：not_run

### FR18 · 耗尽后裸补充不得暗开新链
前提：上链已exhausted
策略：prefer_auto_resolve=false；层级：mock_integration
输入：左边的
断言：不自动恢复已耗尽任务；提示重新提交完整任务；无执行。
结果：not_run

### FR19 · 左边的补齐完整抓放
前提：苹果17/18，托盘19；首轮选苹果歧义
策略：prefer_auto_resolve=false；层级：mock_integration
输入：把苹果放托盘 → 左边的
断言：R→U生成完整原任务；由Python按实际场景选对象；目的地/关系/数量保持；并非只有left筛选片段。
结果：not_run

### FR20 · 左右修饰与运动方向区分
前提：两个苹果，原任务向右5cm被澄清
策略：prefer_auto_resolve=false；层级：mock_integration
输入：把苹果向右移动5厘米 → 左边的苹果
断言：source selection增加left，运动仍right/0.05m；U/运动证据校验不只读取最新短句。
结果：not_run

### FR21 · 距离修订优先于旧值
前提：原任务向右5cm失败且未提交
策略：prefer_auto_resolve=false；层级：mock_integration
输入：改成2厘米
断言：仅distance改0.02m；原5cm标superseded，不与新值同时参与校验。
结果：not_run

### FR22 · 明确修改目标容器
前提：原托盘任务被澄清
策略：prefer_auto_resolve=false；层级：mock_integration
输入：左边的，但放进篮子
断言：允许revise目标，但重验篮子唯一和几何；不改其余未授权操作。
结果：not_run

### FR23 · 用户明确改变任务类型
前提：旧robot_task未完成
策略：prefer_auto_resolve=false；层级：mock_integration
输入：不要机械臂搬了，直接编辑场景放过去
断言：只在明确route修改证据后接受；仍走新route的全套验证。
结果：not_run

### FR24 · 第一轮模型澄清无合法Turn
前提：MockU返回clarification/null
策略：prefer_auto_resolve=false；层级：mock_integration
输入：移动一下 → 把左边苹果向右移动2厘米
断言：draft.validity=unparsed或partial，不伪造accepted；第二轮重新通过U输出完整合法任务。
结果：not_run

### FR25 · R非法JSON或超时
前提：已有waiting_user链
策略：prefer_auto_resolve=false；层级：mock_integration
输入：左边的
断言：没有调用业务U/Control；保存本轮错误，不覆盖原草稿、不进入自循环。
结果：not_run

### FR26 · R幻觉改变目标
前提：原basket，用户只说左边的，MockR改tray
策略：prefer_auto_resolve=false；层级：mock_integration
输入：左边的
断言：guard拒绝无来源的destination修改；零业务写入。
结果：not_run

### FR27 · U丢失R已接受的条件
前提：R明确保留红色，MockU漏color
策略：prefer_auto_resolve=false；层级：mock_integration
输入：左边那个红的
断言：R→U差异验证阻断；不能仅因U schema合法即提交。
结果：not_run

### FR28 · 原始场景授权不得漂移
前提：根任务current，MockR输出original
策略：prefer_auto_resolve=false；层级：mock_integration
输入：左边的
断言：无用户明确原始场景请求则阻断；不衍生新场景或重置平台。
结果：not_run

### FR29 · 历史提示注入不改变权限
前提：历史错误详情带忽略校验文字
策略：prefer_auto_resolve=false；层级：mock_integration
输入：继续
断言：历史作为数据；policy计数/exec权限不可被模型改写；R输出禁止字段触发schema错误。
结果：not_run

### FR30 · 预算超限不截断关键条件
前提：根指令超过上下文预算且含尾部否定
策略：prefer_auto_resolve=false；层级：mock_integration
输入：补充细节
断言：明确context_budget_exceeded或要求简化；不截掉否定／单位后执行。
结果：not_run

### FR31 · 询问优先不随机
前提：两个严格匹配苹果，一个托盘
策略：prefer_auto_resolve=false；层级：mock_integration
输入：把一个苹果放进托盘
断言：询问苹果身份，建立root；没有自动实例选择、没有执行。
结果：not_run

### FR32 · 自动选择一个合法source
前提：苹果17/18满足全部条件，托盘唯一
策略：prefer_auto_resolve=true；层级：mock_integration
输入：把一个苹果放进托盘
断言：选择仅来自{17,18}；保存SelectionDecision并公开说明；后续仍通过规划/几何/执行检查。
结果：not_run

### FR33 · 已有明确ID不可改选
前提：ID17为苹果，ID18另一个苹果
策略：prefer_auto_resolve=true；层级：mock_integration
输入：把17号苹果放进托盘
断言：始终选17；auto不覆盖显式ID；ID无效则拒绝而非改18。
结果：not_run

### FR34 · 贴图颜色不可验证时沿用回退随机
前提：两个苹果均无可靠颜色标签、实例覆盖证据，贴图颜色不可解析；托盘唯一
策略：prefer_auto_resolve=true；层级：mock_integration
输入：把红苹果放进托盘
断言：保持原有颜色描述回退，允许只在两只无颜色证据的苹果中持久化随机选一个；公开提示颜色未验证；不声称它实际为红色，后续仍经过原有规划/执行检查。
结果：not_run

### FR35 · 明确颜色证据冲突时不能乱选
前提：唯一苹果带可靠绿色标签或实例颜色覆盖，用户说红色；没有颜色未知的候选
策略：prefer_auto_resolve=true；层级：mock_integration
输入：把红苹果放进托盘
断言：不将已知绿色苹果视为红色或纳入颜色未知回退池；无合格候选时询问/拒绝，零执行。
结果：not_run

### FR36 · 多个独立tags需全部满足
前提：候选分别只满足花纹或无把手
策略：prefer_auto_resolve=true；层级：mock_integration
输入：把带花纹且无把手的杯子移过去
断言：最高tag交集分不等于满足全部条件；无严格匹配则不自动选。
结果：not_run

### FR37 · 目的地不唯一不随机
前提：一个苹果两个托盘
策略：prefer_auto_resolve=true；层级：mock_integration
输入：把苹果放到托盘
断言：首版不自动选destination；询问托盘身份。
结果：not_run

### FR38 · 计数查询不抽样
前提：四个苹果
策略：prefer_auto_resolve=true；层级：mock_integration
输入：有几个苹果
断言：结果4而不是1；无选择随机数、无写入。
结果：not_run

### FR39 · 所有保持集合
前提：三个苹果
策略：prefer_auto_resolve=true；层级：mock_integration
输入：把所有苹果改成蓝色
断言：目标是3个，不随机一个；不减少用户数量。
结果：not_run

### FR40 · 极值并列不任意破局
前提：两个苹果同为最左
策略：prefer_auto_resolve=true；层级：mock_integration
输入：把最左边苹果放托盘
断言：首版保留极值歧义；未启用任意规则不随机。
结果：not_run

### FR41 · 破坏性编辑默认不随机
前提：两个苹果
策略：prefer_auto_resolve=true；层级：mock_integration
输入：删除一个苹果
断言：首版remove/replace不走自动选择；用户明确编号后才允许。
结果：not_run

### FR42 · 重试和重启复用选择
前提：同logical task/step/constraint revision
策略：prefer_auto_resolve=true；层级：mock_integration
输入：抓苹果（重试）
断言：不同request_id不重抽目标；保存并恢复同chosen IDs。
结果：not_run

### FR43 · 候选顺序不影响seed选择
前提：对同候选倒序枚举
策略：prefer_auto_resolve=true；层级：unit
输入：程序化构造场景／事件。
断言：候选先canonical排序；相同decision key选择结果相同。
结果：not_run

### FR44 · 选择失败不逐个换物体试
前提：选17后规划拒绝
策略：prefer_auto_resolve=true；层级：mock_integration
输入：把一个苹果放托盘
断言：记录真正失败并交用户修改；不自动改选18掩盖规划问题。
结果：not_run

### FR45 · 无放回数量
前提：明确任意两个且契约支持，严格候选四个
策略：prefer_auto_resolve=true；层级：mock_integration
输入：任意两个苹果改蓝
断言：只选2个不同ID，choice记录可复现；不重复抽同一个，不改为全部。
结果：not_run

### FR46 · 活动链策略不可被模型修改
前提：ASK链有效
策略：prefer_auto_resolve=false；层级：mock_integration
输入：改成自动成功就行
断言：自然语言不直接修改服务端flag；允许建议UI切换，但不得绕过轮数和安全策略。
结果：not_run

### FR47 · 成功前缀不得重放
前提：增加苹果成功、增加托盘成功、抓放歧义、查询not_run
策略：prefer_auto_resolve=false；层级：mock_integration
输入：左边的
断言：不再新增苹果或托盘；只恢复失败抓放及原not_run后缀。
结果：not_run

### FR48 · 后续失败保留累计Ledger
前提：上一续接已完成step3，step4安全失败
策略：prefer_auto_resolve=false；层级：mock_integration
输入：改成旁边
断言：completed step1-3不重放；只改变尚未完成范围。
结果：not_run

### FR49 · 取消不是撤销
前提：原复合任务前两步已提交
策略：prefer_auto_resolve=false；层级：mock_integration
输入：算了
断言：已新增物体保留；仅取消剩余任务并明确告知。
结果：not_run

### FR50 · plan-only不当执行
前提：execution_enabled=false，抓放只生成计划，后面还有依赖动作
策略：prefer_auto_resolve=false；层级：mock_integration
输入：继续
断言：原计划不能视为已搬运；保持plan_not_executed门控，不从预期效果推演Scene。
结果：not_run

### FR51 · 当前Scene变化重新核验
前提：用户在两轮之间改变布局
策略：prefer_auto_resolve=false；层级：mock_integration
输入：左边的
断言：旧candidate/选择不直接使用；在当前Scene重新绑定，无法证明一致则澄清。
结果：not_run

### FR52 · Scene分支变了
前提：原root在sceneA，当前为sceneB
策略：prefer_auto_resolve=false；层级：mock_integration
输入：继续刚才的
断言：不套用旧对象ID；要求明确基线／新任务。
结果：not_run

### FR53 · 原对象已删除
前提：自动选中17后17被删除
策略：prefer_auto_resolve=true；层级：mock_integration
输入：继续
断言：不能悄悄改选18；给出目标失效说明。
结果：not_run

### FR54 · OLS版本在模型调用期间变化
前提：R使用目录revA，U/编辑时revB
策略：prefer_auto_resolve=false；层级：mock_integration
输入：继续
断言：执行前发现版本不一致并阻断；不绑定旧key到新资产。
结果：not_run

### FR55 · ACK丢失后禁止续接写入
前提：Gateway commit有可能已落地
策略：prefer_auto_resolve=false；层级：mock_integration
输入：再来一次
断言：BLOCKED_RECONCILIATION；先查询既有transaction，不能新发同编辑。
结果：not_run

### FR56 · 物理部分动作不重放
前提：Control已approach/grasp，place失败且持物未知
策略：prefer_auto_resolve=false；层级：mock_integration
输入：换个位置试试
断言：普通对话不能宣告empty或重置机械臂；获取权威状态之前零派发。
结果：not_run

### FR57 · 仿真丢弃有证据才可重规划
前提：独立simulation确认已清理scratch，Scene未改，无真实动作
策略：prefer_auto_resolve=false；层级：mock_integration
输入：放到托盘旁边
断言：确认环境和安全证据后R可改目标；重走当前完整校验，不能仅凭错误码放行。
结果：not_run

### FR58 · 旧错误码不证明无动作
前提：同RETRYABLE code但execution_environment=unknown
策略：prefer_auto_resolve=false；层级：mock_integration
输入：程序化构造场景／事件。
断言：不按现有五次循环盲目重试；进入blocked并保留日志。
结果：not_run

### FR59 · 成功写回后发布失败
前提：场景commit已确认、产物写入失败
策略：prefer_auto_resolve=false；层级：mock_integration
输入：继续
断言：保留已提交事实，禁止重做动作；先修发布／checkpoint。
结果：not_run

### FR60 · 释放租约失败
前提：业务处理后unlock不明
策略：prefer_auto_resolve=false；层级：mock_integration
输入：继续
断言：active chain阻断变更；不等待用户期间继续持有逻辑owner或重复加锁执行。
结果：not_run

### FR61 · Control写回PhysicalProperties保持
前提：最新Scene含未知扩展及PhysicalProperties
策略：prefer_auto_resolve=false；层级：mock_integration
输入：改苹果颜色后续接
断言：非目标组件逐字/结构保持；无记忆功能引起的组件丢失。
结果：not_run

### FR62 · 同Session新TaskID续接
前提：首Task终结且租约释放
策略：prefer_auto_resolve=false；层级：mock_integration
输入：左边的
断言：新TaskID、新child request，但同root链；不是让首Task持续运行等用户。
结果：not_run

### FR63 · 跨Session隔离
前提：两个用户会话同对象语义
策略：prefer_auto_resolve=false；层级：mock_integration
输入：左边的
断言：不能读取另一Session的root/question/选择；外部source_turn_id越界拒绝。
结果：not_run

### FR64 · 模型返回期间并发改变chain
前提：同时取消或明确开新任务
策略：prefer_auto_resolve=false；层级：mock_integration
输入：左边的
断言：CAS检测chain revision冲突；旧R输出不执行。
结果：not_run

### FR65 · 记忆关闭快速回退
前提：conversation_recovery.enabled=false
策略：prefer_auto_resolve=false；层级：mock_integration
输入：原支持的正常命令
断言：不调用R、不做续接改写；原功能与结果保持，已记录审计不丢失。
结果：not_run

### FR66 · 发布策略不被上下文绕过
前提：平台换装禁用
策略：prefer_auto_resolve=false；层级：mock_integration
输入：把机械臂换Piper → 就按刚才的换
断言：仍capability_unsupported；没有新平台提交。
结果：not_run

### FR67 · 公开服务单臂门控保持
前提：当前public service拒绝双臂
策略：prefer_auto_resolve=false；层级：mock_integration
输入：两只手抓两个苹果 → 左手那个
断言：R不能用上下文绕过control_dual_arm_not_ready；底层独立双臂测试不受重写。
结果：not_run

### FR68 · 真实Qwen与仿真分层验收
前提：固定当前版本组合，先execution disabled
策略：prefer_auto_resolve=false；层级：real_qwen
输入：两苹果一托盘→左边的 → 改成篮子 → 查询和取消
断言：真实R/U结果单独记录token/route/IDs；Mock通过不写成真实Control通过。
结果：not_run

### FR69 · 独立wheel与版本矩阵
前提：干净checkout、最小元数据fixture
策略：prefer_auto_resolve=false；层级：environment
输入：程序化构造场景／事件。
断言：Python3.11/3.12分别报告；缺资源不掩盖核心测试；wheel内含新Prompt/Schema，源码目录外smoke。
结果：not_run
