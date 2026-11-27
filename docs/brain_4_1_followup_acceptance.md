# Brain 4.1 后续整改验收

日期：2026-11-27。依据附件《brain_4_1整改实施方案.md》。
基线为 `0faa69a6969a2eb06e53a16f8e04f0ad1baef8f5`，起始工作区干净。
原报告2037通过/31跳过仅作基线，本轮结果单列；没有修改旧测试证据。

## 实施结果

| 项目 | 代码与函数 | 验证及边界 |
|---|---|---|
| B1 生命周期 | BrainSession._accept_result/check_turn/switch_robot_setup；RobotModeLock | 编辑/布局/查询不锁；成功接受机器人计划或可信显式setup才锁；独立first_robot_mode_turn_id；拒绝/澄清不增加接受计数 |
| B2 入口与绑定 | BrainApplication._resolve_imported_profile/accept_browser_scene；RobotProfileRegistry.resolve_scene | CLI/Web共用resolver；保留实际remapped ID；校验接口、driver关节/限位与附件；不凭两台driver猜左右 |
| B2 首次选择 | BrainSession._process_setup_turn/process_initial_robot_turn；RobotSetupManager.prepare | 未锁时可在布局后准备注册配置；规划校验通过再ACK；丢失ACK进入unknown、不发布计划；原物体/布局保留 |
| B2 策略 | ScenePlatformPort.configure_initial_robot_mode；LocalScenePlatform/Gateway adapter | 本地metadata有显式授权；Gateway尚无专门事务，明确拒绝，不伪装scene_edit，不解除v0.2动态切换策略 |
| B2 U与auto | pipeline.understand_turn/understand_composite；TaskIntent.requires_dual | 注入候选/锁上下文；明确both或左右联合不降级；单臂兼容别名保留；auto仅注册recipe或有能力Qwen，无失败降级 |
| B3 保存迁移 | SessionState.migrate_mode_lifecycle/consistent；SessionStore.save/restore | lifecycle version=1；新版null原样保留；仅完整非机器人历史可解除误锁；缺档/归档/unknown保守保留并记录诊断 |
| B3 original与重绑 | BrainSession.derive_original_scene/initialize_scene/bind_imported_profile/rebind_platform_assets | 与当前锁定装配不兼容的original派生在写入前拒绝；锁定后禁止直接导入或重绑；original文件不改 |
| B4 严格协议 | commands_sequence_v41/strict_json/dual_skill_draft；canonical_commands_v41 | 必须显式版本；严格整数、64位小写digest；拒绝嵌套NaN/Inf/非JSON；不删合法技能字段；保留图校验 |
| B4 语义合同 | ControlSkillContract.validate_operation；plan_v4 | 可信operation_semantics声明必要技能及参数映射；拒绝无关技能、漏源对象、方向/距离/placement丢失；不猜物理可行性 |
| B5 能力/交付 | AgentService.planning_capabilities/mode_state/result/dispatch；BrainApplication.refresh_control_contract/_record_cli_turn | 可信快照注入；规划执行分离；逐臂摘要；4.1保留plan_ready与文件、不进2.0 adapter；CLI计划/setup不建失败链 |
| B6 安全准备 | execution_v41提案模型；SequenceExecutionPort；prepare_sequence_execution_envelope | Scene/setup/合同/状态/请求绑定；mock反馈覆盖/依赖/逐臂校验；无生产4.1传输或反馈HTTP接口 |
| B6 当前单臂安全 | AgentService.dispatch/_retry_allowed/resolve_uncertain；SessionState.execution_reconciliation | 调用前持久化pending；保存失败不调用；部分/未知保留证据和阻塞；Gateway没写场景不能证明没动作 |
| B7 文档/schema | README、layout_dual_arm_integration、control_sequence_v41_boundary | 旧same_arm说明退役；新增commands_sequence_v41 schema，旧导入名仅4.1兼容别名 |

无物理profile的兼容single路线仍可用default_single逻辑标识，但只在接受机器人计划时锁定。
它不是RobotProfile或Control能力。未绑定setup而revision非零，只允许有受控rebind历史且
setup revision不小于平台rebind revision；arm_states/profile map必须为空，未删除状态一致性校验。

## 验收矩阵对应

主要新增 `brain_tests/test_brain_41_followup.py`；以下均为fixture/离线或隔离HTTP测试，
不是实际机械臂执行。

| 编号 | 覆盖 |
|---|---|
| M01/M02 | 真正空Scene查询、保存恢复；六苹果布局→再次布局→改色仍未锁 |
| M03/M04/M05 | 布局后显式dual配置/机器人计划；非机器人前缀后普通single计划 |
| M06/M07/M08/M09 | 原模式锁专项补充：setup幂等、失败可重新选、锁定拒绝、dual单手4.1 |
| M10/M11/M12 | Web/CLI真实应用入口、remapped Scene、非法接口、缺少唯一profile/map拒绝；M12不能绑定时明确拒绝的分支 |
| M13 | 新checkpoint未锁、旧误锁可信解除、缺失历史保留、旧计划/待执行恢复；迁移幂等 |
| M14/M15 | original装配不兼容预先拒绝；locked rebind与直调导入拒绝 |
| M16/M17 | 前缀布局成功后机器人失败保留；ACK拒绝/丢失、pending保存失败不下发、receipt幂等不增计数 |
| C01/C02/C03/C04 | 严格JSON/身份；保留现有图与展开回归；同物体/同容器不推导跨臂边、显式末→首 |
| C05 | 合同revision、未注册/无关技能、对象角色缺失或替换、无法表达的语义拒绝 |
| W01/W02 | 可信文件/注入合同、revision变更、能力分层、4.1计划不下发、CLI无假失败链、重启后session列表候选状态 |
| E01/E02/E03 | 4.1拒绝执行且无pending；提案反馈stale/重复/臂错/依赖失败；2.0无副作用重试条件、部分/未知、保存失败 |

## 真实Qwen理解记录

目录：`var/brain-41-followup/real-u-first/` 与 `real-u-final/`。
每例首次各调用一次，无自动重试；保存完整HTTP请求、原始Compact、canonical或拒绝原因、
模型名/指纹、token与耗时。这里只提供fixture profile上下文，不是实际发布布局或真实部署。

第一批7例：4条解析接受；锁定切single正确返回unsupported；2条非法输出：

| 指令 | 首次结果 | 输入/输出token | U调用秒 |
|---|---|---|---|
| 布局后选择fixture_dual并左右抓取 | accepted | 18766/272 | 14.570 |
| 显式fixture_dual setup | accepted | 18754/51 | 1.676 |
| 锁定dual后切single | 正确unsupported | 18776/56 | 1.782 |
| dual仅左臂抓苹果 | accepted | 18773/148 | 4.196 |
| 两臂放入同一个篮子 | 缺placement_target，被Python拒绝 | 18790/345 | 9.439 |
| 左臂完成后右臂再抓 | accepted，显式依赖保留 | 18781/255 | 7.000 |
| 左臂向右推五厘米 | 模型漏运动参数，被拒绝 | 18777/160 | 4.594 |

上述失败未删字段修复、未补成可执行任务，也不算通过。末批是在澄清Prompt中
“首轮”指首个模式决定后的独立复核，结果与首批分别保存，见下方最终记录及JSON。

## 真实外部阻塞与未覆盖

1. Gateway尚未协商“已布局但未锁时首次模式配置”的事务，因此浏览器内single→dual装配转换保持无副作用拒绝。本地候选事务通过不等于Gateway支持。
2. 真实Control4.1消费、左右臂部署身份、执行传输、幂等ledger、逐臂反馈与联合碰撞/等待恢复尚未交付。4.1始终fail-closed，没有调用真实Control/机械臂。
3. 新execution envelope/feedback是Brain侧提案；生产字段与传输仍须双方确认，不是可调用的公网接口。不能用fixture完成这些外部项。
4. original无法安全合并当前装配时选择写入前拒绝；没有扩展复杂动态换平台。
5. 真实U仍有模型输出遗漏，按原始记录报告，不能承诺所有自然语言稳定通过。
6. 当前未知/部分执行重新保持会话核验；只有可信无副作用或已销毁隔离工作区才可清理。后续真实Control对账仍需适配交付。

本轮未改Control IK/碰撞/轨迹算法，未重启生产服务，未调用真实机械臂，未提交或推送。
最终双环境、wheel、HTTP及跳过原因记录如下；过程中的失败日志也保留在同一证据目录。

## 最终源码与安装验证

| 检查 | 结果 | 证据 |
|---|---|---|
| Python3.12全量 | 2087 passed / 31 skipped，40.72秒 | var/brain-41-followup/final-source-312.xml |
| Python3.11全量 | 2087 passed / 31 skipped，34.71秒 | var/brain-41-followup/final-source-311.xml |
| 独立wheel安装/理解smoke | 两版本通过，仓库外执行 | wheel-311.log、wheel-312.log |
| 安装包隔离HTTP | 两版本HTTP200；Qwen/OLS未配置如实显示不可用 | health-311.json、health-312.json |
| 配置实际OLS路径的补充资产测试3.12 | 19 passed，23.08秒，无Control | runtime-assets-312.xml |
| 公开schema与diff检查 | 通过 | generate_layout_schemas.py --check；git diff --check |

证据相对路径均在 `var/brain-41-followup/`。
最终wheel：`/tmp/brain-41-followup-final-source/dist/robot_agent_brain-0.1.0-py3-none-any.whl`。
SHA256：`e9b0485f04f6a449a5c574f6a31916f0403072e92bee52df10539df0bb9ea1f7`。

全量默认环境31项跳过原因：13项要求ROBOT_BRAIN_RUNTIME_CONFIG，3项要求安装指定最新OLS checkout，
15项要求指定OLS1.0.8资产位置。这里是测试环境条件，不能概括为当前运行OLS不可用。
指定现有实际配置后，对前13项所属两个模块补测，3.12共19项通过（包含6项原已运行测试）；
不可把19再全部加到全量通过数。其余指定资产安装路径测试仍未覆盖。

最终Prompt复核仍为每例一次调用、没有重试：

| 用例 | 结果 | 输入/输出token | U秒 |
|---|---|---|---|
| 布局后指定dual | accepted | 18783/274 | 15.394 |
| 显式dual setup | accepted | 18771/51 | 1.634 |
| 锁定后切single | 正确unsupported | 18793/56 | 1.830 |
| dual单手 | accepted | 18790/148 | 4.197 |
| 同篮子独立操作 | 缺placement_target，拒绝 | 18807/345 | 9.372 |
| 明确跨臂先后 | accepted，依赖保留 | 18798/255 | 7.003 |
| 明确方向距离 | 漏运动参数，拒绝 | 18794/160 | 4.621 |

未把两条模型失败补成成功；两批证据分别保留。没有本轮真实双臂Control执行/运动截图。
机器可读汇总：`var/brain-41-followup/report.json`；变更文件清单：`changed-files.txt`。

补充实际OLS配置验证：Python3.11同样19通过，21.75秒，证据为runtime-assets-311.xml。
两版本都未调用Control。当前源代码与独立安装包均已完成验证；最后仅追加验收文档。
产物/会话持久化错误继续使用原publication/checkpoint记录，不能把存储失败解释为
“现场一定没有变化”或自动重放；该边界不以回滚模式锁掩盖已经确认的接受事实。
