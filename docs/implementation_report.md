# Scene v1 / 只读资产迁移报告 — 2026-10-09

基线：`a60a17b4c93e898aec65073e4d44516295761040`。
最终 commit SHA 在交付消息中提供，避免报告自引用自己的 commit。
本节为当前状态；后面旧协议/旧验收数量仅为历史。

## v3 最终验收项目

1. 提交：完成本地验收后提交，远程结果记录在本节后续验收栏。
2. Pydantic：src/robot_agent_brain/contracts/scene.py；CLI `robot-brain schemas --output-dir var/schemas`
   导出 scene_config.schema.json、commands.schema.json、run_report.schema.json，Schema 与运行时模型同源。
3. 用户 fixture：brain_tests/fixtures/shared_scene_v1.json 与用户提供 scene_example (2).json 的 JSON
   内容一致；顶层/对象/组件字段不新增 flat 字段，严格契约及 round-trip 测试通过。
4. MetadataRef.path 原样往返，含样例 `<id>`；占位只准结构保留，不可资源 resolve。
5. AssetLibraryPort 的 resolve/find_by_name/find_by_category 统一资源入口；Local adapter 只读
   index/metadata/外置 cache/可选 sidecar，严格解析 `$LIBRARY_SERVER/<规范整数>`，不接受本地路径。
6. scripts/build_asset_geometry_cache.py 离线扫描 OBJ 顶点生成完整 local min/max + dimensions；
   scripts/validate_asset_geometry_cache.py 对照重算。运行时不扫描 OBJ/MTL/PNG。
7. grasp_objects 21 个资产前后树 SHA256 均为
   `7dc29ed669cbb94c2a3ff8a3c128bf37bc8ee2f6ed0250528b5fdfaf28866e01`，确认零修改。
   资产包及压缩包不进入 Git/wheel，派生 cache/categories/aliases 在 config/。
8. 已有场景 category 来自 Semantic；无场景 category-only 依可选 sidecar 筛选，
   未配返回 asset_category_unavailable，多候选仍需消歧，不随机选取、不改资产 metadata。
9. parent=null 为 world，非 null 为 parent-local；parent=0 保留。空间推理使用完整 world affine，
   编辑逆变换写回局部 TRS，无法表达的剪切编辑拒绝。
10. RobotDriver joint_sequence/joint_limits 精确保留，编辑其他对象不变；不送入第二模型。
11. 未知 JSON-safe 组件 round-trip 原样保留；已知组件严格验证，Camera/Light/MeshRenderer 不丢失。
12. Scene、Grounded、Commands target/reference、Feedback、Camera、Dialogue 数字 ID 全链路迁移；
    Task semantic ID 仍为 string；独立 ResolvedSelectionRelation/CommandPlacementTarget 避免混用。
13. old flat Scene runtime 已移除。内部 SessionState 保存 seen/next，不进入 Scene；
    保存恢复后禁止复用删除编号。旧 flat 场景/旧 checkpoint 需显式外部转换或新建会话。
14. full pytest：**425 passed in 5.35s**（Python 3.12），无 skip/xfail；git diff --check 通过。
15. 仓库外 wheel：新 venv 真正从 site-packages 导入，清除 PYTHONPATH，smoke 已通过。
16. Python 3.11/3.12 CI：最终提交后实际核对，不以工作流存在代替通过。
17. real_qwen_tested=true：新协议 demo 6/6，8 次真实 HTTP，详见 demo/VALIDATION.md。
    使用 demo 元数据，模型真实；没有伪响应/Replay 替代，没有新增模型调用或改变第二阶段边界。
18. Simulation/Frontend/Control 未实际联调；robot_executed=false，不新增模拟执行、MuJoCo、IK、轨迹依赖。
19. 剩余限制如下，不把单元测试当正式平台可执行性证明。

## 剩余限制与部署输入

- 当前抓取库 1–21 不包含正式桌子/机器人资源。default_table_metadata_ref、default_robot_metadata_ref、
  default_robot_driver 必须由团队提供，并由 adapter 解析到完整资源/几何。当前 Local adapter 仅支持
  配置 index 内资源，外部平台库需部署端提供完整库或同 Port 的适配器；不能只填不存在的编号。
  config/local_asset_library.json 留 null 是明确缺配置，不会悄悄回退 demo。
- 内置 demo 平台为合成 demo_joint 和几何，不是真实 UR5e 配置。真实 Qwen demo 不是正式资产联调。
- Scene 没有 color/inside/interaction_state；缺可靠证据明确失败，不猜显示名、不添加旧 properties。
- 支撑推导是水平朝上 surface 的 AABB 几何证据，不是接触/稳定性物理；移动支撑物不会执行物理跟随。
  父节点运动会按 scene graph 改变子节点世界变换，但不求解支撑动力学，外部执行必须返回确认快照。
- Commands v2 已改 concrete integer IDs，但 taskStep/旧 Control 适配没有实施；plan success 不等于执行成功。
- 真实 Qwen 仅覆盖两个多轮样例，不是任意中文任务准确率保证；正式 camera 渲染与视觉定位未测试。

## 最终重验

实际最终 wheel：`/tmp/brain-shared-wheel-ckQP2d/final/robot_agent_brain-0.1.0-py3-none-any.whl`。
SHA256：`5b7de479b269a79280c01b6da7d943afddfee9432ed810729a0ce536084b3510`。
venv：`/tmp/brain-shared-wheel-ckQP2d/venv`；从 /tmp 清除 PYTHONPATH 执行 wheel_smoke.py，
实际导入该 venv/site-packages，**passed**；产物 `/tmp/brain-wheel-smoke-rgwqix8_`。
检查 wheel 95 个条目，不含原资产 OBJ/MTL/PNG/7z；JSON Schema 从同一安装包成功导出。
初次尝试 --no-build-isolation 因本机无 hatchling 失败，改用标准隔离构建成功；未安装项目运行时新依赖。
原始 fixture JSON 与仓库 fixture 逐值比较相等；21 个 cache 对照 OBJ 重算和资产树哈希复核通过。
真实 demo 结果根目录：`demo/results/shared-scene-v1/20261009-001313-f6f762/`（Git 忽略）。
远程 Python 3.11/3.12 CI 待提交后核对，下方补充实际链接和状态。

---

# 历史：Optional 第二阶段 Qwen Atomic Skill Planner — 2026-10-07

基线：`ab434b24e61f3ceca0ea7365b307c821d7e3602b`。
验收代码提交：`fd4d245685341bb4f82202a669ee56775db3ccc6`，已实际 push 到 main。
最终文档提交 SHA 以 Git HEAD/交付消息为准，
不在提交中写不可实现的自身 SHA。

## 实现与边界

- `planner=recipe|qwen|auto`，默认 recipe；run/chat/batch 和同名环境/JSON 配置均支持。
- recipe：仅确定性规划；qwen：已接受 robot_task 在 grounding/展开/距离解析后调用第二模型。
- auto：仅依据 supports=false 选 Qwen，recipe 前置条件失败不 fallback；Qwen 失败也不回退。
- supports 集合：locate/move/grasp/release/pick_and_place/press/open/close。所有现有可执行
  类型已有 recipe，所以 auto 当前通常仍是 recipe；未来新能力仍须同步第一阶段契约和校验器。
- Search：supports=false，但 Registry 没有 Search，所有模式提前 capability_unsupported。
  **Search wire 未接入**，未扩展 generic/other TaskType。
- 第二次只组合 locate/move/grasp/release/press/pull/push。Registry 记录 signature、描述、
  前置条件、效果、region 和可见性，不读 Control SKILL.md，不含高层 recipe。
- PlanValidator 共用：从固定 Counter/步数改为 located/reached/held 与语义效果；重复定位和
  合法接近可通过；角色、覆盖、顺序、依赖、持物、接触、放置和最终状态仍严格验证。
  重复位移会翻倍距离，仍拒绝；Exporter 再次走同一门禁。
- 无场景首轮机器人任务先规划再加载候选场景，第二规划失败不留下已提交场景。
  既有场景失败不变、无新 commands、无旧 commands 链接，executed=false。
- 冻结 Query/SceneEditPlan 和 Commands v2 wire 未改；未加入 MuJoCo/IK/Control 依赖。

## Schema / payload / 诊断

`PlannerContext`：instruction、确定性 semantic_summary、operations、entities、goals、initial_state。
operations 只含 id/type/semantic_intent/role_bindings/valid_roles/depends_on/placement_target/
motion_direction；entities 只含语义 id/name/category；goals 为 relation/subject/reference；
initial_state 为 held_entity/gripper_occupied。外部持物映射 null/true。无物理快照或解析后距离字段。

`SkillPlanLLMOutput`：operations[]（id、非空且≤300字符 intent、非空 steps[]）；steps 只含
skill 枚举、target_role、reference_role、region。严格拒绝 extra；操作 ID 唯一且序列完全相同。
Python 检查当前操作角色/注册技能/region，再绑定 TaskEntity、生成 step-N；无 silent repair。
详细 Schema 字段与完整 JSON 示例见 contracts.md。

HTTP 第二请求复用相同 URL/model/key/timeout，stage=skill_planning，temperature=0，
默认 JSON Schema strict。user payload 为 context 的 6 项加 skills；system prompt 从 txt 载入。
completion budget=min(cap,384+128×max(展开操作数,1))，cap 默认1024、合法128–4096。
HTTP 仍记录 usage/finish_reason/耗时/错误/原文，不自动重试或切换模型。

metrics：understanding_calls、vision_calls、skill_planning_calls、planner_requested、planner_used、
model_calls。debug：planner_context.json、planner_skill_catalog.txt、raw_skill_plan.json、
normalized_skill_plan.json、skill_plan_validation.json，以及 model_calls/traceback。
没有响应时 raw 标记 available=false；未完成的阶段不伪造 normalized。配置指纹含 mode/cap/
prompt/catalog 哈希；原始响应保持 debug-only，按已有规则脱敏。

## 本地实测

Python 3.12：`python -m pytest -q brain_tests -o addopts=''` → **327 passed**。
新增四个专项文件，共 **78 个参数化测试实例**；原有 249 项保持通过。`git diff --check` 通过。
逐项 A–H、Replay、Search、失败隔离和集合展开证据见 acceptance_matrix.md。

MockTransport 实际发出的 HTTP 请求计数（不是实际 Qwen 推理）：

| 模式/轮次 | 理解 | 技能规划 | 无视觉时总调用 |
|---|---:|---:|---:|
| recipe robot_task | 1 | 0 | 1 |
| auto supported robot_task | 1 | 0 | 1 |
| qwen robot_task | 1 | 1 | 2 |
| edit/query/control/clarification | 1 | 0 | 1 |

测试还检查 2 个苹果先展开为 2 个 operation，第二预算为640，导出12条命令；失败调用仍记录，
已持有 source 可以用3步放置，额外抓取/重复位移/缺接触/错误角色被拒绝。

独立 wheel：`/tmp/brain-planner-wheel-Gfjki1jp/wheels/robot_agent_brain-0.1.0-py3-none-any.whl`。
SHA256：`16984a5f10f2fe4ba5993f5d784e86d6c272e8bb8bd8c93f6e89f4b5cb745fdf`。
新 venv：`/tmp/brain-planner-wheel-Gfjki1jp/env`；从 /tmp 清除 PYTHONPATH 运行
scripts/wheel_smoke.py → **passed**。实际导入 site-packages；保持 recipe 回放，不伪造二次 Qwen。
验证包内两类 prompt、Registry、默认配置、Schema、命令和查询/编辑；产物：
`/tmp/brain-wheel-smoke-_ghpkz5q`。临时 wheel/产物不提交到仓库。

## GitHub Actions 实测

[本轮代码 CI](https://github.com/haotian2410/robot_agent_brain/actions/runs/37621201197)
已通过 GitHub API 核对 head_sha 与上述代码提交一致：

- [Python 3.11](https://github.com/haotian2410/robot_agent_brain/actions/runs/37621201197/job/112791627968)：completed / success。
- [Python 3.12](https://github.com/haotian2410/robot_agent_brain/actions/runs/37621201197/job/112791627687)：completed / success。

两项均包括全量 pytest、wheel 打包、新 venv 安装、仓库外 smoke；不是仅声明工作流存在。
本地及 remote main 的代码 SHA 通过 git ls-remote 对照，后续只提交此验收证据。

## 真实服务与限制

`real_qwen_tested=false`。本轮访问 `http://127.0.0.1:8080/v1/models` 连接被拒绝；
没有启动或重配模型，没有把 Replay/Mock 当成真实模型成功记录。真实服务恢复后需按
manual_testing.md 做 recipe/qwen 对照，并记录 token、延迟、有效率和命令数。

Control/Frontend **未联调**；真实渲染、MJCF、机器人执行均未验收。Brain 原生场景仍是 JSON。
第二 planner 不能修正第一阶段错误数量/实体/目标，也不能创造第一阶段无法表达的新高层动作。
按既有 domain policy，纯“苹果右移五厘米”是 scene_edit，第二调用为0；机器人 MOVE 用明确
抓起→移动→放下链验证。当前 demo 资产没有柜门/按钮，真实复合任务需要部署方提供元数据。
视觉可选调用独立计数；不宣称任意场景都恰好两次模型调用。

## 修改文件

```text
README.md
docs/acceptance_matrix.md
docs/contracts.md
docs/manual_testing.md
docs/implementation_report.md
brain_tests/test_skill_planning_context.py
brain_tests/test_skill_planning_qwen.py
brain_tests/test_skill_planner_router.py
brain_tests/test_skill_planning_end_to_end.py
scripts/wheel_smoke.py
src/robot_agent_brain/config.py
src/robot_agent_brain/resources/config.json
src/robot_agent_brain/cli.py
src/robot_agent_brain/skills/__init__.py
src/robot_agent_brain/skills/registry.py
src/robot_agent_brain/planning/context_builder.py
src/robot_agent_brain/planning/skill_planner_router.py
src/robot_agent_brain/planning/recipe_planner.py
src/robot_agent_brain/planning/plan_validator.py
src/robot_agent_brain/models/skill_planning.py
src/robot_agent_brain/models/qwen_http.py
src/robot_agent_brain/models/prompt_templates/skill_planning_v2.txt
src/robot_agent_brain/pipeline.py
src/robot_agent_brain/application.py
src/robot_agent_brain/session/brain_session.py
src/robot_agent_brain/diagnostics.py
src/robot_agent_brain/adapters/artifact_writer.py
```

---

# 历史：Query 契约收口与场景连续性返修报告 — 2026-10-07

## 版本与范围

基线：`ba7678c3581a3ec1b22bbb8fd9656c43c381ceab`。
验收代码提交：`e59b051f1cf8a8baa295952b53334f503d47295e`。
该提交已实际 push 到 GitHub main，已用 ls-remote 对照确认，不是仅本地 commit。
本报告的后续提交仅整理验收证据；最终文档提交 SHA 以 Git HEAD 和交付消息为准，
避免把包含自身 SHA 的不可实现自引用写进文件。

保留 Application / Pipeline / Session / Bootstrapper / Planner / Commands v2。
未增加 MuJoCo、IK、轨迹规划或物理引擎依赖。上一阶段报告保存在基线提交历史中。

## 本轮修改

- Query 只允许 query_type + entities + relations + target，严格校验实体引用和 selection scope。
- REMOVED：SceneQueryIntent 顶层 semantic_name、category、referent_scene_object_id；无 Legacy Adapter。
- REMOVED：QueryEngine 旧字符串筛选路径、Provider referent ID 注入、dialogue_scene_object_id marker。
- QueryResult 不再包含冗余 semantic_name，保留具体 object_ids 和对应结果。
- SemanticEntitySelector 统一 Query / Robot Grounding / Scene Edit 的候选和关系筛选。
  Query count/existence 允许 0/N；robot 仍校验唯一性/集合数量；candidate_pool 先校验池数量。
- 集合语义 marker 不携带实例 ID，Python bindings 保留全部实例；集合后的单数指代澄清。
- 水平相对布局保留目标 Z；新增对象通过已验证支撑或明确默认桌面计算自身底部高度。
- AABB 优先，支持 scale、xyzw 旋转和明确 center-origin 元数据。free_space 不再当作 above。
- Transform 清除旧空间事实；Editor 在 prospective scene 上追加可证明的 support/on，
  原子提交一个版本。抬升/出界不恢复 support，不猜 container_membership。
- Prompt、Replay、批处理、wheel smoke、旧测试和使用文档同步迁移。

## 实测验收

本地 Python 3.12：

```bash
/home/cscvlab/miniconda3/envs/robot_agent_integ/bin/python -m pytest -q brain_tests -o addopts=''
git diff --check
```

结果：**233 passed**，diff 无错误。基线 205 项；新增专项 28 个参数化测试实例，
迁移 10 个既有测试文件。对应 Q-C01～03、Q-A01～03、D-C01～02、L-Z01～04、
F-S01～04 以及几何边界，逐项证据见 acceptance_matrix.md。

CLI Replay batch：**4 passed / 0 failed / 0 skipped**。
产物目录：`/tmp/brain-query-batch-t8P5Ed7W`。包含同会话生成→查询→“它们”查询，
不是模型准确率或机器人执行验收。

### 仓库外 wheel

本轮新建 venv：`/tmp/brain-query-wheel-79dkK7n1/env`。
最终 wheel：`/tmp/brain-query-wheel-79dkK7n1/final/robot_agent_brain-0.1.0-py3-none-any.whl`。
SHA256：`3507aeee4fd7373f8330b41eb4aabb2a5acc2d3e11e3014227708cc081ffadce`。

从 /tmp 清除 PYTHONPATH 后运行 scripts/wheel_smoke.py：**passed**。
实际导入来自该 venv 的 site-packages；验证包内 prompts/assets/defaults、公开 Schema、
两轮命令导出和第三轮集合 Query=2。产物 `/tmp/brain-wheel-smoke-n0o1vapf`。
这些临时本地产物不提交到仓库。

### GitHub Actions

[本轮代码 CI](https://github.com/haotian2410/robot_agent_brain/actions/runs/37578435201)
已由实际 push 触发，并通过 GitHub API 实际核对：

- [Python 3.11](https://github.com/haotian2410/robot_agent_brain/actions/runs/37578435201/job/112652445725)：completed / success。
- [Python 3.12](https://github.com/haotian2410/robot_agent_brain/actions/runs/37578435201/job/112652445969)：completed / success。

两项均包含全量 pytest、wheel 打包及仓库外 smoke，并非只提交了 workflow 文件。

### 真实模型与外部接口

`real_qwen_tested=false`。本轮实际请求
`http://127.0.0.1:8080/v1/models` 返回 connection refused。
未启动、重配或替换模型；未把 Replay/HTTP 注入测试写成真实 Qwen 通过。

前端、Control、components/taskStep 转换、真实渲染和机器人执行未联调。
CLI 仍导出 Brain 原生 SceneConfig/Commands，而非 scene.xml 或物理执行结果。

## 已知限制

支撑推导是包围盒几何证据，只支持水平朝上的 surface（可 yaw），不是接触物理。
必须有 AABB 或明确 center-origin 元数据；未知原点/倾斜表面不推断。
support_contact_tolerance_m 默认 .001 米，是容差而非位姿补偿。
检查过但未证明的支撑用 support_evaluated 区分于未经检查的上传场景；
on 查询只返回有正面证据的对象。没有容器内部几何，不重建 inside。

本轮事实重建针对新增/变换目标，不会自动移动其他被支撑对象；
若部署端移动/删除桌面或执行机器人动作，需要提供完整确认快照，
不能把 Brain 元数据编辑当作物理求解器。Commands v2 的执行语义未变更。

## 实际修改文件

下列为代码提交相对基线的 34 个文件，另更新本报告（合计 35 个）：

```text
brain_tests/support_fixtures.py
brain_tests/test_acceptance_remaining.py
brain_tests/test_application_artifacts.py
brain_tests/test_batch.py
brain_tests/test_bootstrap_scene_edits.py
brain_tests/test_layout_and_numeric_edges.py
brain_tests/test_pipeline_stages.py
brain_tests/test_query_focus.py
brain_tests/test_query_scene_continuity.py
brain_tests/test_same_turn_understanding.py
brain_tests/test_scene_contracts.py
brain_tests/test_semantic_closure.py
docs/acceptance_matrix.md
docs/contracts.md
docs/manual_testing.md
examples/cases/manual_cases.jsonl
examples/replay/manual.json
scripts/wheel_smoke.py
src/robot_agent_brain/config.py
src/robot_agent_brain/contracts/turn.py
src/robot_agent_brain/grounding/scene_grounder.py
src/robot_agent_brain/grounding/scene_relation_resolver.py
src/robot_agent_brain/grounding/semantic_entity_selector.py
src/robot_agent_brain/models/prompt_templates/task_understanding_v2.txt
src/robot_agent_brain/models/qwen_http.py
src/robot_agent_brain/pipeline.py
src/robot_agent_brain/resources/defaults.json
src/robot_agent_brain/scene/editor.py
src/robot_agent_brain/scene/geometry.py
src/robot_agent_brain/scene/query.py
src/robot_agent_brain/scene/scene_layout.py
src/robot_agent_brain/scene/scene_manager.py
src/robot_agent_brain/scene/spatial_facts.py
src/robot_agent_brain/session/dialogue_state.py
docs/implementation_report.md
```
