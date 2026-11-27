# 布局与双臂验收缺口清单

> 历史审计：共享资源、hold、sync及4.0要求已由双模式序列v2方案取代。
> 当前结果见 `dual_mode_sequence_acceptance.md`；本文件保留历史证据。

核对日期：2026-11-27。依据附件第10–13节和当前工作树，不是完成声明。
详细运行记录见 `layout_dual_arm_implementation_report.md`。

证据等级：**代码**指有针对性的离线测试；**真实U**只证明理解调用；
**浏览器**要求发布场景、几何/身份断言与 Gateway 实际截图一致。
不能从任何一级推导真实机器人执行成功。

## 布局矩阵

| 附件项 | 已有证据 | 尚缺/限制 |
|---|---|---|
| L01 六苹果2×3 | grid-latest-browser-success：输入真实空Scene(0对象)、首次1U、确定性grid、6对象2行3列、version1、截图digest一致 | 单例通过，不推导所有语言变体通过 |
| L02 五苹果圆 | circle-browser-success；确定性圆/半径测试 | 该证据不覆盖所有circle/ring参数组合 |
| L03 苹果香蕉交替 | alternating-browser-success：3+3、实际XY间距0.15m、单次U | 已覆盖该具体例句，非语言全集 |
| L04 篮子周围8苹果 | around-browser-success：真实U、8对象完整圆周、45°间隔、一次版本提交 | 修复前错误front_half响应保留；当前仅一例真实独立调用通过 |
| L05 字母A | text-a-isotropic-browser-success：真实U一次、30荔枝、字体指纹、统一XY尺度、30个对象、版本1、Gateway截图 | 仅字母A/已注册DejaVu；12苹果原请求等比后碰撞拒绝，未替换原请求或减少数量 |
| L06 未声明数量 | missing-count-20261127-01首次0/3，修复Prompt后02真实U为3/3澄清，无Scene/控制副作用 | 仅三例，全面数量来源验证尚缺；隔离8503已刷新，生产服务未切换 |
| L07 支撑面不存在 | test_layout_relative_session及事务引用预检；missing-surface-after真实U明确茶几不存在、场景/digest/original不变、Gateway截图 | 本次在U阶段澄清，未触发Python Resolver的scene_layout_region_unresolved；后者仍只有自动测试证据 |
| L08 容量不足 | exact不减数量；auto创建/追加、ID预留和幂等测试；真实U范围解析3/3；quantity-range-browser-success首次10→5、授权2～10、30cm不变、一次提交、digest匹配截图 | 已验证一条真实自动数量缩减；显式混合资产数量、非循环sequence和重排不会自动改数量 |
| L09 碰撞整轮回滚 | collision-grid-before/after：现有6苹果保持，新增2苹果固定1cm，真实U后scene_layout_collision/geometry_layout；前后raw Scene、version、digest、original完全一致，无Commands，实际Gateway截图 | 覆盖该碰撞用例；页面泛化文案已修复并双版本10项测试通过，文案修复尚未刷新服务 |
| L10 真正空首轮 | 多个独立浏览器会话，bootstrap一次理解 | 数值丢失首次失败保留；20cm修复后真实复测通过 |
| L11 缺机器人源对象 | composite-missing-target证据、无Commands | 证明该用例，不代表Control执行 |
| L12 请求幂等 | 实际HTTP重放修复前400空场景身份错误；修复后200返回原task28；任务总数、会话哈希、original与Gateway事务列表均不变；Web21项回归 | 证明本次首轮布局完成后的重放，不等于所有传输中断场景 |

## 双臂矩阵

| 附件项 | 实际测试入口 | 当前结论 |
|---|---|---|
| D01 显式左右臂 | test_dual_v4_pipeline；test_visual_arm_assignment；dual-semantics-20261127-01真实U左右互换2/2 | 代码：锁定后跳过分臂模型；真实U不等于真实双臂执行 |
| D02 未指定独立任务 | test_visual_arm_assignment | 代码：覆盖/规则fallback；真实可信双臂图像尚缺 |
| D03 持物原臂 | test_dual_v4_holds；test_dual_v4_pipeline | 代码：持物约束与实际状态不被预测状态覆盖 |
| D04 过期视觉 | test_stale_frame_never_calls_assignment_or_uses_fallback | 代码：拒绝过期scene/version/sub-version |
| D05 漏/重复操作 | test_arm_assignment；test_commands_dag_v4_contract | 代码：完整覆盖校验 |
| D06 独立跨臂并行 | test_dag_builder_orders_same_arm_and_keeps_parallel_arms | 代码：DAG无多余跨臂依赖，不等于实际并行执行 |
| D07 同容器资源 | test_dual_v4_resources | 代码：资源窗口不固定左先右后 |
| D08 显式先后 | test_dag_builder_from_ir_keeps_cross_arm_dependency | 代码：跨臂依赖保留 |
| D09 同时开始 | test_explicit_simultaneous_start_only_synchronizes_operation_starts | 代码：仅声明支持时生成sync |
| D10 同臂并发 | test_commands_dag_v4_contract | 代码：同臂依赖与sync冲突拒绝 |
| D11 环/skill/contract | test_commands_dag_v4_contract；test_control_skill_contract | 代码：图、技能参数、revision校验 |
| D12 v3-only拒绝v4 | test_commands_v4_compat；test_dual_v4_pipeline | 代码：无静默flatten或降级 |
| D13 单臂v2 | 两版本全量历史测试和最新wheel replay | 不是物理执行验收 |
| D14 未注册协调技能 | test_unregistered_cooperative_skill_never_exports_or_changes_runtime：recipe/Qwen模拟输出分别覆盖pour、handover、cooperative_grasp，共6例；test_two_ordinary_acquisitions_cannot_disguise_handover：已有持物/本段建立持物两例 | 代码：未注册技能无导出、无状态改变、不fallback；显式hold约束下两次acquire不能冒充handover。尚不证明真实U不会把协调语义误译成两个普通任务，也不代表真实Control验收 |

当前隔离 `/health` 实测：Control execution_disabled，commands仅2.0。
该状态只能证明隔离运行时不执行控制，不能单独证明远端Control的完整能力。
当前实现明确不通过旧v2/v3适配器下发v4；真实v4调度、反馈、并行执行未验收。

2026-11-27 实际消费链审计：当前 Control HEAD 为
`05afa87c53ceb3c9cde06ea223b2e2fc482255ea`。
`robot_agent_link/link/workspace.py:load_task` 明确只接受 `schema_version=2.0`；
`robot_agent_control/control_runtime/__init__.py:connect_robot` 仍构造2.0场景任务。
在 Control 源码中未找到 `commands_dag_v4/skill_contract_revision/dependency_dag`
的声明或消费实现。这个源码检索不代表远端全部能力，但足以说明不能用当前桥接证明v4下发。
Brain `application.py` 已提供显式 `control_skill_contract` 构造参数，校验并深拷贝适配器提供的规划快照；默认不提供，也不从skill.md/Profile/模型回答推断。应用会话v4规划测试使用显式测试合同；现有Web部署尚无实际Control合同发现来源。
`BrainSession.mark_dispatched` 的4.0拒绝分支仍保留。因此正式运行时的合同发现、
协商后dispatch与逐命令反馈适配均为未完成项，不将测试合同当作控制端实际注册。

## 连续性矩阵

| 附件项 | 证据 | 尚缺 |
|---|---|---|
| I01 下一轮新版本绑定 | layout/rearrange/browser与export digest测试 | 双臂实际链路 |
| I02 同轮布局后规划 | composite-digest-capture，单次U+S，导出digest匹配 | 双臂真实U/DAG浏览器导出 |
| I03 布局失败不出Commands | test_composite_scene_robot、reservation Gateway拒绝 | 新版浏览器注入 |
| I04 真实状态后的布局 | test_layout_feedback_continuity（模拟反馈） | 真实Control反馈不在此证据范围 |
| I05 多用户隔离 | test_layout_concurrent_sessions共享Pipeline与Editor、同步屏障并发，成功/失败两种组合；per-session index/context、既有Web隔离测试 | 尚缺真实Gateway/浏览器并发A/B完整联调；离线并发不是端到端证据 |
| I06 重启恢复 | reservations崩溃恢复、original组恢复；浏览器restart-rearrange；test_layout_application_recovery在发布前超时/发布后丢确认两种情况下重新创建应用，unknown持久化、无重发、无ID复用 | 新增应用重建测试使用平台故障模拟；unknown/pending与新布局组合的真实Gateway恢复演练仍缺 |
| I07 布局成功规划失败 | composite-missing-target-capture与离线测试 | 已证明保留布局，不代表所有下游错误覆盖 |

## 发行与交付缺口

- 最新源码全量Python3.12、3.11均1931通过、31跳过；包含应用合同入口、版本不匹配拒绝、幂等HTTP重放、分臂前合同预检和显式圆形尺寸保真。真实U圆/环/弧尺寸样例首次3/3通过，每例一次调用，证据`round-dimensions-20261127-01`，非浏览器或控制执行验收。
- 最新wheel位于`/tmp/brain-layout-release-contract-20261127/dist/robot_agent_brain-0.1.0-py3-none-any.whl`，SHA256为`64d6db7f1974598eaf2de49745a2933f6bbe68fa93476550db33812a39fa7575`。已在独立3.12/3.11环境、仓库外执行wheel_smoke与wheel_understanding_smoke全部通过；包括应用合同深拷贝、圆形参数拒绝、数量范围Compact往返、四份公开schema和资源一致性。结果不包含真实模型或控制调用。
- numeric参数来源已覆盖明确中心/边缘间距及“固定为”等表达，以及半径、圆环内外半径、弧角的明确中英文数值与单位；模式或数值丢失时在ID预留前拒绝。两版本布局/事务/composite相关86项测试通过。任意数量措辞、否定和修订语句等仍缺完整来源验证，不能宣称所有数值都经过校验。
- 运行时字体配置与缺字体部署说明已补充；不随意复制不明许可字体。字母A浏览器单例已通过，复杂文字及其他字体不在该证据范围。
- P0–P7独立提交尚未完成；未自动推送，不能声称提交交付完成。
- 最新32份Web任务的分类和逐调用耗时汇总：`var/layout-dual-audit/aggregate-20261127-03/`；25份服务报告成功、2份几何安全拒绝、2份同步失败、1份运行时校验失败、1份引用/选择失败、1份澄清，读取错误0。保留修复前失败，不把服务报告成功等同独立验收通过；不包含独立U/S smoke，最终跨证据类型总报告仍待补齐。

## 下一轮优先顺序

1. L09真实碰撞回滚已通过；后续覆盖更广泛的碰撞/支撑边界，不把单例当成所有几何情形验收。
2. 核对所有显式数值、auto授权和缺数量行为，扩展来源约束而非静默补值。
3. 新模块A/B并发、Gateway重放/拒绝和重启恢复组合验收。
4. 双臂真实U/可信视觉/DAG导出；控制端能力单独确认，保持版本协商。
5. 两版本全量、最新wheel、证据汇总及阶段提交检查后再做最终完成审计。
