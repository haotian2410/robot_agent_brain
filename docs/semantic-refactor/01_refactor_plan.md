# Robot Agent Brain：OLS 目录感知、桌面语义与测试矩阵重构方案

审查基线：`main@1fc9fe9b2568672a9a5110a5ec749c1eb038bef9`  
审查日期：2026-11-03  
性质：**实施设计与待执行验收计划，不是已完成的代码或测试报告。**  
本文只要求修改 Brain 和必要的测试适配；不修改生产 OLS 资产包、不改变共享 Scene v1、不实现 Control/IK/MuJoCo/真实机械臂执行。

## 1. 本轮任务的三个明确目标

**目标 A：让首阶段 Qwen 看见完整、当轮有效的 OLS 资产目录，并直接选择可用资产。** 不再让模型先凭空翻译出 `cup`，再由 Python 猜成 `mug`；也不能把 `cup→mug` 写成永久规则。将来目录加入真正的 `cup` 后，显式请求 cup 应能选 cup。

**目标 B：固定桌面工作域。** 普通物体生成、方位放置、旋转、改色、平移等都在已绑定主桌面工作区内解释；不再询问“桌子右边是桌外还是桌面”。机械臂切换保持独立 `robot_config`。桌面语义简化不等于取消边界、支撑、碰撞、身份和回滚校验。

**目标 C：测试一行一种能力，变体是完整自然语言表达。** 资产 A/B 仍通过 seed 选取；每行可以继承某个前序行的已验证结果，也可以独立使用显式 fixture。同义改写与位置/角度/颜色变化都保留，但分别有正确的语义预期。

交付文件：
- `02_semantic_test_matrix.xlsx`：20 个功能行、115 条表达；前五行依次为生成、方位放置、旋转、改色、平移。
- `03_semantic_test_plan.json`：与表格同源的机器可读规范。
- `04_test_plan.schema.json`：规范文件结构校验。
- `06_test_runbook.md`：执行、继承、seed、断言和结果口径。
- `07_asset_roles_template.json`：动态角色池能力约束模板。
- `05_codex_task.txt`：短实施入口。
- `validate_spec.py`：仅校验本包结构/引用，不运行 Brain。

## 2. 最新仓库实际情况

以下是本次读取固定提交源码所得，不沿用旧版结论。

| 位置 | 已有实现 | 本轮需要改什么 |
|---|---|---|
| `models/task_understanding.py` 的 `TaskUnderstandingRequest` | 请求仅有 instruction；已有 v3 typed wire | 增加不可变目录快照、桌面上下文、紧凑场景上下文 |
| `pipeline.py::understand_turn` | 有 scene/dialogue，但只把 contextualized instruction 交给 Provider | 把资产目录和桌面契约以结构化字段传入，不塞进用户原话 |
| `models/qwen_http.py` | 第一阶段只发送 instruction；存在 replace/selector 的自然语言正则修复 | 发送完整 request；移除固定 cup/mug 名称修复和会改写语义的兜底 |
| 当前 clean v3 Prompt | 明确把 cup、coffee cup、杯子固定解释为 mug | 删除固定资产名等价式，改成“仅从本轮目录选择” |
| `scene/asset_resolver.py` | 名称/别名检索、类别、标签、默认样式、颜色覆盖 | 对新协议按已选 key 精确绑定；不重新解释自然语言名称 |
| `web/assets.py` | 有 OLS list/metadata 与本地库一致性检查 | 复用读取契约生成快照；补目录更新与几何就绪边界 |
| `batch_matrix.py::_instruction_variants` | 混合完整句子、裸值、关键词启发式 | v2 变体只接受完整模板；参数变化显式存字段 |
| `compile_matrix` | 构造多条分支后按 sample_count 循环取样 | 变体全覆盖 × 资产样本 × 重复次数分离，不能 sample=1 只测一句 |
| `batch_campaign.py` | 父指令拼接后按长度切片，父选择依赖阶段长度 | 显式记录 row-local instructions、父变体、父快照和角色绑定 |
| `config/batch_asset_roles.json` | 已有 object_a/b、placement_1/2、surface_1 | 保留角色名，候选从目录和能力约束派生；surface_1绑定实际桌面 |

可复核源码见文末 S01—S11。这里只做了源码核对；没有连接用户机器的 Qwen/OLS/Gateway，也没有重跑仓库 pytest。

### 两个尤其需要避免的旧问题

1. **目录接入之后仍运行硬编码 alias。** 这样 Qwen 选了 cup，Python 仍可能改成 mug，重构无效。
2. **表格写了很多变体但编译时只抽一条。** 当前流程的 sample_count 不是“每个变体重复次数”；新格式必须明确迁移，不能直接复用旧含义。

## 3. 冻结边界与兼容策略

保留：一次首阶段理解正常路径；scene_edit/scene_query/robot_task/robot_config 等既有任务种类；recipe/qwen 第二阶段规划；资产只读；current/original；单/双臂和 Profile；Commands；Gateway 租约、版本、摘要、原子提交及失败不发布旧命令。

新增协议建议命名 `task_understanding.v3.1`，测试规范命名 `brain-semantic-matrix.v2`。旧 v3/replay 在明确的兼容适配层读取；live 新协议不可悄悄退回基于名称猜资产。不要依赖 `model_construct()` 绕过新字段的正式验证。

测试包采用新矩阵格式，**当前仓库的 v1 batch-compile 不能直接作为 v2 运行器**。Codex 应先实现 importer/compiler/campaign，再使用此包。旧表格与 JSON sessions 保留兼容，不要求本次删除。

## 4. OLS 目录感知的第一阶段

### 4.1 数据流

```text
只读 OLS / 已验证本地索引
  → AssetCatalogSnapshot（完整目录 + revision + 就绪信息）
  → TaskUnderstandingRequest
  → Qwen：语义抽取 + 从目录选择新建/替换资产
  → Wire 结构校验
  → AssetChoiceValidator（同一revision内成员/类型/属性校验）
  → SceneReferenceResolver（绑定已有实例与桌面）
  → SceneEditor（几何、支撑、边界、碰撞）
  → Gateway原子提交
```

“第一轮”应理解为**每个用户 turn 的第一阶段理解调用**，不只是会话首句。当前 HTTP 调用无服务端会话记忆，不能只在 session 第一轮提供目录，随后期待模型自动记住。不要为了判断“是否 scene_edit”额外加一次 Qwen 分类；正常一次调用直接带目录，由模型自行路由。

### 4.2 目录来源与全量要求

现有 OLS 校验代码使用 `/list?type=model&uid=0`、robot/scene 类型列表及单项 metadata；应复用当前部署的真实协议，不臆造新 OLS API。

- 所有 model 的名称都进入 `model_catalog`；同名不同款式必须分别列出 key。
- robot 名称放独立 `robot_catalog`；可切换能力以 **已注册 RobotProfile** 为准，不等于“OLS 有机器人文件就一定能切换”。
- scene 模板另作 `scene_catalog`，不让 add 把模板误当物体。
- 不按老的 21/34 个数量写死，不只取手工角色池，不偷偷 top-k。
- 每项可标注 `selectable_for_add`、`availability_reason`，全量展示与可执行资格分开。
- 目录接口确有分页时才按真实分页协议拉全量，测试检查 total/条数；没有分页字段就不要伪造参数。

建议新增 `contracts/asset_catalog.py`、`semantics/asset_catalog_context.py`；给实际 AssetLibraryPort/adapter 增加显式 `catalog_snapshot()` 或同等接口，不让业务模块读取 adapter 私有 `_assets`。

### 4.3 发送给模型的最小信息

建议每个 model 含：
`asset_key`、`name`、真实存在的 display_name/aliases、category、tags、颜色/款式标签、可选择状态。
没有的字段为空，不由 Python 编造描述。尺寸/边界/碰撞网格/URDF/绝对磁盘路径不需要整包放进 Prompt。

`asset_key` 使用带命名空间的目录身份，例如 `model:900001`。这是**从请求给出的枚举中选择已有资产身份**，不是生成场景实例 ID。真正 `MetadataRef` 仍由 Python 输出，保持原有 Scene 协议。

示意请求（900001 仅是隔离测试示例，不代表真实 OLS）：

```json
{
  "instruction": "增加一个杯子",
  "workspace": {
    "mode": "tabletop",
    "interaction_mode": "tabletop_edit",
    "default_support": "primary_table",
    "coordinate_convention": "x_right_y_front_z_up"
  },
  "asset_catalog": {
    "revision": "sha256:...",
    "models": [
      {"asset_key":"model:900001","name":"mug","tags":["handle"],"selectable_for_add":true}
    ],
    "robots": [],
    "registered_profiles": []
  },
  "scene_context": {
    "basis": "current",
    "primary_table_available": true,
    "objects": []
  }
}
```

上下文中的目录名称/描述属于数据，不是可覆盖系统规则的指令；长度需有界并正确 JSON 编码。

### 4.4 模型输出与 Python 绑定

建议新增 `SceneEditWire.asset_choices`，不要将资产身份塞入共享 Scene 的新顶层字段，也不要将所有目录资产声明为本轮 entities：

```json
{
  "protocol_version": "task_understanding.v3.1",
  "status": "accepted",
  "turn_kind": "scene_edit",
  "scene_edit": {
    "scene_basis": "current",
    "entities": [
      {"entity_id":"vessel","semantic_name":"mug","category":"container","count":1,"quantity_mode":"single"}
    ],
    "asset_choices": [
      {"entity_id":"vessel","asset_key":"model:900001"}
    ],
    "relations": [],
    "operations": [
      {"operation":"add","target":"vessel","relation":"on","reference":"table","placement_hint":"any"}
    ]
  }
}
```

这是**核心片段，不是完整顶层 wire 示例**；Codex 必须按最终 schema 生成完整示例并自动校验，避免再次产生“Prompt 示例缺 required 字段”。

规则：
- add target 与 replace.replacement_entity 必须有且仅有一个资产选择。
- 修改/移动/删除已有实例不按目录重新选资产，不因目录更新把原物体变成别的资产。
- 同一个实体多步复用，不重复生成不同选择。
- 引用 table/basket 等已有对象不要求 asset_choices；与新建资产角色严格区分。
- `asset_key` 必须是请求快照中的 model 成员；Qwen不能自行拼路径、下载URL、object_id_in_scene。
- 对名称和 key 冲突直接报错，不以名字覆盖 key，也不偷偷反过来修名字。
- Python 保留类别/硬属性/权限/几何的确定性校验，但不再把 `cup` 改写 `mug`、把 `box` 改写 `basket`。
- 对 key 的 schema 可使用当轮枚举，并保留运行时成员检查。服务端不支持动态 enum 时仍做严格后验校验，不能无约束通过。

### 4.5 mug/cup 与款式策略

| 目录与请求 | 应有行为 |
|---|---|
| 仅mug；用户说“杯子” | Qwen根据目录含义选择mug，保留选型证据 |
| mug与cup都有；用户明确“cup” | 优先精确目录名cup，不经过cup→mug |
| mug与cup都有；用户说“马克杯” | 选择mug对应项 |
| 多个普通篮子、未限定款式 | 在配置允许的等价款式内自主选择；记录“未指定款式”的选型策略，不强迫所有无款式请求澄清 |
| 用户明确白色编织篮子 | 不能因默认蓝篮子易放而覆盖用户属性 |
| 只有带把手mug，用户要无把手杯 | 不满足硬条件，应澄清或无匹配，不丢弃条件 |
| 新增cup但缺必要几何/缓存 | 报asset_not_ready一类明确配置错误，不能自动回退mug |
| 没有任何杯类 | 明确无候选，不换成任意容器 |

建议 `unspecified_style_policy=allow_model_choice` 用于 **创建/替换新资产**。它不适用于“删除哪一个现有篮子”之类实例歧义；现有实例多个候选仍需 selector 或澄清。不能声称仅凭目录就能保证模型选型永不出错，必须用下述目录演进测试衡量。

### 4.6 快照与热更新

一次 turn 固定同一个 catalog_revision。摘要由稳定排序后的类型、身份、名称、真实标签/语义版本、可用状态构造；不包含机器特定绝对路径。

每轮开始检查目录变化，新增/删除名称必须进入新快照；元数据/几何更新通过只读同步与派生缓存就绪流程处理。现有 `check_ols` 会核对本地与远端，因此**必须同时解决本地 adapter 缓存更新与几何缓存覆盖**，不能只把远端名字喂给Qwen而本地resolve仍不认识。

严格模式下，对外发布新revision之前完成索引一致性和就绪校验。若OLS缺统一revision，按已验证索引/元数据内容计算digest；不得拿“缓存30秒”声称“下一轮必定可见”。若中途目录发生冲突，拒绝/重试该turn须显式记录；不能用新目录解释旧响应。

### 4.7 清理补丁

全仓搜索并移除 live 路径中的固定 `cup→mug`、`coffee_cup→mug`。用户真实提供的资产 aliases 可以作为目录数据保留，但不能成为跨资产无条件替换。

`_repair_explicit_replace`、`_repair_explicit_selector_clarification` 不得继续根据几个硬编码名词生成新任务、覆盖澄清或丢掉否定/原始场景/后续子句。只保留不改变语义的格式适配（旧字段名等）。有明确遗漏仍返回精确错误；首轮通过率与修复后通过率分开统计。

## 5. 桌面工作域的唯一契约

### 5.1 运行上下文，不只是一段Prompt

新增可配置且可记录的 `WorkspaceSemanticPolicy`：
- `mode=tabletop`
- `interaction_mode=tabletop_edit`
- `primary_table` 的真实已验证绑定
- 桌面中心与已约定轴向
- 默认平面、默认旋转轴、位移/模糊尺度策略版本

没有 scene 时沿用已配置bootstrap创建主桌面平台，不让Qwen新增桌子。已有场景必须有可靠主桌面绑定；不能任意挑第一张桌子。桌面元数据存在但支撑几何不可信时仍明确阻塞。

桌面政策下，“增加A”与“在桌子上增加A”在语义上统一为on primary_table；缺省来源写成 `source=workspace_default`，并非模型凭空假设。

### 5.2 方位映射冻结

沿用已有项目约定：**X向右/东，Y向前/北，Z向上**。桌面“右上角”中的上是平面前/北，不是离开桌面向Z上移动。此定义不依赖当前相机朝向。

| 说法 | region |
|---|---|
| 右上角 / 东北角 / 右前角 | right_front |
| 左上角 / 西北角 / 左前角 | left_front |
| 右下角 / 东南角 / 右后角 | right_back |
| 左下角 / 西南角 / 左后角 | left_back |
| 桌子右边 / 东侧 / 右半边 | right_half |
| 桌子左边 / 西侧 / 左半边 | left_half |
| 桌子前边 / 北侧 | front_half |
| 桌子后边 / 南侧 | back_half |
| 中间 / 正中央 / 中心 | placement_hint=center |

针对“桌子右边”删除旧的“也许是桌外地面”解释。针对“香蕉右边”，仍是相对香蕉的right_of，但候选位置必须在主桌面工作区。

角区可以是区域约束，不强制落在桌沿角点。中心是实际主桌面几何中心的硬约束，不得在工作区裁剪后静默换成裁剪区域中心；中心不可行则拒绝。

### 5.3 路由与操作

在 `tabletop_edit` 上下文中：
- “放置/生成/增加A”是新增编辑。
- “把已有A放到B旁边/放进B”是编辑位置/容器关系，不因为“放”而触发机器人。
- “让机械臂抓取/执行搬运”才走明确机器人任务路由；保留执行能力校验。
- “换机械臂/切换单双臂”走robot_config，不把机械臂当普通桌面物体。
- 创建/编辑与明确机器人执行混合时保留现有完整性边界，不执行一半。

已有robot_task API不删除，本次普通编辑测试统一带tabletop_edit上下文，避免不同表达反复询问主体。

### 5.4 保留的安全与真实歧义

始终保留：桌面footprint、support、workspace、AABB/几何碰撞、容器内部几何、scalable许可及范围、组件引用/RobotDriver/Profile、current/original快照、原子回滚和Gateway提交。

“都在桌面”不表示所有物体Z相同：模型底部偏移、旋转后最低点、桌面高度、托盘/容器支撑由Python计算；不硬写Z=0。支持的容器/托盘关系仍在桌面工作域内。

以下仍需要澄清：多个无法区分的现有实例；“最远”无参照；替换未指明新对象；缺可靠几何证据。明确越界命令不偷偷改写；当前矩阵不以桌外任务为常规测试。

### 5.5 near与nearest不能混成一个概念

选择条件“靠近B的A”是邻近范围过滤；“离B最近的A”是排序取极值。两个A都在邻近范围时，不能未经数量/指代约束就自动只选最近一个。`neighbors`查询、near位置生成、near选择和nearest选择各有清晰语义与oracle，避免为了让批测通过而改变用户意思。

## 6. 测试矩阵 v2：一行能力、多个完整表达

### 6.1 表格结构

`matrix`：每个功能一行，维护case_id、父行、父变体策略、无父时fixture、角色槽位、asset_samples、repeats_per_variant。首五行严格为：
T01生成；T02区域放置；T03旋转；T04改色；T05不同方向平移。

`variants`：每条表达一行，带稳定variant_id、所属case_id、equivalence_group、完整模板、expected JSON、expected_outcome与precondition。主表展示表达预览，完整编辑以variants表为准；不要维护两套独立的表达真值。

其他sheet：使用说明、角色与基线、方向契约、回归断言、运行配置、结果模板、源码依据。

### 6.2 三个维度必须正交

1. `asset_seed`：只控制角色对应资产与允许的seed_parent选择。
2. `variant_id`：控制自然语言表达与本条真实语义参数。
3. `repeat_index`：对同一基线/资产/表达重复调用，以测模型稳定性。

同义改写必须在同一资产与基线上比较。不能把不同资产大小、不同父状态、不同位置导致的差异误算成语言差异。

一轮预算为：
`Σ(每行启用变体数 × asset_samples × repeats_per_variant × 实际展开父分支数)`。
同一行sample=1仍要运行其所有启用变体；不允许再用sample_count截断变体列表。选择子集必须显式标记variant_selection并报告覆盖率。

### 6.3 同义改写 vs 参数变化

“增加一个A / 在桌子上增加一个A / 生成一个A”同组，canonical语义应相同（允许无关实体符号名等标准化差异）。

“右上角 / 左下角 / 中心 / 东南角”不是四句同义话：它们属于一个能力行下四个参数组；每组又可有同义表达。判定应核对各自region/hint，不能要求都生成相同JSON。

旋转的顺/逆时针、改色的蓝/绿/红、平移的东西南北同理。`variant_kind`只是分类，实际正确性以本条expected和独立oracle为准。

### 6.4 完整模板，禁止猜词

v2 `instruction_template`始终是一句完整指令，可使用：
`{object_a}`、`{object_b}`、`{placement_1}`、`{placement_2}`、`{surface_1}`。
颜色、方向、距离变化也可以显式给参数，但不得再把裸值同时塞给color/direction/object_a。

模板名称由运行时角色display phrase渲染；未知显示名回退真实目录名称，不维护与生产选型冲突的庞大中文翻译字典。专门的“杯子/mug/cup”用例保留原词，不能被test compiler预先改写成正确答案。

## 7. 行间继承、基线与角色身份

### 7.1 ID不可混用

- case_id：T01等表格行身份；
- variant_id：T01.V01等表达身份；
- asset_key：model命名空间下的库身份；
- scene_id/object_id_in_scene：运行时场景实例身份。

用户在表格填写的是父case/variant，不手填场景物理ID。运行器自动从父run结果读取快照及角色绑定。

### 7.2 默认继承示例

```text
T01 生成A ──→ T02 新增B于指定区域
         ├─→ T03 旋转A
         ├─→ T04 改色A
         └─→ T05 移动A
```

T03可改成继承T02，T04可改成继承T03。每行只有一个可选直接父行；多前置合流不是本期目标。父必须是前序已定义行，编译时检查缺失、环和角色需求。

### 7.3 父分支选择与成功门控

支持：
- `fixed`：明确parent_variant_id，推荐可定位基准；
- `seed`：从按稳定ID排序的合格父run中，用稳定派生seed选择；
- `all`：全部合格父run × 当前全部变体，必须记录展开数。

父合格条件不是 `status=passed` 一个字段，而是该父case预期语义/终态全部通过且拥有子行所需角色。父返回正确澄清不能提供“已生成A”的前置。不得把safe rejection或截图存在当父生成成功。

### 7.4 快照隔离

每个 child variant从同一选定父快照创建自己的分支session；兄弟分支相互隔离，不累积旋转/改色/新增。父快照不可修改。

保存 `parent_run_id`、`parent_variant_id`、`parent_scene_digest`、`baseline_digest`、role_bindings和ID remap。如果Gateway要求新scene/instance ID，使用已有可靠allocator/remapper；角色通过映射更新，不能伪造ID复用。

新分支session的original按其已确认基线冻结；祖先original只作为lineage证据保留，不偷换含义。测试original根快照的case用显式fixture构造，不用父行ID代替scene_basis。

### 7.5 不继承不等于没有物体

T03/T04/T05.parent=NONE时，分别使用显式single_a_center等fixture搭建前置。fixture搭建不是被测Qwen语义，不计入本行首阶段成功率；保存其资产和场景快照。

若用户选了一个缺A的父行，不自动补A、不偷偷回放T01；报告fixture_incompatible。表格中的fixture_id只在无父时生效，除非run profile明确覆盖，避免暗中改变继承状态。

### 7.6 中心放置的特例不是绕过安全

T01“增加A”可能把A放在中心；T02继承它再新增B到同一中心自然会撞。三者必须分开：
- T02正例：中心为空，应该成功；
- T17负例：中心确实冲突，应该安全拒绝且场景不变；
- 无法满足T02正例前置：fixture_incompatible，不计语言失败，也不计成功。

本包附 `center_empty` run profile：T02取消父行，独立空桌面验证区域/中心正例。不得移动A来伪造“完全继承”。

## 8. seed与目录变化的可复现性

不要依赖Excel物理行号、集合迭代顺序、`len(stages)`或全局PRNG消费顺序。使用稳定case_id/role/asset_sample_index构造派生seed，例如SHA256的固定字节截取；编码、排序和版本写进规范。

同一个根case同一asset_sample的所有变体共享A/B；子行继承既有角色，不重新抽A，新增角色B才抽。存在已有B时继续使用它；替换操作后A绑定到新的实际实例与名称，后续占位符依据快照重建，不残留apple旧名。

每次记录：root seed、派生seed算法版本、catalog_revision、候选key排序、选中key/display name、fixture hash、workspace policy版本、Prompt/schema hash、模型与推理参数。不同seed可能恰好抽中相同资产，不能断言“换seed必换物体”；目录变化可以改变结果，但必须清楚标识revision不同。

## 9. 独立oracle与结果口径

Prompt通过不是任务正确。测试层至少分三层：
1. raw模型输出/路由/目录选择；
2. canonical语义与对象角色；
3. 最终Scene/query/profile状态。

不要复用被测方向解析器来证明方向正确。测试fixture保存独立坐标轴与预期表；根据前后Scene计算位置/旋转/颜色/数量，比较预期资产key和角色ID。

建议Scene数值容差配置为位置1e-4m、角度0.05度（测试默认，可按序列化精度调整，不代表真实机械臂精度）。旋转比较矩阵或四元数等价（q/-q等价），不能只靠截图看球体。位置中心检查物体指定pivot/中心契约，footprint另检；近邻距离需统一报告XY原点距离或几何边界距离，不能二者混报。

状态：
- passed：本条预期语义与终态通过；
- failed_assertion：系统返回成功但做错；
- failed_protocol/runtime：模型协议或程序异常；
- expected_clarification：确实缺信息并无副作用；
- expected_safe_rejection：确实不可行且匹配错误码、Scene/版本不变；
- blocked_fixture：前置/目录/profile/几何不满足；
- skipped_parent_not_satisfied：父结果不能提供前置；
- not_run：未执行。

以上每类独立统计。“Qwen输出澄清”不能一律算passed，桌面规则已经提供答案却再次追问，应是语义失败。更不能把22条定向复测当成旧554轮矩阵全部通过。

结果至少含：case/variant/equivalence group、完整渲染指令、seed/role mapping、目录revision、父run与基线、模型原始JSON、规范化JSON、修复记录、选中资产key、阶段错误path、前后Scene、独立断言、实际outcome、未执行标记、截图与Scene身份。截图缺失不得以旧图补齐。

## 10. 按提交拆分实施

| 阶段 | 重点修改 | 必须新增的测试 |
|---|---|---|
| C0 基线冻结 | 保存旧v1样例/当前schema，建立新规范导入校验 | 20行/115变体结构合法；旧矩阵仍可读 |
| C1 Catalog快照 | contracts/asset_catalog.py、实际adapter/port、web/assets.py、config/application | 全量目录；model/robot同ID；新增/删除；原子revision |
| C2 首阶段请求 | TaskUnderstandingRequest、pipeline.py、qwen_http.py、replay/fake provider | 普通调用一次；目录与桌面上下文送入实际HTTP请求 |
| C3 精确资产绑定 | SceneEditWire/Plan.asset_choices、AssetChoiceValidator、asset_resolver/editor/bootstrapper | mug-only、cup+mug、款式/颜色硬条件、未知key、旧catalog |
| C4 桌面契约 | WorkspaceSemanticPolicy、prompt、domain policy、reference/layout/editor | 四角/四向/中心；bare-add同义；无桌外澄清；保留安全拒绝 |
| C5 Matrix v2 | batch_matrix.py、新模型与schema、batch CLI、roles模板 | 完整句模板；变体×样本×重复；稳定ID；无漏跑 |
| C6 Campaign v2 | batch_campaign.py、batch_service.py、快照/role sidecar、报告 | 父快照分支、all/fixed/seed、无父fixture、兄弟隔离 |
| C7 真模型验收 | Prompt/模型版本固定；独立oracle；报告导出 | 首五行全变体、目录演进、27个不变量、全量pytest |

C1—C4先用Mock OLS/MockTransport验证，再接真实Qwen。C5/C6是测试基础设施，不要用它们修改生产任务语义。C7未具备本地服务条件时必须列“未验证”，不得编造通过数量。

### 建议新增测试文件

`test_asset_catalog_context.py`、`test_asset_choice_validation.py`、`test_catalog_evolution.py`、
`test_tabletop_semantic_policy.py`、`test_tabletop_oracles.py`、
`test_batch_matrix_v2.py`、`test_batch_campaign_snapshots.py`、
`test_batch_report_semantics.py`。

原有`test_qwen_http.py`应检查请求包含完整目录，而非只检查返回结果；Prompt中的完整JSON示例必须加载实际wire schema逐个验证。

## 11. Prompt改造原则与精简规则片段

这不是让你再叠加一大段v4补丁。保留唯一运行时Prompt来源，把资产固定名称与桌外歧义章节**替换**掉，并让样例与实际schema自动对齐。

核心规则可以压缩为：

> 你接收instruction、asset_catalog、workspace和scene_context。新建或替换模型只能选择本轮catalog中给出的model key；具体资产名以catalog为准，不能固定把cup归为mug。普通任务处于桌面编辑域，省略桌面仍表示primary_table；桌子右边/右上角等均是桌面内部位置。右/东为+X，前/北为+Y，右上=东北，右下=东南。已有对象按scene/context选择，不因catalog变化重新选资产。用户的数量、颜色、款式、顺序和否定必须保留。只输出契约JSON，不输出坐标、实例ID、轨迹和执行成功结论。只有真实缺失信息才澄清；几何可行性由Python验证。

角色/双臂/原始快照等既有条款不得因缩短Prompt被删除。不要直接将本段txt整体替换现有完整Prompt，否则会丢协议字段。

## 12. 完成标准

上线本次方案前，应同时满足：

- 实际HTTP请求包含完整当前OLS model目录与独立robot/profile信息；新cup出现后不被旧alias覆盖。
- 新建/替换从模型选择的合法key绑定；Scene导出字段不变；OLS包未被改写。
- 首五功能行所有启用表达均被展开，并在相同资产/基线下运行；seed不替代语义变体。
- 四角与中心各有独立断言；“桌子右边”在桌面内；碰撞/超界不被偷偷平移/裁剪。
- 任一行可选前序父行或NONE；明确父变体/快照；子变体不污染父/兄弟；没有长度切片或伪造默认查询。
- 报告区分真实成功、正确拒绝、错误澄清、前置阻塞、级联跳过；未调用Control。
- 全量单元测试、Mock协议测试与真实Qwen测试分别给出命令、计数、失败证据、未验证项。

## 源码依据（固定到审查提交）

- **S01 首阶段请求与 Wire Schema**：TaskUnderstandingRequest 目前只有 instruction。
  https://github.com/haotian2410/robot_agent_brain/blob/1fc9fe9b2568672a9a5110a5ec749c1eb038bef9/src/robot_agent_brain/models/task_understanding.py
- **S02 Qwen HTTP 与修复逻辑**：首阶段只发送 instruction；修复函数含 cup→mug 等固定映射。
  https://github.com/haotian2410/robot_agent_brain/blob/1fc9fe9b2568672a9a5110a5ec749c1eb038bef9/src/robot_agent_brain/models/qwen_http.py
- **S03 运行时任务理解 Prompt**：把 cup/mug 固定合并；仍含路由和空场景通用规则。
  https://github.com/haotian2410/robot_agent_brain/blob/1fc9fe9b2568672a9a5110a5ec749c1eb038bef9/src/robot_agent_brain/models/prompt_templates/task_understanding_clean_v3.txt
- **S04 理解调用入口**：BrainPipeline.understand_turn 构造仅含 instruction 的请求。
  https://github.com/haotian2410/robot_agent_brain/blob/1fc9fe9b2568672a9a5110a5ec749c1eb038bef9/src/robot_agent_brain/pipeline.py
- **S05 资产选择器**：按别名、name/category 查找，并处理默认款式/颜色覆盖。
  https://github.com/haotian2410/robot_agent_brain/blob/1fc9fe9b2568672a9a5110a5ec749c1eb038bef9/src/robot_agent_brain/scene/asset_resolver.py
- **S06 资产内部视图**：BrainAssetView 提供类型、库ID、语义名、标签等；不改共享 Scene。
  https://github.com/haotian2410/robot_agent_brain/blob/1fc9fe9b2568672a9a5110a5ec749c1eb038bef9/src/robot_agent_brain/contracts/asset_library.py
- **S07 OLS 校验适配**：现有 /list?type=...&uid=0 和单项元数据读取；与本地库核对。
  https://github.com/haotian2410/robot_agent_brain/blob/1fc9fe9b2568672a9a5110a5ec749c1eb038bef9/src/robot_agent_brain/web/assets.py
- **S08 矩阵编译器**：variants 可被当成句子或占位符值；sample_count 对分支循环取样。
  https://github.com/haotian2410/robot_agent_brain/blob/1fc9fe9b2568672a9a5110a5ec749c1eb038bef9/src/robot_agent_brain/batch_matrix.py
- **S09 继承 campaign**：按父指令长度切片；成功父分支选择依赖阶段数量。
  https://github.com/haotian2410/robot_agent_brain/blob/1fc9fe9b2568672a9a5110a5ec749c1eb038bef9/src/robot_agent_brain/batch_campaign.py
- **S10 矩阵使用文档**：已提供 batch-compile/batch-campaign 与 seed_parent/all_parents。
  https://github.com/haotian2410/robot_agent_brain/blob/1fc9fe9b2568672a9a5110a5ec749c1eb038bef9/docs/batch_matrix_testing.md
- **S11 现有角色池**：object_a/object_b、placement_1/2、surface_1 已存在。
  https://github.com/haotian2410/robot_agent_brain/blob/1fc9fe9b2568672a9a5110a5ec749c1eb038bef9/config/batch_asset_roles.json
