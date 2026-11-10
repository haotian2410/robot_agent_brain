# C0–C7 续验与当前工作树审计（2026-11-05）

本记录按 `01_refactor_plan.md` 与 `06_test_runbook.md` 重新核对当前实现。它把自动回归、编译证据、真实服务 smoke 和仍未验证的项目分开，不把旧 campaign 或正确澄清误算成完整通过。

## 当前实现基线

- 上一个已推送提交：`3ee2434`。
- 本次续验工作树在其上增加：桌面默认支撑归一化、工作区策略元数据、独立 oracle 几何断言、known-scene 未绑定 fail-closed 标记及对应测试。
- 未修改生产 OLS、OBJ/MTL/PNG/URDF；未调用 Control、IK、MuJoCo 或真实机器人执行。
- 未触碰工作树中已有的未跟踪本机配置、`docs/docs/` 和 IDE 文件。

## C0–C6 结果

| 阶段 | 结果 | 证据 |
|---|---|---|
| C0 | 通过 | `validate_spec.py`：20 个功能行、115 条表达、27 条不变量 |
| C1 | 通过（自动/静态） | OLS 1.0.7 目录快照包含 34 model、13 robot、7 scene；model/robot 命名空间分离 |
| C2 | 通过（MockTransport） | 每轮请求包含 `asset_catalog`、`workspace`、`scene_context`，并锁定同一 revision |
| C3 | 通过（自动/隔离 fixture） | `asset_choices` 成员与可新增性校验；mug-only 与 cup+mug 目录演进用例通过 |
| C4 | 通过（自动） | v3.1 裸 `add` 归一到 primary table；桌面区域、中心、对象相对缺参照物和回滚回归通过 |
| C5 | 通过 | v2 编译器展开全部 115 条表达，seed/变体/重复轴独立 |
| C6 | 通过（自动） | 父快照、角色绑定、seed/all/fixed 选择和兄弟分支隔离回归通过 |

## 编译与规范证据

证据目录：`var/semantic-v2/audit-20261105-102514/`。

- `validate_spec.py` 输出 `status=valid`、`feature_rows=20`、`expressions=115`、`regression_invariants=27`。
- generated v2 输出 115 sessions，首条包含 `asset_role_mapping`、`fixture_id=workspace_empty` 和完整 instruction。
- known-scene v2 也展开 115 条，但官方 workbook 没有具体场景路径。现在 manifest 明确写入：
  - `scene_binding_status=missing`
  - `known_scene_requires_fixture_binding=true`
  因此不会把 scene-less 输出误当成可运行的预设场景批次；campaign 在缺少 fixture 绑定时直接标记 `blocked_fixture`，不触碰浏览器。

## 自动回归

```text
conda run --no-capture-output -n robot_agent_integ pytest -q
```

结果：收集 902 项，退出码 0，全部通过。

专项验证：

```text
conda run --no-capture-output -n robot_agent_integ \
  pytest -q brain_tests/test_batch_oracle.py \
    brain_tests/test_batch_matrix_v2_features.py \
    brain_tests/test_semantic_matrix_v2_spec.py
```

结果：全部通过。独立 oracle 现在校验旋转轴/角度（含 q/-q 等价）、平移非目标轴和距离、缩放倍率/模式、所有目标区域符号、查询结果证据与 robot setup，而不是只检查“发生了变化”。

## 真实服务证据与未验证项

已有真实 Qwen/OLS/Brain/Gateway 证据仍只覆盖代表性 smoke：空场景/预设场景代表用例和七个 OLS 场景只读查询。它们证明服务链路和场景协议可用，不等价于 115 条表达全量真实验收。

仍明确标记为 `unverified` 或 `blocked_fixture`：

1. 115 条表达在真实 Qwen 上的完整执行；当前缺少 `single_a_center`、`three_a_one_reference`、`safety_scenarios` 等 runbook fixture。
2. T19 目录演进的真实隔离 OLS 运行；生产 OLS 不会为了测试临时增加/删除 cup。
3. 27 条不变量的逐条真实浏览器证据；目前有结构校验和自动测试，未伪称为现场通过。
4. Wheel smoke；当前环境缺少 `hatchling.build` 时应单独记为环境阻塞。
5. 机器人 profile 切换、Control、IK、MuJoCo、真实轨迹执行和双臂执行。

## 结果口径

- `passed`：预期语义、终态和独立 Scene/query/profile 断言均通过。
- `expected_clarification`：真实缺信息且场景/版本未改变；不计入成功生成率。
- `expected_safe_rejection`：有不可行几何证据、错误码匹配且原子回滚；不计作程序失败。
- `blocked_fixture`：缺少明确 fixture、目录或 profile，未运行模型语义，不进入准确率分母。
- `failed_protocol/runtime`：Qwen schema、引用、几何实现或服务异常，需要保存 raw/canonical/traceback 后修复。

本轮没有用旧截图、旧进程或“模型自己选择的结果”作为正确性证明；真实联调仍应在重启到当前工作树后按 runbook 分批补齐。
