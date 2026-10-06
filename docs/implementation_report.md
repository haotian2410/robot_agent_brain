# 增量实现交付报告 — 2026-10-07

## 范围与基线

仓库 robot_agent_brain，分支 main。开始时核对基线
`266ebcc94fd5b433ebe1000f4d04c7356b747faa`，工作区干净，原有 26 项测试通过。
保留原 Pipeline、SceneManager、Grounder、TaskExpander、RecipePlanner 和 Commands v2，
增量增加应用编排，没有引入 MuJoCo、MJCF、Control、IK 或轨迹依赖。

本报告的最终**代码**验收版本为 `d427bc5`，之后的报告整理只修改文档。
全部提交保留在本地，**未推送 GitHub**。逐条行为证据见 [验收矩阵](acceptance_matrix.md)。

## 已实现

- 一次理解得到 BrainTurn，同一份结果用于可选场景初始化及后续处理；兼容 run/run_turn/run_task。
- generated/uploaded/session/none 分流；有效空场景不重建，坏上传不 fallback，已有场景缺对象不补造。
- 元数据初始化保持数量/颜色/候选和初始关系；不提前完成机器人放置目标，不重复首轮 add。
- 有序原子编辑、SceneEditResult、稳定实例 ID、退休 ID 保护、变换保留、同轮新增引用和跨轮集合焦点。
- 模糊距离依据用户措辞，按模型轴尺寸与实例比例换算；缺距离证据不接受模型猜测。
- 握持状态驱动组合 recipe，集合配对保留数量，独立 PlanValidator 在导出入口验证语义前置条件。
- canonical commands v2 wire、严格读取/写盘和独立公开 Schema 验证，scene/commands 版本一致。
- run/chat/batch/schemas、配置优先级、包内 demo 资产/布局资源、明确的 Qwen/Replay 区分。
- export_only 不占 pending、不更新确认姿态；显式 dispatch、反馈检查及外部新快照刷新。
- JSON 会话保存/恢复、配置指纹、本地 POSIX 锁、隔离请求目录、失败时不返回旧命令。
- HTTP 注入测试、逐轮调用日志、失败 raw/usage/finish_reason 保留、debug 脱敏诊断。
- README、手动测试、协议说明、回放用例、CI Python 3.11/3.12 与独立 wheel 验收脚本。

## 实测结果

以下检查均实际运行，不是预期结果：

```bash
cd /home/cscvlab/lht/robot_agent_brain
/home/cscvlab/miniconda3/envs/robot_agent_integ/bin/python -m pytest -q brain_tests
git diff --check
```

结果：**205 passed**，diff 检查无错误。包含依赖边界、单元、HTTP MockTransport、
Replay、Application、CLI 子进程和落盘产物测试；不代表真实模型理解准确率。

文档 JSONL 批处理实际运行：**3 passed / 0 failed / 0 skipped**；
证据目录 `/tmp/brain-manual-doc-audit`（临时本地产物，不提交为真实模型结果）。

### 最终代码 wheel 仓库外验收

```bash
cd /home/cscvlab/lht/robot_agent_brain
/home/cscvlab/miniconda3/envs/robot_agent_integ/bin/python -m pip wheel --wheel-dir /tmp/brain-final-wheel-e3jQoGgk/wheels .
/home/cscvlab/miniconda3/envs/robot_agent_integ/bin/python -m venv /tmp/brain-final-wheel-e3jQoGgk/env
/tmp/brain-final-wheel-e3jQoGgk/env/bin/python -m pip install --no-index --find-links /tmp/brain-final-wheel-e3jQoGgk/wheels robot-agent-brain
cd /tmp
env -u PYTHONPATH /tmp/brain-final-wheel-e3jQoGgk/env/bin/python /home/cscvlab/lht/robot_agent_brain/scripts/wheel_smoke.py
```

**通过**。Python 3.12 新 venv，无 system-site-packages，导入路径实际来自
`/tmp/brain-final-wheel-e3jQoGgk/env/lib/python3.12/site-packages/robot_agent_brain`。
没有使用源码 PYTHONPATH。验证控制台入口、prompt/config/assets 包资源、schemas、
无 scene 的机器人 Replay、两只苹果、commands Schema、场景 ID/版本一致、
跨进程恢复同一场景并再次导出。验收输出：
`/tmp/brain-wheel-smoke-h6ncns7s`。

Wheel SHA256：
`04d36f4981931cb552b50e123a09d114899873bdd602457c4c45939246b75ea0`。
CI 已配置同一脚本用于 Python 3.11/3.12；本机实际执行的是 3.12，不声称远程 CI 已运行。

### 真实 Qwen

**未运行真实 Qwen 任务验收**。实际执行
`curl --noproxy '*' --max-time 3 --silent --show-error http://127.0.0.1:8080/v1/models`
得到连接拒绝（exit 7）。没有自动启动服务，没有用 Replay 冒充真实模型。
服务恢复后按 manual_testing.md 指定实际 model ID 进行真实自然语言测试。

## 可复制使用方式

```bash
cd /home/cscvlab/lht/robot_agent_brain
python -m pip install -e '.[dev]'
robot-brain run '把两个苹果放进篮子' --provider replay \
  --replay-file examples/replay/manual.json --output-dir var/demo --session demo01 --json
robot-brain run '有几个苹果' --provider replay \
  --replay-file examples/replay/manual.json --output-dir var/demo --session demo01 --json
robot-brain chat --provider replay --replay-file examples/replay/manual.json \
  --output-dir var/demo --session demo01
```

输出位置为 `OUTPUT/SESSION/REQUEST/`。机器人拿
`scene_config.json + commands.json`，编辑拿完整 scene_config.json 和 patch，
查询拿报告回复及 query_result.json。报告明确 `executed=false`。
真实模型命令及全部参数见 [手动测试](manual_testing.md)。

## 兼容与迁移

- 旧便捷 API 保留；新增 process_turn 不重复调用理解模型。
- SceneEditor.edit 仍返回 Patch；新 edit_result 额外返回焦点/创建删除 ID/局部绑定。
- CommandsFile 仍为 2.0；使用 canonical_commands 或已验证的最终文件，不自行保留互斥 null。
- CommandExporter 的直接调用也经过 PlanValidator，必须提供实际包含目标实例的场景。
  如果计划从已握持状态开始，显式传 held_object。
- 导出不再自动 pending；外部集成必须显式 mark_dispatched。无执行后确认快照则 unknown。
- 恢复需同一输出根目录和 session ID；配置指纹变化会提示，不重建已确认场景。
- 原测试意图保留：旧双抓取测试保留数量并断言单夹爪拒绝，用 LOCATE 检查全部实例导出；
  旧空场景导出夹具补齐其目标对象；无依据 .01m 旧断言改成 P05 要求的拒绝；
  原多平移测试补写其真实 5cm/10cm 输入，保留全部姿态与数量断言。

## 明确限制与外部未验收项

- 只交付 Brain 原生 JSON，不是 scene.xml/MJCF，不宣称兼容未冻结的 components/taskStep。
- 前端/Control 联调、真实物理执行/抓取、IK/轨迹/碰撞能力均未验证，也不属于本应用实现。
- 初始 inside/on 等缺内部几何能力的约束明确拒绝；SEARCH 无实现时明确拒绝，不降级。
- demo 只有尺寸/类别/属性元数据，没有真实 mesh/材质；LocalScenePlatform 没有图片。
  vision 开启需显式渲染适配器，否则报错，不向 VLM 传假图。
- 本地会话锁为 Linux/POSIX 单主机方案，不声称 Windows 或分布式并发部署已验收。
- 模型输出可能仍需澄清；Replay 仅接受夹具精确输入，不能证明任意自然语言理解。
- 磁盘与平台不是分布式事务；已确认场景后的磁盘失败保持真实提交状态，不能保证失败磁盘的恢复。
- 标准 JSON Schema 作用于合法 JSON。NaN/Infinity 非 JSON token 由严格解码拒绝，
  不把 Python 默认解析器的非标准扩展当成合法 wire。
- 当前源代码验收已完成；真实 Qwen 和外部执行接口须在相应服务/协议可用后另行验收。

## 实际修改文件（相对基线）

```text
.github/workflows/ci.yml
README.md
brain_tests/test_acceptance_remaining.py
brain_tests/test_application_artifacts.py
brain_tests/test_artifact_writer.py
brain_tests/test_batch.py
brain_tests/test_bootstrap_scene_edits.py
brain_tests/test_cli.py
brain_tests/test_config_assets.py
brain_tests/test_configuration_geometry.py
brain_tests/test_diagnostics_artifacts.py
brain_tests/test_edit_prospective_layout.py
brain_tests/test_export_roundtrip.py
brain_tests/test_layout_and_numeric_edges.py
brain_tests/test_motion_and_commands.py
brain_tests/test_motion_evidence_gate.py
brain_tests/test_pairwise_collections.py
brain_tests/test_pipeline_stages.py
brain_tests/test_plan_validator.py
brain_tests/test_query_focus.py
brain_tests/test_qwen_http.py
brain_tests/test_recipe_state.py
brain_tests/test_same_turn_understanding.py
brain_tests/test_scene_atomicity.py
brain_tests/test_scene_bootstrap.py
brain_tests/test_scene_domain.py
brain_tests/test_scene_file_codec.py
brain_tests/test_semantic_closure.py
brain_tests/test_session_lifecycle.py
brain_tests/test_session_store.py
docs/acceptance_matrix.md
docs/contracts.md
docs/implementation_report.md
docs/manual_testing.md
examples/cases/manual_cases.jsonl
examples/replay/add_apple.json
examples/replay/manual.json
pyproject.toml
scripts/wheel_smoke.py
src/robot_agent_brain/__main__.py
src/robot_agent_brain/adapters/artifact_writer.py
src/robot_agent_brain/adapters/json_command_sink.py
src/robot_agent_brain/adapters/local_asset_catalog.py
src/robot_agent_brain/adapters/local_scene_platform.py
src/robot_agent_brain/adapters/scene_file_codec.py
src/robot_agent_brain/application.py
src/robot_agent_brain/batch.py
src/robot_agent_brain/cli.py
src/robot_agent_brain/config.py
src/robot_agent_brain/contracts/bootstrap.py
src/robot_agent_brain/contracts/commands.py
src/robot_agent_brain/contracts/run_report.py
src/robot_agent_brain/contracts/scene.py
src/robot_agent_brain/contracts/turn.py
src/robot_agent_brain/diagnostics.py
src/robot_agent_brain/errors.py
src/robot_agent_brain/grounding/scene_grounder.py
src/robot_agent_brain/grounding/scene_object_selector.py
src/robot_agent_brain/models/prompt_templates/task_understanding_v2.txt
src/robot_agent_brain/models/qwen_http.py
src/robot_agent_brain/models/replay.py
src/robot_agent_brain/pipeline.py
src/robot_agent_brain/planning/command_exporter.py
src/robot_agent_brain/planning/plan_validator.py
src/robot_agent_brain/planning/recipe_planner.py
src/robot_agent_brain/planning/task_expander.py
src/robot_agent_brain/presentation.py
src/robot_agent_brain/resources/__init__.py
src/robot_agent_brain/resources/assets.json
src/robot_agent_brain/resources/config.json
src/robot_agent_brain/resources/defaults.json
src/robot_agent_brain/scene/asset_resolver.py
src/robot_agent_brain/scene/bootstrapper.py
src/robot_agent_brain/scene/editor.py
src/robot_agent_brain/scene/query.py
src/robot_agent_brain/scene/scene_manager.py
src/robot_agent_brain/semantics/motion_evidence.py
src/robot_agent_brain/session/brain_session.py
src/robot_agent_brain/session/dialogue_state.py
src/robot_agent_brain/session/store.py
```
