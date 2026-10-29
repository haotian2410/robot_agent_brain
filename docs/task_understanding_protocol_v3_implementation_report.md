# 任务理解与场景引用协议 P0–P3 整改报告

基线：`3168333`（本地 `main`，未覆盖用户已有未跟踪资料）  
当前实现：`0f8e161`

## P0：场景引用与错误传播

状态：完成。

完成内容：

- 先增加 `reference=table` 的端到端复现测试，再拆分 Qwen wire 解析和语义校验。
- 增加 `SceneReferenceCatalog`、`SceneReferenceResolver`，支持桌面、桌子、台面、`desk`、`desktop` 等别名。
- `table` 等环境引用不会进入普通 `AssetResolver`，也不会被加入任务实体列表。
- Bootstrapper、SceneObjectSelector、SceneEditor 使用同一套解析路径。
- 支持当前/原始场景中的唯一对象、对象名称和对象 ID 解析；多候选返回
  `scene_reference_ambiguous`，未知引用返回 `scene_reference_unresolved`。
- `BrainError` 保留 `code/category/stage/path/value/details/retryable`，语义错误不再默认伪装成 `provider_error`。

专项验证：

```text
brain_tests/test_scene_reference_protocol.py 通过
brain_tests/test_scene_bootstrap.py 通过
brain_tests/test_component_bootstrap.py 通过
```

## P1：canonical v3 与 Prompt 分层

状态：完成。

完成内容：

- 增加 `RefScope`、`CanonicalReference`、`SelectionRelation`、`PlacementGoal`。
- `SceneEditIntent` 支持独立的 `placement_goal`，并向旧 Editor 字段做确定性归一化。
- wire model 只做结构解析；canonical model 再做实体、操作、关系、依赖和场景 basis 校验。
- `id/name` 兼容归一化为 `entity_id/semantic_name`。
- v3 wire schema 仅要求 `turn_kind`，各 route 的 payload 由 Python 显式检查；旧严格 schema 保留给直接调用和兼容路径。
- Prompt 拆分为 common、route selection、scene edit、scene query、robot task、session control、output contract。
- 明确区分“机器人放进容器”“场景编辑在容器中增加对象”“查询容器旁边对象”。

## P2：策略、能力和依赖

状态：完成。

完成内容：

- 增加 `DomainPolicyRegistry`，统一关系枚举、场景引用目录和机器人能力提示。
- Prompt route 规则由 registry 生成，能力判断仍在语义解析后执行。
- 支持 `operation_id`、先前操作依赖和同轮新增对象被后续操作引用。
- 场景引用目录支持配置文件加载，并纳入配置指纹。
- Bootstrapper 只预创建真正需要绑定的任务实体；环境支撑面不作为待创建资产。

## P3：迁移、观测和评估

状态：完成。

完成内容：

- v2/v3 协议版本保留在 `BrainTurn`，旧 `TaskParseOutput` 明确标记为 v2，live scene-edit wire 默认 v3。
- `models/protocol_migration.py` 提供 canonical v2/v3 shadow comparison。
- 每轮 metrics/debug 记录协议版本、parser stage、turn kind、scene basis、原始/规范引用、错误码。
- 增加中文 golden corpus、别名稳定性、未知引用不绑定默认桌面、场景引用歧义和 v2/v3 等价性测试。
- 新增本报告和 `docs/task_understanding_protocol_v3.md`。

## 提交顺序

文档要求的 Commit 1–8 已按顺序完成：

```text
513a730 test(scene-edit): reproduce unknown table reference
8f5d245 refactor(task-understanding): separate wire parsing from semantic validation
25977f8 feat(scene): add scene reference catalog and resolver
891050d feat(scene-edit): resolve environment references before asset grounding
1d22704 fix(prompt): allow known scene references outside entities
b739db7 refactor(prompt): split common and route-specific semantic contracts
88ed528 refactor(policy): centralize semantic aliases and capability registry
655dc5f test(evaluation): add semantic protocol corpus and v2/v3 comparison
```

随后补充了集成、诊断、Bootstrapper、显式场景对象解析、协议校验、错误分类和 v3 wire 收尾提交：

```text
023e741  6815deb  cc2131a  ee99090  42c37ac  36f417e  7bf6d5e  0f8e161
```

## 验证结果

- 分阶段回归命令均在对应改动后执行：
  - P0：`pytest -q brain_tests/test_scene_reference_protocol.py brain_tests/test_scene_bootstrap.py brain_tests/test_component_bootstrap.py brain_tests/test_pipeline_stages.py`，通过。
  - P1：`pytest -q brain_tests/test_scene_edit_contract.py brain_tests/test_web_protocol.py brain_tests/test_qwen_http.py`，通过。
  - P2：`pytest -q brain_tests/test_domain_policy_registry.py brain_tests/test_scene_edit_contract.py brain_tests/test_pipeline_stages.py`，通过。
  - P3：`pytest -q brain_tests/test_semantic_protocol_corpus.py brain_tests/test_diagnostics_artifacts.py`，通过。
- 全量 `conda run --no-capture-output -n robot_agent_integ pytest -q`：通过，退出码 `0`。
- 场景引用、Bootstrapper、协议和 Qwen HTTP 专项测试：通过。
- 独立 wheel 构建：成功，SHA256：
  `2b8127b60e2ae8ecf28b588ca0f4a2b1e5b27f0addbb744fba05ff8c318dea72`。
- wheel smoke import：`robot_agent_brain wheel-smoke-ok`。
- 资产原文件、current/original 快照协议、双臂和 Commands v3 未修改。

## 剩余风险与边界

- 本轮没有启动真实 Qwen、Gateway、OLS 或 Control；真实模型输出稳定性和浏览器联调仍需单独验证。
- 不实现 IK、轨迹、碰撞执行、MuJoCo 或 Control 技能。
- `scene_reference_catalog` 只自动绑定明确注册的引用；未知引用和多候选不会猜测。
- 仓库工作区保留用户已有的未跟踪配置、文档压缩包和 IDE 文件，未加入提交。
