# 双臂与原始场景扩展：实现与验收

## 2026-10-18 三项复审修复

基于已推送的 `bfe03b91b512656e7c471a323c85ab77c1b0c884`，只修本轮三个边界，未重构 A–F，未新增技能。
以下为本轮本地验收记录，与上一轮远程 CI 分开；本轮提交及远程 CI 状态以 Git 历史和对应 Actions run 为准。

- `session/store.py::restore`：unknown 或存在 pending 请求时仅恢复内部 SceneManager、实例历史、
  setup、逐臂状态和门禁，不调用 initialize_scene／外部 load_scene。synchronized 且无 pending 保留平台恢复契约。
  pending 继续等待对应执行反馈；unknown 继续要求权威场景恢复，不把旧 checkpoint 当执行后真值。
- `application.py::_load_scene/_capture_original`：平台 ACK、绑定平台清单后保存导入版本并立即 capture_once，
  在理解或编辑前完成；已存在 original 不覆盖。无任务物体的空模板仍不冻结，自动创建仍在整轮成功后冻结。
  任务物体认定仍依赖显式 platform manifest／profile，不猜测未知场景的平台对象。
- `session/brain_session.py::_validate_execution_scene`：普通双臂反馈和异常恢复共用场景 ID／版本、
  实例集合、Profile 资源、完整 RobotDriver 配置及注册组件引用检查。校验失败在平台 I/O 前拒绝，
  保留原场景及 pending／unknown 门禁。恢复另保留其请求来源、最低版本、known 双臂与持物校验。
- 新增 `brain_tests/test_review_recovery_boundaries.py`：14 项，RecordingPlatform 记录实际 load 调用；
  覆盖 unknown／pending 重启零加载、正常恢复、权威恢复后加载、同请求上传＋首次移动、先导入再移动、
  理解失败仍保留导入原件，以及两条确认路径下合法 JSON 中资源／关节／连接关节／自定义引用篡改拒绝。
- 本地 Python 3.11／3.12：各 **631 passed，0 skipped**（含已安装 final_models）；没有运行物理执行。
- 独立 wheel 仓库外安装 smoke **passed**（Replay，未调用真实 Qwen）：
  `/tmp/brain-review-wheel-20261018/robot_agent_brain-0.1.0-py3-none-any.whl`，
  SHA256 `375295033785c212de41acccac7267f151eca3f043d3c5c70c6c791a540f6168`；
  产物 `/tmp/brain-wheel-smoke-d0p3ig_p`。`git diff --check` 通过。

上一轮远程 CI 已核实：[run 39121186272](https://github.com/haotian2410/robot_agent_brain/actions/runs/39121186272)，
`test (3.11)`、`test (3.12)` 均 success。附件复审提供的日志计数为各 **608 passed、1 skipped**，
跳过缺少 final_models 的集成模块；API 核实的是任务状态，日志计数引用附件，不冒充本轮 CI。
上一轮本地 **617 passed** 与其不矛盾，外部集成模块在本地展开为 9 个测试。

## 2026-10-16 审计整改交付（当前结果）

该轮基线为 `f41b66a792ee79ee26f9fb0371033a6ee8b42bdb`，后已提交并推送为 `bfe03b9`，远程 CI 成功，见上。
按 A→B→C→D→E→F 先补失败用例再修复。保留单臂 v2、双臂 v3 单文件以及两个 nullable arm 槽。
没有实现 pour；明确倒水请求即使被模型误转为 grasp 也拒绝。

### 文件、函数与验收矩阵

路径均相对仓库；源码位于 `src/robot_agent_brain/`，测试位于 `brain_tests/`。

| 项目 | 已实现的文件／函数 | 行为证据与限制 |
|---|---|---|
| A-01～A-05、A-07 | `contracts/task_intent.py`、`models/task_understanding.py`：arm_usage；`planning/arm_assignment_resolver.py::resolve_arms`；`pipeline.py`；`planning/task_expander.py::expand` | `test_dual_arm_assignment.py`、原单臂回归；集合展开后按稳定顺序分臂，显式分臂优先，独占同一实例拒绝；不是可达性判断；保留依赖与并行要求 |
| A-06 | `semantics/task_domain_policy.py::classify`；`contracts/turn.py` | `test_domain_robot_semantics.py`；简单显式左／右 translate 保留角色和配置，复杂双臂或 original 语义不足则澄清 |
| B-01～B-06 | `planning/dual_condition_builder.py::{build_conditions,required_invariants,require_condition_coverage}`；`planning/coordinated_scheduler.py::{schedule_stages,validate_stage_order}`；两个 dual Planner 的 `plan`；`coordinated_validator.py::validate` | `test_dual_temporal_constraints.py`、`test_coordinated_validator.py`；四种受限谓词、同前态、必需条件覆盖、持续保持、到位→对臂动作→释放。另测右臂移动后继续放置、左最后释放；Qwen 错序只拒绝，不修复 |
| C-01～C-03 | `planning/dual_capability.py::validate_dual_capability`；`pipeline.py`；`session/brain_session.py::mark_dispatched` | `test_dual_coordinated_capability.py`；最终双非空 stage 才触发协调能力门禁，dispatch 重查当前能力及模板到实例映射，禁止旧映射绕过；串行 v3 可用 |
| D-01～D-04 | `contracts/feedback_v3.py`；`session/brain_session.py::{_apply_dual_feedback,reconcile_scene_and_robot_state}`；`application.py::reconcile_scene_and_robot_state`；`session/store.py` | `test_dual_recovery.py`、`test_dual_delivery.py`；partial→unknown→权威 scene＋双臂 known 恢复；校验请求来源、版本、setup、机器人对象、持物、ID 集合；平台超时仍 unknown；旧计划作废，恢复上下文可重启 |
| E-01～E-04 | `scene/component_reference_registry.py::{remap_component,validate_scene}`；`scene/id_remapper.py::remap_scene`；`scene/robot_setup_manager.py`；`config.py`；`session/brain_session.py` | `test_scene_component_reference_registry.py`；声明无引用或精确 single/list/map_values 路径，nullable、类型检查；未知组件拒绝；切换后清理失效 Dialogue ID；规则进入配置指纹 |
| E-05 | `session/original_scene_store.py::{capture_once,_recover_prepared,load}` | `test_original_scene_recovery.py`；prepare journal＋哈希＋no-replace 双文件＋commit marker/fsync；各中断点恢复。孤儿／损坏文件无可信准备记录时拒绝，不冻结最新场景替代基线 |
| E-06～E-07 | 保留 original/current replace、支撑重建、新实例／scene ID、危险重置门禁 | 原 `test_original_scene_*`、`test_scene_replace.py`；下面 Replay 实际产物验证连续 original 不累计，原 SHA 不变 |
| E4 发布失败 | `session/publication_store.py::{write,read,require_checkpoint}`；`application.py::{_handle,get_publication_status,get_session}` | `test_publication_recovery.py`；持久化 request、scene_commit_status、snapshot_id、publication_status 和 checkpoint revision；发布失败可查事实，旧 checkpoint 不冒充恢复成功 |
| F-01 | `diagnostics.py::BrainResult.robot_setup_was_changed`；`session/brain_session.py::_process_setup_turn`；`application.py::_handle` | `test_robot_config_noop.py`；同 profile unchanged，版本／持物／对话／导出不改变；真实切换仍 committed |
| F-02～F-03 | TXT prompts、`models/task_understanding.py::task_understanding_wire_schema`、`models/qwen_http.py`；demo 校验 | 全量回归、`test_qwen_http.py`、`test_domain_robot_semantics.py`；wire schema 要求模式／保持字段，特定明确语义遗漏运行时拒绝；不保证任意自然语言理解无误 |

### 契约与恢复入口

- 第一阶段 `arm_usage=unspecified|both_required`；设备 dual 不等于必须双臂参与。
- `hold_constraints` 使用 `hold_during_operation|hold_until_operation`，语义实体／操作 ID
  在 Grounding 后变成实例 ID。后者使用 holder_operation、region_entity、placement_region、while_operation；
  release 必须在 peer 完整结束后。多个连续 peer 操作分别声明约束；歧义集合保持、任意 DAG／XYZ 不支持。
- v3 附带绑定后的 typed `hold_constraints`，preconditions/invariants 仅 holding、gripper_empty、located、at_region。
  完整单操作先通过旧 v2 exporter 终态检查，再排阶段并做协同检查；所有效果均 symbolic_only。
- 恢复调用 `BrainApplication.reconcile_scene_and_robot_state(session_id, confirmed_scene=..., confirmed_arms=...,
  source_request_id=..., robot_setup_revision=..., source="external"|"simulated")`。
  接口由可信适配器调用；source 字符串不是认证凭据。无完整权威场景不能靠 confirm_robot_state 恢复。
- 发布故障用 `get_publication_status(session_id, request_id)` 查询。外部平台与本地文件不是全局事务；
  checkpoint 丢失而已提交记录存在时显式 recovery_required，不自动拼造旧状态或重放动作。
  存储设备完全不可写时不能保证写出持久化故障记录。

### 实测结果（本轮）

- Python 3.11／3.12 全量 pytest：各 **617 passed，0 skipped**。本机装有 final_models，含 9 项外部资产集成测试。
- 附件审计记录的基线远程 CI 是各 **545 passed、1 skipped**（外部 final_models 未安装），不是 554；
  后续 `bfe03b9` 远程结果单独记录在上方。现有 CI 仍跑 3.11／3.12 全量与 wheel，外部缺包 skip 保留。
- 独立 wheel 在仓库外 `/tmp` 安装运行，`PYTHONPATH` 已移除，smoke passed（Replay，不是 Qwen）。
  安装模块：`/tmp/brain-audit-wheel-0xAcGU/env/lib/python3.12/site-packages/robot_agent_brain/__init__.py`。
  产物：`/tmp/brain-wheel-smoke-_1c1uzot`。
- wheel：`/tmp/brain-audit-wheel-0xAcGU/robot_agent_brain-0.1.0-py3-none-any.whl`；
  SHA256 `b4864d593b0c9f65c0856757464282f2e26032b4745132a10ef66cd646bf9dee`。
  构建后仅增加测试及本说明，无运行时代码变更。

### 真实 Qwen 与 actual JSON

本机 Qwen3.8-27B-UD-Q4_K_M.gguf，`http://127.0.0.1:8080/v1`，每成功例一次理解＋一次技能规划。
`demo/dual_arm/run_qwen_demo.py::verify_report` 检查实际 scene／commands，而非只看 success：
不同 actor ID、双臂参与、数量、版本、null、符号阶段／持续条件以及原快照。
以下目录内都有实际 `commands.json`、`scene_config.json` 和 debug 模型调用：

| 场景 | `var/dual-arm-audit-qwen/` 下成功请求目录 |
|---|---|
| 双臂抓取／并行槽 | `dual-9c053a6cbe-1/12e71d6012254a8fa7c9e8b9cf43b652/` |
| 左抓放＋右移动 | `dual-9c053a6cbe-2/37da6904532141b185bc6d646b75d58b/` |
| 两苹果集合自动分臂 | `dual-4d026d2f59-3/dad6444037694a1baf8067542f205897/` |
| 左到位保持→右移动释放→左释放 | `dual-f4bb1b7a27-4/3b025044ed784d368b4b33530376c346/` |

早期漏 arm_usage、hold_constraints、setup 及非法并行均曾失败，记录保留在同一产物根目录；
随后加强 wire schema、运行时缺失门禁、TXT 示例后重新单独运行成功，不是一次全成功或自动回退。
这些产物是规划验收，全部 `executed=false`。物理双臂、相机、IK、接触、碰撞均未执行。

纯 Replay（非 Qwen）的 `demo/dual_arm/run_scene_continuity_demo.py` 实际输出：
`var/dual-arm-audit-scenes/a7b5fc1bfb/summary.json`，其 reports 包含每轮绝对 JSON 路径。
初始 apple/banana → original 替换 banana/banana → current 替换 apple/banana → original 再次 banana/banana；
original SHA 始终为 `34cd7de0f12914d05a90de90975ddb2e8c5401b84877cad2ad28453b987b4500`。
运行方法见 [demo README](../demo/dual_arm/README.md)。本地 var 产物不加入模型资产或 wheel。

### 尚需 Control 联调与风险

1. 真实 robot_object_id／planning_group／end_effector／gripper 映射；demo 的 DEMO_ONLY 名称不能投递硬件。
2. v3 单文件 consumer、阶段 barrier、协调启动、typed hold_constraints／preconditions／invariants 的持续监测。
3. grasp/move/release 的真实轨迹、IK、碰撞、稳定接触与终态反馈；Brain 符号通过不证明可执行。
4. 唯一 command ID、逐臂反馈、版本化完整 scene＋known 状态、可信来源认证和平台 ACK／超时约定。
5. 倒水、共同抓取／交接、自由行为树均未实现；等待新版 skill.md，不添加假参数。

用户 `.idea/`、`robot_agent.md`、资产和私有配置未修改、未随 `bfe03b9` 提交。
完整工作区清单与统计见同目录 `dual_arm_audit_worktree.txt`。

---

## 历史实现记录（旧基线；以下数字不是本轮验收）

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
