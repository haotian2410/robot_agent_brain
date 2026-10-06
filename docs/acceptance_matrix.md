# 附件验收追踪（持续核查）

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
| C01 | scripts/wheel_smoke.py：已在 039114a 核心版本新 venv、仓库外通过；最终版本待重建复验 |
| C02 | test_cli：run 单 JSON，chat 按行 JSON、提示在 stderr |
| C03 | test_batch：独立组继续、依赖 skipped；文档三用例批处理实跑 3/3 |

## 工作项/交付物审查

- T01：pipeline 分段、Session 已解析入口、兼容 run/run_turn/run_task 均保留；无第二次完整理解。
- T02：配置优先级、资产严格加载/复制、别名、demo 标识及包资源已实现。几何默认值和类别约束继续审查。
- T03：SceneBootstrapper/BootstrapResult、生成/导入/恢复分流、生命周期、候选数量/布局/关系约束已实现。
- T04：SceneEditResult、单 patch 全量预览、最终 SceneConfig 重验、retired IDs、变换/集合检查已实现。
- T05：临时握持状态、TaskExpander 和独立 PlanValidator 导出门禁已实现，不包含物理能力验证。
- T06：编辑/查询/机器人焦点结果、统一 selector 和删除失效已实现，D02 完整集合编辑补强见上表。
- T07：单参数映射、规范 wire、独立 Schema 落盘验证；公共 CommandsFile 仍为 2.0。
- T08：Application/Report/错误、原生 Codec、LocalScenePlatform、暂存发布和真实提交状态已实现。
- T09：本地严格 JSON checkpoint、配置指纹、POSIX 锁、导出与真实 pending 分离、反馈刷新入口已实现。
- T10：run/chat/batch/schemas、Qwen 注入测试、Replay 显式精确输入、退出码/日志隔离已实现。
- T11：本表持续收集证据；真实服务不可达时记录“未运行”，不把 Replay 当模型验收。
- T12：README、manual_testing、contracts、implementation_report 和 CI wheel 检查均存在；最终报告整合及最终 wheel 仍待完成。

团队 components/taskStep、真实前端/Control 联调、机器人执行与真实渲染属于明确未验证的外部接口，
不得通过 Brain 本地测试宣称完成。真实 Qwen 可选验收因 8080 不可达未运行，不是模型通过记录。
