# Query 契约收口与场景连续性返修报告 — 2026-10-07

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
