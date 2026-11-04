# Semantic Refactor C0–C7 验收报告（2026-11-05）

> 报告使用的源代码基线为 `d381080`，远端同步基线为 `c64f57a`（本轮按要求未自动推送）。
> 文中历史段落若出现旧 SHA，
> 仅表示当时的证据快照，不代表当前代码版本。

## 结论摘要

本报告按 `01_refactor_plan.md` 和 `06_test_runbook.md` 记录 C0–C7 的当前证据。
C0–C6 的代码、结构化校验和自动回归已完成；C7 的首五行真实验收已在匹配
fixture 上完成，T03/T04/T05 共 26 条表达全部通过独立场景 oracle。完整 20 行、
115 条表达的真实 Qwen/Gateway 验收尚未完成，不能据此宣称整个矩阵通过。

源代码基线：`d381080`；远端同步基线：`c64f57a`。generated campaign
的服务运行证据以 `50da3d1` 语义代码基线记录，后续提交仅补充证据分类、hash 和文档。

## 运行基线

| 项目 | 实际值 |
|---|---|
| Qwen | `127.0.0.1:8080/v1`，真实 Qwen3.8-27B，`reasoning off` |
| OLS | `127.0.0.1:8000`，1.0.7-dev 数据目录 |
| Brain | `127.0.0.1:8500`，`brain-web/2` |
| Gateway | `127.0.0.1:8099`，`brain-web/2` |
| OLS catalog | 34 model、13 robot、7 scene |
| catalog revision | `sha256:c53749b10d5a054289414101e8777b4c58fe52066704e46aab8ff96ba1f064cc` |
| camera | Brain 选择顶视 `camera_id=5`，证据中为 `explicit_overhead_semantic` |
| 执行边界 | `executed=false`；未调用 Control、IK、MuJoCo 或真实轨迹 |

服务健康检查在真实批量开始前返回 `service=ready`、`qwen=ready`、`browser=bound`、
`assets=ok`，资产计数与 OLS 一致。

## C0–C6 状态

| 阶段 | 状态 | 证据 |
|---|---|---|
| C0 基线与旧协议 | 已验证 | 全量 pytest 通过；旧 JSON/JSONL 入口仍保留；v2 `expected_json` 现在按 route/oracle 最小结构校验 |
| C1 OLS 目录与命名空间 | 已验证（自动/静态） | `FinalModelsLibraryAdapter` 读取 34/13/7；model/robot 数字 ID 分离；每轮可原子刷新 OLS 与别名 revision |
| C2 首阶段上下文 | 已验证（自动/静态） | 每轮请求携带完整 `asset_catalog`、`workspace`、`scene_context`，并使用同一 revision；mug-only/future-cup alias 回归通过 |
| C3 资产选择 | 已验证 | v3.1 `asset_choices` 校验 key、规范名、可新增性和 catalog revision；不把 cup 永久改写成 mug |
| C4 固定桌面语义 | 已验证 | live v3.1 桌子左右归一到桌面区域；对象相对关系缺参照物时澄清；center 严格检查真实桌面中心与 workspace；几何保护、回滚保留 |
| C5 矩阵编译 | 已验证 | 官方校验得到 20 行、115 表达、27 不变量；v2 生成/known 两种 kind 均输出 schema v2；`--schema-version 2` 不再回退到 v1 |
| C6 父快照与分支隔离 | 已验证 | campaign 只接受父 run 全部 turn `classification=passed` 且 digest/角色满足子行要求 |

结构化校验命令：

```text
conda run --no-capture-output -n robot_agent_integ \
  python docs/semantic-refactor/validate_spec.py
```

输出：`status=valid`，`feature_rows=20`，`expressions=115`，
`regression_invariants=27`，首五行为 `T01..T05`。

编译命令（均成功）：

```text
robot-brain batch-compile --matrix-version 2 \
  --matrix docs/semantic-refactor/02_semantic_test_matrix.xlsx \
  --kind generated_edit --asset-roles docs/semantic-refactor/07_asset_roles_template.json \
  --asset-catalog config/batch_asset_catalog.json --seed 20261103 \
  --run-profile independent_first_five \
  --output var/semantic-v2/audit-20261105/generated_independent.json

robot-brain batch-compile --matrix-version 2 \
  --matrix docs/semantic-refactor/02_semantic_test_matrix.xlsx \
  --kind known_scene --asset-roles docs/semantic-refactor/07_asset_roles_template.json \
  --asset-catalog config/batch_asset_catalog.json --seed 20261103 \
  --output var/semantic-v2/audit-20261105/known_default.json
```

两份输出均为 schema v2、115 sessions。注意：官方 workbook 当前没有为
`known_scene` 行提供具体场景路径，因此该编译成功只证明 schema/展开逻辑，
不证明七个预设场景已经完成真实运行。

编译入口边界复核：`examples/matrices/generated_edit_matrix_v2.xlsx` 和
`examples/matrices/known_scene_matrix_v2.xlsx` 只有历史 `matrix`/`README`
结构，使用 v2 reader 会明确返回
`semantic_matrix_v2_sheet_missing:matrix,variants`，不会再由旧
`compile_matrix` 以 `schema_version=2` 静默解释。正式 v2 维护入口仍是上述
`docs/semantic-refactor/02_semantic_test_matrix.xlsx`。

## C7 真实验收

### 当前 HEAD 的 generated campaign 证据

当前 HEAD 运行的 generated campaign 证据目录：

```text
/tmp/semantic-c7-full.X3PAbX/campaign-20261105-044141-20261105-641ab6ea/
```

该运行使用真实 Qwen、OLS、Brain 和 Gateway。按 stage 统计如下；失败、安全拒绝和
截图证据阻塞没有被折算成通过：

| case | 结果 |
|---|---|
| T01 | 5/5 passed |
| T02 | 6/12 passed；6 条为 `scene_edit_layout_collision`，场景未改变，当前 fixture/workspace 不满足左半区/中心正例 |
| T03 | 8/8 passed |
| T04 | 8/8 passed |
| T05 | 10/10 passed |
| T06 | 4/4 passed |
| T07 | 6/6 passed |
| T08 | 5/6 passed；“南侧”一条返回澄清，矩阵当前预期为成功 |
| T09/T10 | `blocked_fixture` |
| T11 | 0/5；4 条真实 Qwen 对多样式 pen 正确澄清但矩阵要求成功，1 条缺 `replacement_entity` |
| T12 | 5/5 passed |
| T13/T14 | `blocked_fixture` |
| T15 | 1/4 passed；其余语义澄清但截图证据不可用，已分离 `semantic_classification` 与 `evidence_status` |
| T16–T20 | `blocked_fixture` |

逐轮 raw/canonical、Scene、digest、截图和 oracle 保存在上述 stage 目录。
本次实际执行 70 个 turn：58 个完整通过、7 个协议/运行时失败、5 个断言失败、
3 个截图证据阻塞；另外 9 个根 stage 因缺少隔离 fixture 阻塞。此统计不等于
115 条表达全部通过。

### 首五行完整表达

使用匹配的独立 fixture（早于当前 HEAD 的历史快照）：

```text
/tmp/c7-retest-20261105-WChkHj/t03_t05_matching.json
```

fixture 选择与矩阵角色一致：T03/T05 使用 marker，T04 使用 baseball；每个
turn 仍通过真实服务和浏览器 Gateway 执行，未把 fixture 搭建计入被测语义。

最终重跑命令：

```text
conda run --no-capture-output -n robot_agent_integ robot-brain batch \
  --cases /tmp/c7-retest-20261105-WChkHj/t03_t05_matching.json \
  --transport service --agent-url http://127.0.0.1:8500 \
  --gateway-url http://127.0.0.1:8099 \
  --output-dir /tmp/c7-retest-20261105-WChkHj/out-final \
  --task-timeout 180
```

结果目录：

```text
/tmp/c7-retest-20261105-WChkHj/out-final/batch-20261105-022737-3d13b5ac/
```

结果：`passed=26, failed=0, blocked=0, skipped=0`；该目录只能作为历史参考，
不能代替当前 HEAD 的完整验收证据。

| 行 | 表达数 | 结果 |
|---|---:|---|
| T03 旋转 | 8 | 8/8 passed |
| T04 改色 | 8 | 8/8 passed |
| T05 平移 | 10 | 10/10 passed |

每条 turn 的 `oracle.json` 均证明预期场景变化、对象/组件变化、
`executed=false`，并保存 `before_scene.json`、`scene.json`、digest、
`screenshot.png`、raw/canonical payload 和 debug bundle。

### 本轮发现并修复的两个问题

1. **独立 oracle 的命名空间误匹配（已修复）**

   OLS 模型 `3` 与机器人 `3` 共享 `$LIBRARY_SERVER/3` 路径。旧 oracle 只按
   path 匹配，将 baseball 同时识别为 wrist/overhead camera，T04 8 条均报
   `unique_target_instance`。现在 `_find_by_role()` 同时匹配 `path + type`，
   并增加回归测试。修复后 T04 8/8 通过。

2. **模糊平移绑定缺少中间幅度词（已修复）**

   “向右稍微挪一点/往右轻微移动一下”中方向和动词之间有幅度词，旧正则
   无法绑定，报 `motion_clause_binding_ambiguous`。现在 Python 提取器允许
   这些词并映射到 `motion_scale=small`；Prompt 同步规定场景编辑的“一点/稍微/
   轻微/一下”由 Python 策略处理。T05.V09/V10 在修复后 2/2 通过。

### 旧证据的处理

- `/tmp/c7-retest-20261105-WChkHj/out/batch-20261105-015943-0abf18c2/`
  是修复前结果：15 passed、11 failed；其中 T04 8 条是 oracle 假失败，
  T03.V05 和 T05.V09/V10 暴露了真实语义/证据问题。
- `/tmp/c7-retest-20261105-WChkHj/out-v05/batch-20261105-021219-81d03cd6/`
  是 T03.V05 Prompt 修复后的单条复测，`passed=1`。
- `/tmp/c7-retest-20261105-WChkHj/out-vague2/batch-20261105-022657-af7f3cf9/`
  是 T05.V09/V10 提取器修复后的 2 条复测，`passed=2`。
- `/tmp/c7-retest-20261105-WChkHj/out-oracle/batch-20261105-022005-1b9e436e/`
  是 oracle 命名空间修复后的 T04 8 条复测，`passed=8`。

## 自动回归

```text
conda run --no-capture-output -n robot_agent_integ pytest -q
```

本轮全量 pytest 退出码为 0；v2 reader/compiler、CLI 分派、角色类别校验、
专项 oracle、motion evidence、scene default grid、clean v3 prompt 测试均通过。
`git diff --check` 通过。另有：

```text
conda run --no-capture-output -n robot_agent_integ \
  python docs/semantic-refactor/validate_spec.py
```

输出 `status=valid`、`feature_rows=20`、`expressions=115`、
`regression_invariants=27`、首五行为 `T01..T05`。

本轮 `d381080` 新增专项回归命令：

```text
conda run --no-capture-output -n robot_agent_integ \
  pytest -q brain_tests/test_task_understanding_clean_v3.py \
  brain_tests/test_scene_default_grid.py
```

结果：33 项通过。新增行为包括：对象相对新增缺少 `reference` 时明确澄清且不转成
`on(table)`；`center` 放置严格使用桌面几何中心，中心超出 workspace 时拒绝而不取
裁剪后的工作区中点。修改代码后需要重启运行中的 Brain 进程才能在服务中生效。

批量服务前置检查也已收紧：Qwen 非 `ready`、OLS `asset_detail.matched` 为假、已有活动/排队任务，
或活动浏览器没有 Camera 时，在创建批量 session 前直接返回阻塞错误；不会继续执行并生成半套证据。

## 未验证、阻塞和边界

以下项目不能标成通过：

1. **完整 115 条真实 C7**：当前 HEAD campaign 已覆盖 70 个 turn，但仍有失败和
   fixture 阻塞；不能宣称 115 条全部通过。T02 的几何拒绝、T08 的“南侧”澄清、
   T11/T15 的真实 Qwen差异均保留原始证据。
2. **27 个回归不变量的真实运行**：结构和自动单测已验证，但没有把每一条都在
   真实浏览器/OLS 环境中执行并附独立证据。
3. **Known-scene C7**：官方 known 编译成功，但 workbook 当前未给出 scene
   路径；七个预设场景的真实矩阵运行仍为 `unverified`。
4. **Wheel smoke**：当前环境缺少 `hatchling.build`，因此打包 smoke 为环境阻塞，
   不是业务测试失败。
5. **真实机器人执行、Control、IK、MuJoCo、双臂规划**：按范围明确跳过；所有
   计划结果必须保持 `executed=false`。

### 证据分类补充

- `classification=blocked` 只表示截图/浏览器等证据条件未满足；若任务语义已经得到
  正确澄清或安全拒绝，逐轮 JSON 另有 `semantic_classification`（如
  `expected_clarification`）和 `evidence_status=blocked`，不能把两者混为模型失败。
- 编译期 `config/batch_asset_catalog.json` revision 与运行时 OLS catalog revision
  分开记录；当前运行时请求携带的是 OLS 当轮 revision。两者不是同一个快照，故不能
  宣称“编译 manifest 与运行请求版本完全一致”，这属于待补的锁定证据。
- 官方 `A01–A13/M01–M13/R01` 27 项回归断言目前只有规范结构和自动单测覆盖，
  没有逐条真实浏览器证据；报告保留为未验证，不将计数校验写成行为通过。
- 当前 HEAD 的真实首轮 smoke 已在
  `/tmp/semantic-c1-real.6PQaGB/out/batch-20261105-050304-f03cb62a/` 保存
  `prompt_sha256`、`schema_sha256`、`catalog_revision`、真实模型 usage 和完整
  目录计数；更早的 full campaign bundle 没有这些新字段，因此只作为历史运行证据。

本轮新增的 v2 结构证据目录（临时目录，不是生产资产）为：
`/tmp/semantic-v2-check.8BVZha/`。其中 generated/known 两份编译输出各有
115 sessions，manifest 记录 `case_count=20`、`variant_count=115`、
`invariant_count=27`。该目录不包含真实 C7 全量浏览器运行结果。

## 资产与安全边界

- 没有修改生产 OLS、原始 OBJ/MTL/PNG/URDF 或压缩包。
- geometry cache 只作为派生校验数据；catalog revision 不匹配时不静默使用旧缓存。
- 澄清、安全拒绝和失败不提交场景、不增加版本、不生成 Commands。
- 真实截图通过 Gateway `captureScene` 获取；证据中的截图带完整场景身份和
  `camera_id=5`，不使用旧缓存伪造。
