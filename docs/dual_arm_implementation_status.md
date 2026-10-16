# 双臂与原始场景扩展：实现与验收

基线 a4ed6b8，依据用户提供的双臂与原始场景扩展方案。倒水按最新要求只占位：
等待 Control 新版 skill.md，不新增 pour、倒水区域、液体条件或倒水 recipe。

## 已实现的 Brain 链路

- robot_config；只允许 robot_setup_request + robot_task 这一配置与任务组合。
- profile 显式绑定 arm/实例/group/末端/夹爪；公共平台用角色映射，不根据名字、
  坐标、关节数猜左右臂。配置属于 Session，不修改共享 exporter。
- profile 模板首轮建场景；机器人子图切换；组合任务先规划再平台确认提交。
- 单臂 Commands v2 兼容；双臂 Commands v3 有序阶段与显式 null 槽。
- recipe/Qwen 的抓取、抓放、定距移动；同前态验证、资源/所有权冲突、操作终态检查。
  明确同时不能静默串行，模型错误不回退 recipe。
- SessionState v2、逐臂 known/holding、版本门禁、部分反馈、缺失臂 unknown。
  confirm_robot_state 是版本化外部确认接口，恢复后不凭计划猜空夹爪。
- 不可变 original 快照/manifest/hash；首次成功且有任务物体的场景才冻结。
- current/original replace 使用新资产、新实例 ID，重算支撑几何，不复制旧颜色/scale。
- original 派生使用新 scene_id/version=1，按高水位重映射实例、parent/support/附件/arm。
  未知组件无重映射规则则拒绝；恢复原机器人配置，运行状态等待外部确认。

## 配置接口

BrainConfig.robot_profiles 为 RobotProfileRegistry：

| 字段 | 含义 |
|---|---|
| profiles | profile_id → RobotProfile |
| default_single/default_dual | 对应模式未指定 profile_id 时的注册项 |
| profile.setup | mode/profile_id/arms，每臂明确 robot_object_id、planning_group、end_effector、gripper |
| profile.template | 内嵌 Component Scene v1 模板 |
| robot_object_ids | 可切换的机器人子图，包含所属夹爪和附件 |
| platform_object_ids | 自动创建保留的平台 manifest |
| platform_roles | 如 table → 模板 ID，用于新旧 profile 显式对齐 |
| supported_skills/commands_version | 技能和协议；双臂要求 3.0 |
| coordinated_execution | 部署声明支持协调；明确同时且未注册时拒绝 |
| initial_state | 显式初始状态声明；缺失为 unknown，不是默认空夹爪 |
| default_task_arm | 可选默认任务臂；无指派且无配置时拒绝猜测 |
| v2_robot | 单臂 Control robot 名，不能用 profile_id 冒充 |

scene_robot_profile 绑定导入场景。scene_platform_object_ids 为未绑定 profile 的导入场景
提供平台清单。旧 v1 会话缺少证据时，不补造 profile 或 original。
allow_scene_reset 为外部平台重置授权；LocalScenePlatform 只改元数据，可派生重载。

未注册的旧单臂路径仍兼容；要切换机器人或使用逐臂状态，必须提供真实部署映射。
不能把任意旧场景推断成部署 profile。

## 验收索引

以下测试均位于 brain_tests/；测试成功不等于物理执行成功。

| 原计划项目 | 证据与边界 |
|---|---|
| T01–T02 默认/继承 | 单臂原回归、test_dual_session_pipeline、test_dual_bootstrap |
| T03–T04 切换/组合 | test_robot_config_turns、test_robot_setup_manager；pour 改用 grasp 验证 |
| T05–T07 映射/隔离 | test_robot_profiles_state、test_dual_state_consistency、test_dual_session_pipeline |
| T08–T09 顺序/同时 | test_dual_recipe、test_dual_qwen_planner、test_dual_task_semantics |
| T10–T12 同前态/冲突 | test_coordinated_validator；倒水专属条件未实现 |
| T13–T14 null | test_dual_commands_contract、test_coordinated_validator |
| T15–T16 部分失败/旧配置 | test_dual_delivery、test_dual_state_consistency；未接真实 Control |
| T17–T18 冻结 | test_original_scene_store、test_dual_bootstrap |
| T19–T23 替换/回滚/重复 | test_scene_replace、test_original_scene_application、test_original_scene_commit |
| T24–T25 引用/配置恢复 | test_scene_id_remapper、test_original_scene_commit |
| T26–T29 缺失/失败/恢复/迁移 | test_original_scene_store、test_robot_profiles_state、test_component_session |
| T30 原回归/wheel | 本地 Python 3.11/3.12 与仓库外安装 smoke，见下方 |

## 实际验证记录

- Python 3.11 / 3.12：各 554 passed；后续代码修改需复验。
- wheel SHA256：aa4d81b05f27c0f4b34f4acca36e4753b5d9a9ff2744e42273acd8e1c77d4b75。
- 仓库外安装 /tmp/brain-dual-wheel-NAcfyK/env；smoke 产物 /tmp/brain-wheel-smoke-6b1qdl6_。
- 打包排除已有 .idea 和个人 robot_agent.md；未修改这两个用户文件。
- CI workflow 配置 Python 3.11/3.12；本轮未推送，没有本轮远程 CI 成功记录。

真实 Qwen 为本机 Qwen3.8-27B-UD-Q4_K_M.gguf，每项一次理解＋一次规划：

- 双臂抓取：var/dual-arm-qwen-demo/dual-d7c1a6f7bc-1/f0d7df2f446546619e0cb30c294b8e72/。
- 抓放＋移动：var/dual-arm-qwen-demo/dual-c028bb33d9-2/87a4742637854efd8cb00d90c9439d6f/。
- 早期漏角色/漏释放的失败记录仍保留；失败不提交候选。
- 运行方法见 [双臂 demo](../demo/dual_arm/README.md)。

## 外部验收边界

DEMO_ONLY group/末端/夹爪名称只用于 Brain 规划测试，不能投递真实 Control。
仍需控制端提供真实映射、v3 consumer/协调调度能力及逐臂状态证据。
未运行 MuJoCo、IK、联合碰撞或真实机器人，不宣称真正同步、物理无碰撞或抓取成功。
倒水等待新版技能契约。元数据恢复不代表真实物体瞬移复位。
