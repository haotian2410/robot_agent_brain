# Excel 测试矩阵

批量测试现在有两个维护入口：

- `examples/matrices/generated_edit_matrix.xlsx`：空场景的生成与后续编辑；
- `examples/matrices/known_scene_matrix.xlsx`：OLS 预设场景的查询、关系、原始场景和能力边界。

Excel 只保存测试意图。角色名（`object_a`、`placement_1` 等）由
`config/batch_asset_roles.json` 映射到 OLS 1.0.5 的模型语义名，编译时用固定
seed 选择实际资产，并在 `*_compile_manifest.json` 中留下候选、选中项和行号。
不要在表格中填写 OLS 数字 ID，也不要修改 OLS 原始资产。

## 编译

在安装了可选表格依赖的 Brain 环境中运行：

```bash
pip install -e '.[batch]'

robot-brain batch-compile \
  --matrix examples/matrices/generated_edit_matrix.xlsx \
  --kind generated_edit \
  --asset-roles config/batch_asset_roles.json \
  --seed 20261031 \
  --output examples/batch_sessions_generated.json

robot-brain batch-compile \
  --matrix examples/matrices/known_scene_matrix.xlsx \
  --kind known_scene \
  --asset-roles config/batch_asset_roles.json \
  --seed 20261031 \
  --output examples/batch_sessions_known.json
```

编译器会检查工作表名称、固定列、行号、`round_index`、`variants`、模板占位符、父流程和 OLS 场景名称。错误会带有 `sheet!column+row`，不会写出半成品 JSON。没有 `openpyxl` 时返回 `batch_matrix_requires_openpyxl`。

`generated_edit` 的一个父流程可以被多个编辑流程复用。`seed_parent` 选择一个可复现前缀，`all_parents` 展开所有前缀。当前静态编译先生成可直接运行的独立 session；它不会把一个 session 的结果伪装成另一个 session 的成功父状态。需要“父 session 成功后才继续”的实验，应在服务批量运行器上按 campaign 记录和筛选。

也可以直接使用成功门控 campaign。它先运行无父流程，再从成功父 session 的最后一轮
场景快照派生子流程；没有成功父 session 的分支会记录为
`skipped_parent_failed`，不会伪造前置成功：

```bash
robot-brain batch-campaign \
  --matrix examples/matrices/generated_edit_matrix.xlsx \
  --asset-roles config/batch_asset_roles.json \
  --seed 20261031 \
  --agent-url http://127.0.0.1:8500 \
  --gateway-url http://127.0.0.1:8099 \
  --output-dir var/batch-campaigns
```

campaign 的 `campaign_manifest.json` 会记录每个 flow、父 flow、阶段输出目录、成功分支和跳过原因。

## 运行与结果

生成的 JSON 仍可使用原有入口：

```bash
robot-brain batch \
  --cases examples/batch_sessions_generated.json \
  --transport service \
  --agent-url http://127.0.0.1:8500 \
  --gateway-url http://127.0.0.1:8099 \
  --output-dir var/batch-runs
```

每次运行仍保存 `summary.json`、`summary.md` 和逐轮场景证据。安装 `[batch]` 后，根目录还会生成 `batch_test_results.xlsx`。其中固定包含：

- 用户指令；
- 真实浏览器 `captureScene` 截图的超链接；
- 系统返回的任务结果。

同时记录 session、难度、类别、轮次、任务 ID、场景四元组、相机、终态、
`executed`、错误码、诊断编号、产物和证据目录。截图不可用时不会使用旧缓存，
该轮会被记录为阻塞或失败。

旧的 `examples/batch_sessions_empty.json`、`examples/batch_sessions_presets.json`
以及 JSONL 格式继续兼容，但新测试优先编辑两个 Excel 文件并重新编译。
