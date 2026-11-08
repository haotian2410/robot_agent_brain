# Platform Rebind Fix 验收报告

基线：`041516434bb34272c3d3b364cb001af2568ef7a4`
当前工作树：基线之上的未提交修复；本报告不包含自动推送。
报告日期：2026-11-08

## 1. 工作树与范围

本次只修改 Brain 源码和新增真实仓库类回归测试；未修改生产 OLS，未调用
Control/IK/MuJoCo/真实机械臂，未删除或覆盖工作树中原有未跟踪资料。

修改文件：

- `src/robot_agent_brain/adapters/ols_robot_assembly.py`
- `src/robot_agent_brain/adapters/mock_scene_platform.py`
- `src/robot_agent_brain/session/brain_session.py`
- `src/robot_agent_brain/application.py`
- `src/robot_agent_brain/web/service.py`
- `brain_tests/test_platform_rebind_regressions.py`

## 2. R1—R12 状态

| 项目 | 状态 | 证据/说明 |
|---|---|---|
| R1 入口权限 | partial-pass | 有效 Agent owner 可在 agent_owned 换装；无 owner/foreign owner 被拒。真实 AgentService→Gateway 联调 not_run。 |
| R2 局部更新/no-op | pass | camera-only/gripper-only 不改 arm；同资产 no-op；专项测试通过。 |
| R3 附件重挂 | pass | arm-only 重新校验唯一 joint/link，保留已确认挂接变换；缺失/歧义拒绝。 |
| R4 单调 ID | pass | Session 高水位传入 adapter，退役 pedestal 不复用；专项回归通过。 |
| R5 限域 diff | pass | Agent/Browser 候选拒绝普通物体、桌面变更和 candidate 伪造平台类别。 |
| R6 状态/事务 | partial-pass | Gateway 已有 lease/journal/readback/unknown 保护并统一 load_scene 接口；ACK/超时等完整服务矩阵本轮未启动真实服务。 |
| R7 能力匹配 | partial-pass | 显式 Profile 验证当前 Scene；无 Profile 只保留严格 UR5e legacy descriptor；Piper/CobotMagic unsupported。完整 Profile 组合矩阵未全覆盖。 |
| R8 首轮候选 | pass | 首轮平台切换内存构造最终候选，一次写入，scene 1/0，original/manifest 取最终候选。真实 Gateway not_run。 |
| R9 多子句语义 | pass-existing | 复用现有 v3 canonical/replay 代码和回归；本轮未改 parser。 |
| R10 CI/wheel | partial-pass | 3.12 全量 923/923；3.11 无 pytest；wheel 构建成功，独立 smoke 因离线依赖 not_run。 |
| R11 live/replay 边界 | pass-existing | 复用现有 v3 canonical 与显式 replay 代码；真实 Qwen not_run。 |
| R12 单臂/相机范围 | partial-pass | 单臂换装边界明确，双臂不静默只换第一条；多相机单目标仍需 Gateway 显式目标字段。 |

## 3. 三条关键调用链

### Agent 当前任务换装

`AgentService.execute` 在获取 TaskStore/browser 绑定和 Gateway lease 后设置不可持久化
owner context；`BrainApplication`→`BrainSession.process_turn` 只有同一 owner
才能在 agent_owned 调用 `rebind_platform_assets`。候选经限域检查后由 Gateway
单次提交，回执/readback 仍由现有 Gateway adapter 处理。

### 浏览器平台快照同步

`accept_browser_scene(change_kind=platform_rebind)` 不把字段当授权；它从 before
的可信平台角色计算 scope，拒绝普通对象/桌面夹带修改，再采用已提交现场，不调用
二次写入。普通 `scene_edit` 保护保持不变。

### 空会话首轮换装

`BrainApplication` 在 session 无 scene 时从模板复制到内存，调用 OLS adapter 构造
最终目标装配，重置新场景 sub-version 为 0，再执行唯一 `initialize_scene`。专项
回归确认平台端只收到一次写入，original/manifest 包含最终 Piper 装配。

## 4. 分层测试

- L1/L2：平台装配、Session、Gateway、Web Service、任务配置专项全部通过。
- Python 3.12：923 collected，923 passed。首次运行因当前 OLS 目录更新导致派生缓存哈希过期；缓存已备份并从当前 OLS 重新生成后复跑通过。未修改 OLS。
- Python 3.11：`not_run`（pytest 未安装）。
- wheel：构建成功；源码目录外 smoke `not_run`（隔离环境缺离线依赖）。
- L3 真实服务/浏览器：`not_run`，本轮没有启动服务。

## 5. 必要证据覆盖

- camera-only：整段 arm SceneObject（含 nonzero now/initial fixture）保持不变。
- gripper-only：arm Driver/pose 保持不变。
- arm preserve gripper：新 arm joint/link 与保留 attachment 重新绑定，旧挂接变换保留。
- pedestal：Piper 删除、切回 UR5e 使用 Session 高水位，不复用退役 ID。
- invalid diff：普通桌面 Transform 和普通对象 MetadataRef 夹带均在写前拒绝。
- first turn：最终候选一次提交，scene version/sub-version 为 1/0。
- ACK/unknown/live 事务：已有 Gateway 回归覆盖；真实网络矩阵本轮 not_run。

## 6. 兼容与部署

公开 Scene v1、original、ID 不复用、single/dual 原有模块、replay 入口未删除。
`ScenePlatformPort.load_scene` 统一为显式 `change_kind` 参数；旧平台替身必须实现
该接口，禁止通过捕获 TypeError 把 platform_rebind 降级成普通编辑。

## 7. 未解决/启动阻塞

1. OLS 1.0.8 的 `ur5e_table_push_pull` 仍有未归一化 Transform 四元数；按要求未改
   生产资产，应由 OLS 修复或提供清洗后的测试包。
2. Python 3.11 pytest、独立 wheel smoke 依赖不可用。
3. 真实 Qwen/Gateway/OLS/浏览器联调未启动，不能宣称 R1/R6/R10/R11/R12 的 L3
   已验收。
4. 多相机“换相机”若需单个目标，需前端/Gateway 传递明确 camera object ID；Brain
   不会根据同名相机猜测。

## 8. 结论

B0—B4 的核心安全修复和真实仓库类回归已完成并通过。B5—B7 的代码与既有回归
保持通过，但由于外部 OLS 数据质量、Python 3.11 依赖、独立 wheel 依赖和真实
服务未运行，本报告将相应项目保留为 partial/not_run，不把它们写成完整联调通过。
