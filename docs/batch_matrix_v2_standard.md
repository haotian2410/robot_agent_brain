# 批量测试矩阵 v2 维护标准

## 目标

v2 用两份 Excel 维护场景编辑和已知场景测试：

- `examples/matrices/generated_edit_matrix_v2.xlsx`：从空/引导桌面生成对象，再验证位置、旋转、颜色、移动、关系和回滚。
- `examples/matrices/known_scene_matrix_v2.xlsx`：针对 OLS 预设场景做查询、连续编辑、原始场景和能力边界验证。

Excel 是维护入口，编译后才交给批处理器。v1 文件和 JSON 继续保留。

## OLS 资产词表

本仓库还随 `docs/semantic-refactor/02_semantic_test_matrix.xlsx` 提供
`brain-semantic-matrix.v2` 的权威语义回归包。它使用 `matrix`（20 行功能）+
`variants`（115 条完整自然语言表达）双工作表；这份包与历史的
`generated_edit_matrix_v2.xlsx`/`known_scene_matrix_v2.xlsx` 入口并存，不能把
旧表的 `sample_count` 当作新包的变体数量。用 `--matrix-version 2` 时必须使用
该双工作表格式，编译器会做 20/115/27 的结构检查。

运行 `scripts/build_batch_asset_catalog.py` 从当前 OLS `model_index.json` 和模型元数据生成 `config/batch_asset_catalog.json`。表格使用 `asset_key`，不填写数字 ID、路径或 URDF 文件名。编译 manifest 会记录实际 `semantic_name`、标签、类别、MetadataRef 和来源行号。

Brain 首轮任务理解会把当前 OLS 的规范资产名、标签、类别和普通/容器/表面/被动范围注入 Qwen。Qwen 必须从词表选择；Python 仍做最终校验。OLS 升级后必须重新生成目录和重新编译矩阵。

## 桌面语义

本期场景编辑统一在桌面或桌面容器中解释：右为世界 `+X`，前为 `+Y`，竖直上为 `+Z`。`桌子左侧`、`桌面左侧`、`左上角`都表示桌面区域，不再询问桌外地面。仍需澄清不存在/不唯一的参照物、缺少容器内部几何、无合法网格位置和明确机器人执行请求。

## `matrix` 列

基础列：`enabled`、`test_id`、`flow_id`、`parent_test_id`、`parent_flow_id`、`difficulty`、`stage`、`round_index`、`category`、`sample_count`、`branch_policy`、`notes`。

角色列：`role_a`、`role_b`、`placement_1`、`placement_2`；具体资产列：`asset_a_key`、`asset_b_key`、`placement_1_key`、`placement_2_key`、`surface_1_key`。具体 key 优先于角色随机选择，角色选择由 `--seed` 决定。

指令列：`instruction_template`、`variants`、`scene_basis`、`coverage_tag`、`requires_visual`。占位符为 `{object_a}`、`{object_b}`、`{placement_1}`、`{placement_2}`、`{surface_1}`、`{color}`、`{color_phrase}`、`{direction}`、`{distance}`。`variants` 用 `|` 分隔，必须只改变语言表达，不改变测试意图。

预期列：`expected_outcome`、`expected_error_codes`、`expected_scene_change`、`assertion_profile`。结果可写 `success`、`clarification_required`、`safe_rejection`、`query_answered`、`plan_ready`、`capability_unsupported` 或 `blocked`；场景变化写 `changed`、`unchanged` 或 `query_only`。

## 继承与难度

`parent_test_id` 可引用任意前置行；空值表示新 session。`seed_parent` 从父分支稳定选择一个前缀，`all_parents` 展开全部父分支。L1 是单轮基础生成/查询，L2 是属性和简单关系，L3 是几何边界，L4 是多对象、原始场景、能力拒绝和整轮回滚。普通流程 1–5 轮，最多 10 轮。

示例：

```text
GEN-ADD-001: 增加一个{object_a}|在桌子上增加一个{object_a}|生成一个{object_a}
GEN-REGION-001(parent_test_id=GEN-ADD-001): 在桌子右上角生成一个{object_a}|在左下角放置一个{object_a}
EDIT-ROT-001(parent_test_id=GEN-ADD-001): 把{object_a}旋转九十度|让{object_a}顺时针转90度
EDIT-COLOR-001(parent_test_id=GEN-REGION-001): 把{object_a}改成蓝色|把{object_a}换成蓝色
EDIT-MOVE-001(parent_test_id=EDIT-COLOR-001): 把{object_a}向右移动五厘米|把{object_a}往东移五厘米
```

## 编译和执行

```bash
python scripts/build_batch_asset_catalog.py \
  --root /home/cscvlab/lht/webeditor_runtime/ObjectLibraryServer-1.0.7-dev-a6bc69a/data \
  --output config/batch_asset_catalog.json

robot-brain batch-compile --matrix examples/matrices/generated_edit_matrix_v2.xlsx \
  --kind generated_edit --asset-catalog config/batch_asset_catalog.json \
  --schema-version 2 --seed 20261103 --output examples/batch_sessions_generated_v2.json
```

已知场景同样使用 `--kind known_scene`。编译失败必须指出 sheet/行/列；不得生成不完整 JSON。编译 manifest 中的 `covered_asset_keys` 和 `uncovered_asset_keys` 用于检查覆盖率。

## 结果判断

成功编辑必须只增加一个版本；查询、澄清和安全拒绝不得增加版本。失败轮必须保留前后 Scene、digest、raw Qwen、canonical payload、截图和诊断编号。机器人计划始终 `executed=false`；Piper/CobotMagic 的平台能力限制单独记为 `capability_unsupported`，不当作普通程序失败。

不得修改 OLS 原始模型、纹理、URDF，不得用假截图或伪造机械臂执行成功。发现问题时先保留证据，再按 Qwen 解析、语义协议、场景引用、几何布局、Gateway/浏览器和 OLS 资产来源分类。
