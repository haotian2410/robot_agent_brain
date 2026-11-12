# B5—B6：能力与语义/协议边界

## 修改与复用

- `_platform_execution_capability()` 不再只看名字和配置字符串：有显式
  RobotProfile 时要求 Profile 能验证当前 Scene；无 Profile 时仅保留已验证的
  UR5e legacy descriptor（实际 UR5e joint sequence/limits 必须匹配）。Piper、
  CobotMagic 等仍可展示/编辑，但规划结果为 unsupported，保持 `executed=false`。
- 既有 v3 canonical parser、asset catalog、replay 入口和多子句方向回归未被
  重写；本轮未扩大 robot task 或 Control 能力。
- 既有 Gateway journal、lease、readback 和 unknown/quarantine 保护继续作为
  外部提交事务的唯一证据源；本轮没有新增第二套事务数据库。

## 结果

专项能力、任务理解、Gateway 和 replay 测试均在 Python 3.12 环境通过；完整
结果及唯一外部资产失败见最终报告。

## 未宣称

本阶段没有接入真实 Qwen、Gateway 8099、OLS 8000、浏览器、Control、IK、
MuJoCo 或真实机械臂。因此真实服务链按模板标记 `not_run`，不能据此宣称
L3 联调验收完成。

## 后续更正（2026-11-11）

上面「Piper、CobotMagic 等规划结果为 unsupported」的结论已作废：那条判据把
UR5 型号名当成了能力白名单，而控制端运行时的 URDF 与关节表完全由场景文件选型。
`_platform_execution_capability()` 现在只要求场景恰好一台 `role=arm` 且其
`RobotDriver` 与 OLS 条目自洽（joint sequence/limits 一致），任何型号的单臂都可
进入规划；`RobotProfile` 缺失不再是单臂的前置条件。双臂依旧必须有显式 Profile。
仍然成立的是外部硬约束：非 UR 关节命名、非 6 个 revolute 关节的单臂能通过门禁，
却会在控制端碰撞检查/关节约束处失败，那属于另一轮处理。同口径见
`docs/webeditor_integration.md`「能力与现场读取」前的门禁说明。
