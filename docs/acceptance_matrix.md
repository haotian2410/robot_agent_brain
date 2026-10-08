# Scene v1 / 只读资产迁移验收 — 2026-10-09

下表是当前实现的验收依据；后面的旧阶段记录仅为历史，颜色、flat Scene、旧 ID 断言已按新协议迁移。

| v3 方案条目 | 当前自动化证据（brain_tests/） |
|---|---|
| 1–4、18–27、70–74 | test_shared_scene_contract：用户 fixture 等值往返、字段严格验证、parent=0、未知组件、joint_limits/Camera/Light/MetadataRef 不变 |
| 5–15、65–69 | test_asset_library：只读索引/metadata/cache、统一 ref 解析、离线 build/validate 前后 tree hash、category sidecar、runtime 不扫描 OBJ |
| 16–17、28–31、42–47、50 | test_component_runtime：Semantic 优先、全局别名/类别、world 父链筛选、整数 concrete ID、颜色/inside 无证据明确失败 |
| 32–35、51–53、78–79 | test_component_editor、test_scene_atomicity：组件 patch、其他组件保留、支持事实刷新、失败版本/编号不变 |
| 48–49、77 | test_component_geometry：实测 cache 的 apple(1)、底部原点模型(4)、XY 偏心工具(16)，完整 AABB 支撑/世界 bounds/布局，无 center-origin 回退 |
| 54–58、66 | test_component_bootstrap、test_library_config：正式引用/config、平台资源缺失失败、world AABB 落桌、组件输出、机器人型号来自 config |
| 59–61 | test_component_session：删后不复用、保存恢复历史、ID=0 持物/焦点、失败不耗编号、marker 无 concrete ID、非法历史拒绝 |
| 62–64 | test_export_roundtrip、test_component_runtime：Commands/Feedback 数字 ID、独立 CommandPlacementTarget、公开 Schema 落盘验证 |
| 75–76 | test_asset_library、test_component_runtime、test_catalog_alias_selection：中文别名/category 候选、无 sidecar 不随机选 |
| 80、第二 Qwen 边界 | test_boundary、test_skill_planning_context、test_skill_planning_end_to_end：不引入执行依赖、不向第二模型投影物理场景 |
| 应用与发布 | test_component_demo_application、scripts/wheel_smoke.py：建场景→导出→编辑→恢复→查询，安装包外独立运行 |
| 真实 Qwen | demo/run_demo.py：新组件协议两组共 6 轮通过，8 次真实 HTTP；不代表 Control 执行 |

全量 pytest、独立 wheel、远程 Python 3.11/3.12 CI 的实际结果和剩余限制见 implementation_report.md。
正式平台 table/robot 资源尚未提供；测试 fixture/demo 不作为正式资源替代。

# 历史：二次 Atomic Skill Planner 验收

基线 `ab434b24e61f3ceca0ea7365b307c821d7e3602b`。四个新测试文件覆盖下表；
真实 Qwen、Control、前端未联调，不以 MockTransport 代替真实验收。

| 附件项 | 测试证据（brain_tests/） |
|---|---|
| A01/A02 | test_skill_planning_end_to_end：recipe/auto 一次 HTTP，qwen 两次；逐阶段 metrics |
| A03–A06 | 同文件 test_nonrobot_never_calls_skill_planner：edit/query/control/clarification |
| B01–B03 | test_skill_planner_router：supports 路由，unsupported stub 调用，holding 不 fallback |
| C | test_skill_planning_context：role/order/goals/外部持物/物理字段投影 |
| D | test_skill_planning_qwen：HTTP schema/stage/temp/model/key、token cap 和预算 |
| E | 同文件：重复/缺失/额外/调序 operation、unknown skill、非法 role/region、空内容、物理字段拒绝 |
| F | test_skill_planner_router：有效放置、重复 locate/approach、无接近抓取/未持有释放/角色交换/缺接触/额外抓取/外部实体 |
| G | 同文件：已持有 source 省略抓取前缀、其他持物 holding_conflict |
| H | test_skill_planning_end_to_end：两响应 HTTP、Commands 模型及公开 Schema、版本和 source_skill_step_id |
| 集合/预算 | 同文件 test_collection_expands_before_second_call_and_keeps_dependencies：2操作/2实例/12命令/640预算 |
| 失败隔离 | 同文件：成功→第二规划失败→控制，旧命令不复用、raw/validation/traceback，首轮失败不提交场景 |
| 网络失败 | 同文件 test_second_call_timeout_keeps_failure_record_and_no_false_scene：两次尝试、失败记录、无场景提交 |
| Search/Replay | router Search 三模式拒绝；e2e 使用真实 ReplayProvider，qwen 缺接口明确报错 |
| CLI/config | e2e：run/chat/batch 参数、环境优先级、cap 边界、planner/prompt/catalog 指纹 |
| 包与 CI | scripts/wheel_smoke.py：独立安装、仓库外 recipe 回放、prompt/catalog 资源、零次第二规划；远程矩阵见报告 |

## 上阶段：Query 收口与场景连续性验收

本轮基线 `ba7678c3581a3ec1b22bbb8fd9656c43c381ceab`。新增专项文件
`brain_tests/test_query_scene_continuity.py`，28 个参数化测试实例；原有测试迁移至 canonical
Query 和显式支撑场景。全量 233 passed；批处理 4/4。提交和远程 CI 见 implementation_report。

| 验收项 | 实际回归证据 |
|---|---|
| Q-C01/C02 | test_q_c01_c02_legacy_fields_are_removed_not_adapted：旧字段单独输入和混入 canonical 均拒绝 |
| Q-C03/Q-A01/A02/A03 | test_q_c03_q_a01_a03_queries_share_alias_category_color_rules：canonical、中文别名、类别别名、红/绿/零匹配；与 Grounder 对照 |
| Query 结构/候选池 | test_query_validates_target_entities_and_selection_scope、test_query_candidate_pool_validates_before_relation_filter |
| D-C01/C02 | test_d_c01_c02_plural_query_focus_then_edit_preserves_entire_set：query→focus→edit 两实例，单数 ambiguous，无实例 ID marker |
| L-Z01/Z02/Z03 | test_l_z01_z03_planar_relative_moves_preserve_support_height：高矮双向、scale.z=2、底部贴桌、单版本 |
| L-Z04 | test_l_z04_relative_add_uses_verified_support_and_own_bottom：相对新增底部高度和支撑 |
| F-S01/S02/S03/S04 | test_f_s01_s04_support_continuity_and_no_guessed_membership：水平/抬升/出界，on 查询和 Grounding、membership 清理 |
| 几何边界 | world_bounds offset AABB/scale/quaternion、yaw footprint/倾斜拒绝、未知原点拒绝、可配置 tolerance、offset support_transform |
| 禁止猜测 | free_space 不当 above、planar caller 必须给 Z、相对新增 unknown support 拒绝、显式默认面回退 |
| 打包/端到端 | scripts/wheel_smoke.py：新 venv、仓库外导入、两轮 robot 导出后集合 query=2；manual_cases 四轮回放 |

真实 Qwen 本轮未运行（8080 拒绝连接）；上述为契约/几何/Replay 验收。

## 上阶段历史验收 — 代码 d427bc5

基线 `266ebcc94fd5b433ebe1000f4d04c7356b747faa`。下表指向实际源码测试，
不是以总测试数替代逐项验收。`brain_tests/` 下测试使用注入 provider/Replay；
没有一项据此声称真实 Qwen 语义准确率或机器人执行成功。

## 行为矩阵

| 附件项 | 证据文件及检查内容 |
|---|---|
| B01 | test_application_artifacts：无场景两苹果，generated、scene+commands、一次理解 |
| B02 | test_acceptance_remaining：苹果/篮子实际 XY 几何不重叠；test_scene_bootstrap：无目标包含属性 |
| B03 | test_scene_bootstrap：香蕉/盒子替代苹果/篮子；目标关系不参与初始约束 |
| B04 | test_scene_bootstrap：两个候选仍选最右一个；test_acceptance_remaining：override 不能缩小候选集绕过筛选 |
| B05 | test_bootstrap_scene_edits：两个苹果和篮子由 add 各创建一次，一个正式版本 |
| B06 | test_bootstrap_scene_edits：旧式参照 add 初始只有苹果，最终一只香蕉且在右侧；新版生命周期也有覆盖 |
| B07 | test_bootstrap_scene_edits、test_same_turn_understanding：add→translate 复用新 ID，没有上一轮焦点也可理解 |
| B08 | test_acceptance_remaining：首轮 translate 相对同种子初始位置恰好 +0.1m，理解一次 |
| B09 | test_application_artifacts：无场景查询 blocked，不生成场景，不报 0 |
| B10 | test_application_artifacts：上传合法空场景返回 0，原字节不变 |
| B11 | test_application_artifacts：已有空场景机器人任务缺对象，不生成替代场景 |
| B12 | test_acceptance_remaining、test_scene_file_codec：损坏 JSON/未知版本/components/未知资产明确失败，无 fallback |
| B13 | test_application_artifacts、test_session_store：同会话复用 ID；跨进程恢复确认版本 |
| B14 | test_config_assets、test_acceptance_remaining：资产缺失、歧义、颜色不支持；缺失时无半场景/commands |
| B15 | test_scene_bootstrap、test_bootstrap_scene_edits：所有对象未知数量拒绝；显式 initial_counts 新增足量 |
| B16 | test_acceptance_remaining、test_layout_and_numeric_edges：工作区过小/相对布局越界有限失败，不减少数量；初始 inside 缺几何显式不支持 |
| B17 | test_scene_bootstrap、test_session_lifecycle：纯删除无场景拒绝；控制无需创建对象 |
| S01 | test_scene_domain、test_bootstrap_scene_edits：有序多编辑完整保留，正式 patch 一次增量 |
| S02 | test_acceptance_remaining：世界/局部旋转四元数不同且数值正确；位置/scale 保留；test_scene_domain 保留平移姿态 |
| S03 | test_edit_prospective_layout：集合新位置互撞拒绝，同时移动可用自身腾出的旧空间 |
| S04 | test_scene_atomicity、test_edit_prospective_layout：后续失败不提交前半段 |
| S05 | test_scene_atomicity：跨 patch 和同 patch retired ID 都不能复活 |
| D01 | test_query_focus：编辑更新焦点；后续单对象 marker 指向同一 ID |
| D02 | test_query_focus：完整集合焦点、集合编辑→plural 再编辑沿用同一组实例，单数则澄清 |
| D03 | test_query_focus：删除焦点后单数指代失效 |
| Q01 | test_query_focus：红/绿苹果颜色过滤正确，不只按名称计数 |
| Q02 | test_query_focus：existence true/false；无匹配返回 0，不与无场景混同 |
| Q03 | test_acceptance_remaining：position/state 来自确认快照且不增加版本 |
| P01 | test_recipe_state、test_plan_validator：grasp→move→release 各一次，独立验证握持前置条件 |
| P02 | test_recipe_state、test_motion_and_commands、test_scene_domain：独立 MOVE 抓放语义、精确距离和 domain 区分 |
| P03 | test_recipe_state、test_semantic_closure：两个 grasp 保留数量后拒绝单夹爪冲突，不改成抓一个 |
| P04 | test_semantic_closure、test_pairwise_collections：红蓝盒顺序及集合逐对展开，不笛卡尔积、不截短 |
| P05 | test_motion_evidence_gate：模型给 0.01 不能替代用户距离依据；Qwen 解析错误保留澄清型错误码 |
| P06 | test_recipe_state：SEARCH 不退化 LOCATE |
| J01 | test_export_roundtrip：两种 MOVE 最终落盘经公开 Schema 校验，canonical wire 不含互斥 null |
| J02 | test_export_roundtrip、test_layout_and_numeric_edges：七类 skill 参数、未知字段、非法/非有限数；非 JSON NaN/Infinity 先由严格解码拒绝 |
| A01 | test_application_artifacts、scripts/wheel_smoke.py：scene/commands ID 和版本匹配 |
| A02 | test_acceptance_remaining、test_artifact_writer：成功后模型失败无旧 commands 链接；失败写盘清理暂存目录 |
| A03 | test_application_artifacts、test_scene_file_codec：输入文件字节不改，新请求目录发布 |
| A04 | test_application_artifacts：平台已提交但磁盘失败保留 committed、不假装回滚 |
| E01 | test_session_lifecycle：连续导出不 pending、不更新 holding/位姿 |
| E02 | test_session_lifecycle、test_session_store：真实 pending 阻止覆盖/新任务/换场景，重启不丢失 |
| E03 | test_session_lifecycle、test_session_store：未 dispatch/过期/重复/未知 ID/不完整成功/非法 holding/旧版本拒绝且状态不改；partial/failed 无快照后 unknown |
| E04 | test_session_store：恢复场景/焦点/pause/sync/pending/反馈来源，不把 corrupt 当新会话 |
| E05 | test_session_store、test_qwen_http、test_batch：独立会话与逐轮日志隔离；同会话锁拒绝并写 |
| H01 | test_qwen_http、test_diagnostics_artifacts：超时/HTTP/空 choices/截断/校验失败各有一条记录，无 fallback，debug 脱敏 |
| C01 | scripts/wheel_smoke.py：d427bc5 在新 venv、仓库外清除 PYTHONPATH 后通过，见 implementation_report 的路径与 wheel hash |
| C02 | test_cli：run 单 JSON，chat 按行 JSON、提示在 stderr |
| C03 | test_batch：独立组继续、依赖 skipped；文档三用例批处理实跑 3/3 |

## 工作项/交付物审查

- T01：pipeline 分段、Session 已解析入口、兼容 run/run_turn/run_task 均保留；无第二次完整理解。
- T02：配置优先级、资产严格加载/复制、别名、demo 标识及包资源已实现。test_configuration_geometry 另证种子/间距、支撑面边界、精确名类别约束与类别别名。
- T03：SceneBootstrapper/BootstrapResult、生成/导入/恢复分流、生命周期、候选数量/布局/关系约束已实现。
- T04：SceneEditResult、单 patch 全量预览、最终 SceneConfig 重验、retired IDs、变换/集合检查已实现。
- T05：临时握持状态、TaskExpander 和独立 PlanValidator 导出门禁已实现，不包含物理能力验证。
- T06：编辑/查询/机器人焦点结果、统一 selector 和删除失效已实现，D02 完整集合编辑补强见上表。
- T07：单参数映射、规范 wire、独立 Schema 落盘验证；公共 CommandsFile 仍为 2.0。
- T08：Application/Report/错误、原生 Codec、LocalScenePlatform、暂存发布和真实提交状态已实现。
- T09：本地严格 JSON checkpoint、配置指纹、POSIX 锁、导出与真实 pending 分离、反馈刷新入口已实现。
- T10：run/chat/batch/schemas、Qwen 注入测试、Replay 显式精确输入、退出码/日志隔离已实现。
- T11：最终代码全量回归 205 项通过；真实服务不可达，记录“未运行”，不把 Replay 当模型验收。
- T12：README、manual_testing、contracts、implementation_report 和 CI wheel 检查均存在；最终代码 wheel 仓库外复验通过。

团队 components/taskStep、真实前端/Control 联调、机器人执行与真实渲染属于明确未验证的外部接口，
不得通过 Brain 本地测试宣称完成。真实 Qwen 可选验收因 8080 不可达未运行，不是模型通过记录。
