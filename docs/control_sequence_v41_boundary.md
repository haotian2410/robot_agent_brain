# Control 4.1 对接边界（Brain 侧提案）

本文件描述2026-11-27整改后的规划接口与未来执行前提，不代表生产Control已经实现。
单臂Atomic2.0继续使用现有adapter；双臂4.1不得flatten或交给单臂adapter。

## 当前可用

- 可信运维可配置 `control_skill_contract_path`，或向 BrainApplication/AgentService 注入合同快照。
- 合同包含revision、supported_protocols、统一expansion_level、注册技能参数schema及对象角色。
- `operation_semantics` 由可信Control合同声明：operation种类对应必要技能顺序，及技能参数到canonical operation字段的映射。缺少语义声明、不支持方向/距离/placement时拒绝，不凭技能名称猜测。
- 新schema为 `schemas/commands_sequence_v41.schema.json`；旧Python导入名与commands_dag_v4 schema只是4.1同义入口，不能读取4.0。
- 顶层schema_version必须显式4.1；scene_digest为RFC8785原始Scene的SHA256，64位小写hex。整数不接受bool/float。参数必须标准JSON且数值有限。
- Commands仅保留每臂序列及显式依赖，不输出共享资源、hold、sync或隐式跨臂等待。

## 能力字段

`/health` 与 `/brainCapabilities` 共用以下字段：

| 字段 | 含义 |
|---|---|
| planning_protocols | 已配置规划合同允许的协议；基本2.0，可信4.1合同存在才列4.1 |
| execution_protocols | 当前运行适配可执行的协议；不会因规划合同而列4.1 |
| dual_planning_ready | 4.1规划合同已注入，不代表任何任务都可表达 |
| dual_execution_ready | 当前固定false，等待真实协商与联调 |
| skill_contract_revision | 当前规划快照revision |
| dual_planning_reason / dual_execution_reason | 不可用原因 |

单臂状态独立保留。配置合同revision变化使旧计划失效；相同revision内容变化拒绝。
会话接口返回robot_mode_lock、deployment_candidate、profile_id、robot_setup_revision、
first_robot_mode_turn_id。未锁定时prompt_route为null，不把候选路由当成真实调用。

## 未来执行提案

`contracts/execution_v41.py` 与 `SequenceExecutionPort` 是Brain本地安全设计和测试模型，
不是已确认的Control公网JSON API；没有新增feedback HTTP端点。

执行envelope在Commands之外携带：session、完整权威Scene、实际RobotSetup（左右实例/规划组）、
setup revision、技能合同revision、逐臂已确认状态。不能往4.1 Commands顶层擅加字段。
`prepare_sequence_execution_envelope` 检查已导出且未失效的计划、锁、Scene digest、
setup/合同revision、状态及pending。它不调用Control，也不创建执行授权。

未来adapter必须提供：

1. 真实4.1消费能力、可信技能注册及粒度协商；
2. 独立的execute_sequence/query_sequence传输；
3. 外部调用前持久化pending及幂等request ledger；同ID同内容查询/复用，不同内容冲突；
4. command ID、arm、终态完整覆盖的反馈；成功命令的所有前置依赖必须成功；
5. 逐臂真实holding与最终关节/物体或权威final Scene；缺失一臂不能认定空夹爪；
6. 超时、部分动作、进程崩溃的对账，不整段重放已完成动作；
7. Control内部联合碰撞、等待、感知及持物控制，以及真实仿真联调。

上述未交付前，`mark_dispatched`继续拒绝4.1，无pending、无Control调用。
有计划但无adapter时返回plan_ready/executed=false并保留artifacts与未执行原因。

## 现行2.0执行安全修复

- 外部调用前保存pending；保存失败不调用执行端。
- 仅可信明确无启动/无副作用证据，或可信已销毁隔离工作区，才保留执行前状态继续。
- backend=mujoco、失败策略字符串或“没有Gateway写入”本身均不是销毁/无物理效果证据。
- 部分/未知保留pending、控制报告与execution_reconciliation，禁止自动重放。
- Gateway恢复接口不能单凭清lease解除Control未知；当前缺少真实机器人对账接口时明确拒绝。
- 有限重试仍需允许错误码、次数上限、场景一致及无副作用；缺execution envelope不默认安全。

本轮未修改Control算法、未重启生产服务、未调用真实机器人。
