# 语义变体测试文档与执行说明

本包是待实现、待执行的测试规范；所有结果初始为 `not_run`。不能将本文或表格中的预期当作真实Qwen结果。
审查基线：`main@1fc9fe9b2568672a9a5110a5ec749c1eb038bef9`。

## 1. 如何编辑表格

主工作表 `matrix` 一行就是一个功能，不是一整个超长session：
1. T01 基础放置生成。
2. T02 方位区域放置。
3. T03 旋转。
4. T04 改色。
5. T05 朝不同方位平移。

在主表改 `parent_case_id`，填写某个前序功能行ID，或 `NONE`。`parent_variant_policy=fixed` 时同时填写父变体，如 `T01.V01`；`seed` 和 `all` 时parent_variant_id留空。无父时使用本行fixture_id。不要把实际场景实例ID填进parent列。

完整语句在 `variants` 工作表编辑：每条必须有case_id、variant_id、equivalence_group、完整instruction_template和expected_json。主表中的预览及variant_count为展示/计算列，**不是第二套可执行表达定义**。

`{object_a}`、`{object_b}`仍然是用户要求保留的占位符。它们由资产seed绑定，但不是传给Qwen的字面“物体A”：发送前渲染为实际用户可见名称，如苹果、香蕉或目录提供的名称。泛称“杯子”的专项用例故意不预先替换成mug。

## 2. 同义与不同语义

同义组示例：T01
- 增加一个{object_a}
- 在桌子上增加一个{object_a}
- 生成一个{object_a}

三者均应生成一个A，落在主桌面；不能因省略“桌面”就询问桌内/桌外。

参数组示例：T02
- 右上角 / 东北角 / 右前角 → right_front。
- 左下角 / 西南角 / 左后角 → left_back。
- 中间 / 正中央 / 中心 → center硬约束。
- 东南角 / 右下角 / 右后角 → right_back。

同一组表达应等价；不同组只能共享能力和基线，不要求输出同一个位置。最终位置允许在合法角区内不同，不要求每个说法产生完全相同XYZ。

## 3. 继承的推荐方式

默认T02/T03/T04/T05都继承T01.V01，这样不会让测试旋转被上一轮改色、碰撞或挪动影响。
需要链式会话时可以改为T01→T02→T03→T04；此时每个variant依然从它选中的父快照重新fork，不能把同一行的多个变体串起来顺序执行。

父run必须提供符合预期的场景和角色。父生成返回澄清而未创建对象，即使框架把“正确澄清”判为测试pass，也不能拿它做生成成功的前置。

取消继承时：
- 生成行使用workspace_empty。
- 旋转/改色/平移使用single_a_center。
- 极值选择/查询使用three_a_one_reference。
- 替换使用single_a_center。
- 机器人切换使用registered_robot_profiles。

fixture搭建单独记录，不通过隐藏Qwen指令做准备，不计入模型表达准确率。

## 4. seed规则

`asset_seed`只改变角色选材与显式seed父分支选择。一个根case同一asset_sample下，各个语义变体共用相同物体；不能每句换一个资产后仍声称在比较同义稳定性。

manifest记录实际选中的asset_key、可读名称、catalog_revision。修改seed不承诺必然换资产，小池可能碰巧相同。改变行顺序不应改变稳定case ID对应的采样结果。

父行的既有角色A不能在子行重新采样；替换以后，A绑定应更新为替换后的新实例，渲染后续指令时读取真实当前名称。

`asset_samples`是每个功能行的资产组合样本数。`repeats_per_variant`是每句同一参数的重复次数；`variant_selection=all`表示全部启用表达都要跑。旧版sample_count迁移必须显式说明，不得沿用“抽几个变体”的含义。

## 5. 本包的执行层

- e2e_scene：模型、语义、资产绑定、几何、Scene提交与独立oracle。
- llm_contract：T19目录演进；隔离Mock OLS/目录快照。验证模型选择与解析，不提交虚构资产到生产OLS。
- config_contract：T20 profile切换；桌面物体保持，不执行轨迹。

T19的mug-only/cup+mug/删除mug场景是**人工隔离夹具**，不是对当前真实资产库的断言。真实OLS未具备所需条件时标blocked_fixture，绝不修改生产库来凑测试。

## 6. 运行配置

`default`：按主表默认继承关系运行。
`center_empty`：仅运行T02，取消继承，使用空桌面，保证中心放置正例基线不被T01生成物体占用。
`independent_first_five`：首五行全部独立搭建前置，用于定位语言与功能错误。
`chain_example`：展示T01→T02→T03→T04继承。

默认配置下若T01让A占住中心，T02中心正例不得自动判安全拒绝为“通过”。应明确前置不可行，并在center_empty配置覆盖这个正例。T17另测真实中心冲突。

## 7. 每类操作的独立终态断言

| 功能 | 检查项 |
|---|---|
| 新增 | 新对象数、asset_key/MetadataRef对应、绑定主桌面、用户属性、非目标不变 |
| 区域 | 正确角区/半区；center对准实际桌面中心；完整footprint在工作区 |
| 旋转 | 目标实例不变；正确角度/轴/旋转方向；矩阵/四元数等价检查；非目标不变 |
| 改色 | 目标实例的颜色覆盖正确；选择颜色与目标颜色分开；位置/资产不变 |
| 平移 | 差分位移正确；东西南北映射正确；距离单位正确；方向不从相机视角猜 |
| 相对位置 | 目标与参照角色未互换；关系成立且桌面合法；near没有丢Z |
| 极值选择 | 从fixture真实候选排序；只选所需数量；并列不可任取 |
| 缩放 | 倍率/模式正确；可缩放许可与范围；几何可行；原子提交 |
| 替换 | 删除旧实例、生成新实例；资产由目录选择；角色映射更新；不复用已退役ID |
| 查询 | 对象集合/计数/距离与fixture计算相符；原Scene不变 |
| 原始场景 | 基于冻结original派生；original哈希不变；不是误改current |
| 安全拒绝 | 事前确有不可行证据；错误码匹配；Scene、版本、原始快照与角色映射不变 |
| 机械臂切换 | 使用注册Profile；revision正确；普通物体/桌面保持；无Control执行 |

极值距离在本包中明确为XY世界原点投影距离，既有near边界查询可使用几何距离但必须另名记录，不混用。位置容差和角度容差是测试可配置值，不能拿来宣称真实机器人精度。

## 8. 推荐实施后的测试次序

1. 结构测试：读取20个case、115条variant、fixture/parent引用合法；全部Prompt完整示例通过真实schema校验。
2. MockTransport：检查实际第一阶段请求含目录和workspace，强制提供正确/错误asset key与属性组合。
3. 生产组件离线测试：geometry、binding、reference、original、snapshot fork与批量编译计数。
4. 真实Qwen首五行：一组资产先跑所有表达；再增加asset_samples与重复次数。
5. T19隔离目录演进与27个不变量。
6. 完整多轮campaign、预设场景与旧兼容批次。
7. 保留原项目全量pytest、wheel smoke、已有单/双臂回归。任何实际未执行项单列。

下列是**需Codex新增的CLI目标示意，不是当前可直接运行的命令**：

```bash
robot-brain batch-compile --matrix-version 2   --matrix docs/semantic-refactor/02_semantic_test_matrix.xlsx   --kind generated_edit --asset-roles docs/semantic-refactor/07_asset_roles_template.json   --seed 20261103 --run-profile independent_first_five   --output var/semantic-v2/compiled.json

robot-brain batch-campaign --matrix-version 2   --matrix docs/semantic-refactor/02_semantic_test_matrix.xlsx   --asset-roles docs/semantic-refactor/07_asset_roles_template.json   --seed 20261103 --run-profile default   --output-dir var/semantic-v2/campaign
```

如果Codex选择保留旧CLI名称，可使用新flag或按format_version分派，但不能让旧v1 importer误读v2表格。
本包即时可运行的只有 `python validate_spec.py`；它不连接任何用户服务、不执行模型或机器人。

## 9. 结果填写与发布

表格“结果模板”是空白记录模板，预填只有测试ID、模板、预期与not_run，不能拿它当结果报告。
实际运行新增run_id后记录完整渲染指令、asset_seed、catalog_revision、角色、父run、基线摘要、实际结果、错误、oracle、截图和证据路径。

不要：
- 只凭scene_updated/answered判业务正确；
- 将每次clarification都算成功；
- 将任何失败都算安全拒绝；
- 把跳过当成独立失败；
- 覆盖首次失败只保留重试成功；
- 把仅修复后通过当作Qwen原始通过；
- 用旧截图填新任务；
- 用模型的asset choice作为它自己的正确答案。

需要分别报告：原始首阶段协议通过率、目录选型正确率、同义组一致性、终态正确率、正确澄清/安全拒绝、fixture阻塞、父依赖跳过、模型调用/修复次数、输入/输出token。所有比例给分子分母，不把未运行记录放进模型准确率分母。

## 10. 功能行索引


### T01 基础放置／生成（5 条表达）

默认父行：NONE；独立基线：`workspace_empty`；执行层：`e2e_scene`。

同一资产seed下所有表达生成同一资产、同一数量；位置允许桌面内任意合法空位。

- `T01.V01` 增加一个{object_a} → `add_one_a` / `scene_updated`
- `T01.V02` 在桌子上增加一个{object_a} → `add_one_a` / `scene_updated`
- `T01.V03` 生成一个{object_a} → `add_one_a` / `scene_updated`
- `T01.V04` 在桌面上放置一个{object_a} → `add_one_a` / `scene_updated`
- `T01.V05` 给场景添一个{object_a} → `add_one_a` / `scene_updated`

### T02 桌面方位放置 B（12 条表达）

默认父行：T01；独立基线：`single_a_corner`；执行层：`e2e_scene`。

右上/左下/中心/东南各为不同语义组。中心被父行A占据时不得硬算成功；用center_empty配置复测中心正例。

- `T02.V01` 在桌子右上角生成一个{object_b} → `region_ne` / `scene_updated`
- `T02.V02` 在东北角增加一个{object_b} → `region_ne` / `scene_updated`
- `T02.V03` 在桌面右前角放一个{object_b} → `region_ne` / `scene_updated`
- `T02.V04` 在左下角放置一个{object_b} → `region_sw` / `scene_updated`
- `T02.V05` 在西南角生成一个{object_b} → `region_sw` / `scene_updated`
- `T02.V06` 在桌面左后角加一个{object_b} → `region_sw` / `scene_updated`
- `T02.V07` 在桌子中间加一个{object_b} → `region_center` / `scene_updated`
- `T02.V08` 在桌面正中央生成一个{object_b} → `region_center` / `scene_updated`
- `T02.V09` 把一个{object_b}生成在中心位置 → `region_center` / `scene_updated`
- `T02.V10` 在东南角加一个{object_b} → `region_se` / `scene_updated`
- `T02.V11` 在右下角放置一个{object_b} → `region_se` / `scene_updated`
- `T02.V12` 在桌面右后角生成一个{object_b} → `region_se` / `scene_updated`

### T03 旋转 A 的不同说法（8 条表达）

默认父行：T01；独立基线：`single_a_center`；执行层：`e2e_scene`。

从桌面正上方朝下观察；逆时针=+Z角度，顺时针=-Z。旋转不新增或换资产。

- `T03.V01` 把{object_a}逆时针旋转九十度 → `rotate_ccw90` / `scene_updated`
- `T03.V02` 将{object_a}向左转四分之一圈 → `rotate_ccw90` / `scene_updated`
- `T03.V03` 让{object_a}绕桌面竖直轴正向旋转90度 → `rotate_ccw90` / `scene_updated`
- `T03.V04` 把{object_a}顺时针转九十度 → `rotate_cw90` / `scene_updated`
- `T03.V05` 将{object_a}向右转四分之一圈 → `rotate_cw90` / `scene_updated`
- `T03.V06` 让{object_a}绕Z轴负向旋转90度 → `rotate_cw90` / `scene_updated`
- `T03.V07` 把{object_a}逆时针转半圈 → `rotate_halfturn` / `scene_updated`
- `T03.V08` 将{object_a}绕Z轴旋转180度 → `rotate_halfturn` / `scene_updated`

### T04 改色 A 的不同说法（8 条表达）

默认父行：T01；独立基线：`single_a_center`；执行层：`e2e_scene`。

目标颜色只能进入属性更新，不能反过来把目标筛选成已具有该颜色的物体。

- `T04.V01` 把{object_a}改成蓝色 → `color_blue` / `scene_updated`
- `T04.V02` 将{object_a}的颜色设为蓝色 → `color_blue` / `scene_updated`
- `T04.V03` 给{object_a}换上蓝色 → `color_blue` / `scene_updated`
- `T04.V04` 把{object_a}变成绿色 → `color_green` / `scene_updated`
- `T04.V05` 将{object_a}改为绿色 → `color_green` / `scene_updated`
- `T04.V06` 把{object_a}设成红色 → `color_red` / `scene_updated`
- `T04.V07` 把{object_a}的外观颜色改成红色 → `color_red` / `scene_updated`
- `T04.V08` 把{object_a}颜色设为#3366CC → `color_hex_3366CC` / `scene_updated`

### T05 朝不同方位平移 A（10 条表达）

默认父行：T01；独立基线：`single_a_center`；执行层：`e2e_scene`。

厘米统一换算米；东=右、北=前、南=后；模糊幅度交现有Python策略，不由Qwen猜米数。

- `T05.V01` 把{object_a}向右移动五厘米 → `move_right` / `scene_updated`
- `T05.V02` 让{object_a}往东挪5厘米 → `move_right` / `scene_updated`
- `T05.V03` 把{object_a}向左移动五厘米 → `move_left` / `scene_updated`
- `T05.V04` 将{object_a}往西挪0.05米 → `move_left` / `scene_updated`
- `T05.V05` 把{object_a}向前移动五厘米 → `move_front` / `scene_updated`
- `T05.V06` 让{object_a}往北挪5厘米 → `move_front` / `scene_updated`
- `T05.V07` 把{object_a}向后移动五厘米 → `move_back` / `scene_updated`
- `T05.V08` 将{object_a}往南移动五厘米 → `move_back` / `scene_updated`
- `T05.V09` 把{object_a}向右稍微挪一点 → `move_right_small` / `scene_updated`
- `T05.V10` 让{object_a}往右轻微移动一下 → `move_right_small` / `scene_updated`

### T06 一次生成多物体（4 条表达）

默认父行：NONE；独立基线：`workspace_empty`；执行层：`e2e_scene`。

角色A/B按seed固定；明确不同角色不抽到相同无修饰名称，除非本行专测同类数量。

- `T06.V01` 增加一个{object_a}和一个{object_b} → `add_a_b` / `scene_updated`
- `T06.V02` 在桌面上生成{object_a}、{object_b}各一个 → `add_a_b` / `scene_updated`
- `T06.V03` 布置一个{object_a}，再布置一个{object_b} → `add_a_b` / `scene_updated`
- `T06.V04` 在桌子上放一个{object_a}和一个{object_b} → `add_a_b` / `scene_updated`

### T07 相对 A 新增 B（6 条表达）

默认父行：T01；独立基线：`single_a_center`；执行层：`e2e_scene`。

A/B相对方向与桌面方位分开；near表示近邻位置，仍在同一桌面。

- `T07.V01` 在{object_a}右边增加一个{object_b} → `relative_add_right_of` / `scene_updated`
- `T07.V02` 在{object_a}东侧生成一个{object_b} → `relative_add_right_of` / `scene_updated`
- `T07.V03` 在{object_a}左边放一个新{object_b} → `relative_add_left_of` / `scene_updated`
- `T07.V04` 在{object_a}前面新增一个{object_b} → `relative_add_front_of` / `scene_updated`
- `T07.V05` 在{object_a}旁边增加一个{object_b} → `relative_add_near` / `scene_updated`
- `T07.V06` 靠着{object_a}附近生成一个{object_b} → `relative_add_near` / `scene_updated`

### T08 已有物体相对移动（6 条表达）

默认父行：T06；独立基线：`two_distinct_objects`；执行层：`e2e_scene`。

不把移动误判为新增；对象总数和两对象实例ID保持。

- `T08.V01` 把{object_a}移到{object_b}右边 → `relative_move_right_of` / `scene_updated`
- `T08.V02` 将{object_a}挪到{object_b}东侧 → `relative_move_right_of` / `scene_updated`
- `T08.V03` 把{object_a}移到{object_b}后面 → `relative_move_behind` / `scene_updated`
- `T08.V04` 将{object_a}挪到{object_b}南侧 → `relative_move_behind` / `scene_updated`
- `T08.V05` 把{object_a}移到{object_b}旁边 → `relative_move_near` / `scene_updated`
- `T08.V06` 将{object_a}放到{object_b}附近 → `robot_task` `pick_and_place` / `plan_ready`

`T08.V06` 的“放到”是对已有物体的搬运动词，按第 2 节路由判据属于 `robot_task`；相对落点写
`placement_target.kind=relative_object`，只是字段填写，不再作为改判 `scene_edit` 的理由。
矩阵里该行的 `expected_json` 同步换成机器人契约（`route=robot_task`、`operation=pick_and_place`、
`executed=false`），`expected_outcome` 改为 `plan_ready`（语义 accepted 且产出可执行计划，场景由
执行端改写），其余五条仍断言 `scene_updated`。

### T09 极值与相对选择后改色（8 条表达）

默认父行：NONE；独立基线：`three_a_one_reference`；执行层：`e2e_scene`。

3个A位置不并列；候选池数量与选择结果数量独立；颜色修改只作用于选中的1个。

- `T09.V01` 把最左边的{object_a}改成蓝色 → `selector_leftmost` / `scene_updated`
- `T09.V02` 将最靠西的{object_a}设为蓝色 → `selector_leftmost` / `scene_updated`
- `T09.V03` 把最右边的{object_a}改成绿色 → `selector_rightmost` / `scene_updated`
- `T09.V04` 将最靠东的{object_a}设成绿色 → `selector_rightmost` / `scene_updated`
- `T09.V05` 把离{placement_1}最近的{object_a}改成红色 → `selector_nearest` / `scene_updated`
- `T09.V06` 将距离{placement_1}最近的那个{object_a}变为红色 → `selector_nearest` / `scene_updated`
- `T09.V07` 把离{placement_1}最远的{object_a}改成蓝色 → `selector_farthest` / `scene_updated`
- `T09.V08` 将距离{placement_1}最远的那个{object_a}设为蓝色 → `selector_farthest` / `scene_updated`

### T10 缩放（6 条表达）

默认父行：NONE；独立基线：`scalable_a_center`；执行层：`e2e_scene`。

角色必须有明确scalable和范围；正例留足空间，不把缺能力当语言失败。

- `T10.V01` 把{object_a}整体放大百分之十 → `scale_110` / `scene_updated`
- `T10.V02` 将{object_a}缩放到当前的1.1倍 → `scale_110` / `scene_updated`
- `T10.V03` 把{object_a}缩小到当前的九成 → `scale_90` / `scene_updated`
- `T10.V04` 将{object_a}整体缩小10% → `scale_90` / `scene_updated`
- `T10.V05` 把{object_a}放大一点 → `scale_small` / `scene_updated`
- `T10.V06` 将{object_a}稍微放大 → `scale_small` / `scene_updated`

### T11 替换资产（5 条表达）

默认父行：T01；独立基线：`single_a_center`；执行层：`e2e_scene`。

新资产由Qwen从目录选择；不得硬编码cup/mug或复制旧实例ID。替换后更新角色A的实际名称与ID。

- `T11.V01` 把{object_a}替换成{object_b} → `replace_a_b` / `scene_updated`
- `T11.V02` 将{object_a}换成{object_b} → `replace_a_b` / `scene_updated`
- `T11.V03` 用{object_b}替换{object_a} → `replace_a_b` / `scene_updated`
- `T11.V04` 把桌上的{object_a}更换为{object_b} → `replace_a_b` / `scene_updated`
- `T11.V05` 将现有{object_a}换成一个{object_b} → `replace_a_b` / `scene_updated`

### T12 删除与数量范围（5 条表达）

默认父行：T01；独立基线：`single_a_center`；执行层：`e2e_scene`。

前4种是单对象同义；“全部”单独数量语义组。

- `T12.V01` 删除{object_a} → `remove_one_a` / `scene_updated`
- `T12.V02` 移除桌上的{object_a} → `remove_one_a` / `scene_updated`
- `T12.V03` 把{object_a}从场景中删掉 → `remove_one_a` / `scene_updated`
- `T12.V04` 去掉这个{object_a} → `remove_one_a` / `scene_updated`
- `T12.V05` 删除全部{object_a} → `remove_all_a` / `scene_updated`

### T13 数量与颜色查询（5 条表达）

默认父行：NONE；独立基线：`three_a_one_reference`；执行层：`e2e_scene`。

独立oracle读取测试快照统计，不相信自然语言reply或answered状态。

- `T13.V01` 有几个{object_a} → `count_a` / `answered`
- `T13.V02` 桌面上一共有多少个{object_a} → `count_a` / `answered`
- `T13.V03` 数一数{object_a}的数量 → `count_a` / `answered`
- `T13.V04` 有没有蓝色{object_a} → `exists_blue_a` / `answered`
- `T13.V05` 存在蓝色的{object_a}吗 → `exists_blue_a` / `answered`

### T14 最近／最远查询（4 条表达）

默认父行：NONE；独立基线：`three_a_one_reference`；执行层：`e2e_scene`。

返回选中对象及实例ID；距离的量纲和XY中心距离定义显式记录。

- `T14.V01` 哪个{object_a}离{placement_1}最近 → `query_nearest` / `answered`
- `T14.V02` 找出距离{placement_1}最近的{object_a} → `query_nearest` / `answered`
- `T14.V03` 哪个{object_a}离{placement_1}最远 → `query_farthest` / `answered`
- `T14.V04` 找出距离{placement_1}最远的{object_a} → `query_farthest` / `answered`

### T15 多步顺序与同轮指代（4 条表达）

默认父行：NONE；独立基线：`workspace_empty`；执行层：`e2e_scene`。

同一行多个变体独立；句内多个操作才依次执行；‘它’绑定本轮新增的A。

- `T15.V01` 增加一个{object_a}，然后把它改成蓝色 → `add_then_color` / `scene_updated`
- `T15.V02` 生成一个{object_a}，再把它的颜色设为蓝色 → `add_then_color` / `scene_updated`
- `T15.V03` 生成一个{object_a}，再让它向右移动五厘米 → `add_then_move` / `scene_updated`
- `T15.V04` 添加一个{object_a}，接着将它向东挪5厘米 → `add_then_move` / `scene_updated`

### T16 原始快照分支（3 条表达）

默认父行：NONE；独立基线：`original_with_current_difference`；执行层：`e2e_scene`。

fixture显式先冻结原始场景，再形成不同current；不是把父行行号当original。

- `T16.V01` 在原始场景中增加一个{object_b} → `edit_original` / `scene_updated`
- `T16.V02` 基于初始场景生成一个{object_b} → `edit_original` / `scene_updated`
- `T16.V03` 在最开始的场景里添一个{object_b} → `edit_original` / `scene_updated`

### T17 几何安全拒绝（3 条表达）

默认父行：NONE；独立基线：`safety_scenarios`；执行层：`e2e_scene`。

每条由fixture证明不可行；仅指定安全码+场景/版本/角色不变才合格，不接受任意failed。

- `T17.V01` 在桌面正中间生成两个{placement_1} → `occupied_center_reject` / `safe_rejection`
- `T17.V02` 把{object_a}放大到当前的一百倍 → `scale_range_reject` / `safe_rejection`
- `T17.V03` 把{object_a}向右移动五厘米 → `table_boundary_reject` / `safe_rejection`

### T18 真正缺信息的澄清（3 条表达）

默认父行：NONE；独立基线：`ambiguous_two_a`；执行层：`e2e_scene`。

桌面约定不应消除多实例歧义、缺远近参照、缺替换目标等真实缺信息。

- `T18.V01` 把最远的{object_a}改成蓝色 → `missing_distance_reference` / `clarification_required`
- `T18.V02` 把{object_a}替换一下 → `missing_replacement` / `clarification_required`
- `T18.V03` 删除{object_a} → `ambiguous_target` / `clarification_required`

### T19 杯子与目录演进（6 条表达）

默认父行：NONE；独立基线：`catalog_contract_fixture`；执行层：`llm_contract`。

使用隔离测试目录/Mock OLS，不修改生产OLS；不是宣称线上已存在cup。

- `T19.V01` 增加一个杯子 → `mug_only:mug` / `semantic_accepted`
- `T19.V02` 生成一个马克杯 → `mug_only:mug` / `semantic_accepted`
- `T19.V03` 增加一个cup → `mug_and_cup:cup` / `semantic_accepted`
- `T19.V04` 生成一个mug → `mug_and_cup:mug` / `semantic_accepted`
- `T19.V05` 增加一个cup → `mug_removed_cup_present:cup` / `semantic_accepted`
- `T19.V06` 增加一个无把手的杯子 → `mug_only_no_handle_compatible_asset:no_match` / `clarification_required`

### T20 切换机械臂（4 条表达）

默认父行：NONE；独立基线：`registered_robot_profiles`；执行层：`config_contract`。

只做已注册profile切换；不由模型编造joint/URDF；桌面和普通物体保持。

- `T20.V01` 切换到单臂 → `robot_single` / `robot_setup_updated`
- `T20.V02` 把当前机械臂配置改为单臂 → `robot_single` / `robot_setup_updated`
- `T20.V03` 切换到双臂 → `robot_dual` / `robot_setup_updated`
- `T20.V04` 把机器人改成双臂配置 → `robot_dual` / `robot_setup_updated`

## 11. 逻辑预期与现有API字段

本包expected_outcome是测试层的逻辑标签。semantic_accepted对应首阶段accepted，safe_rejection是独立断言分类，robot_setup_updated对应已验证的profile切换；不要求为了表格擅自更改现有Brain/Web公开outcome枚举。运行器须显式映射并同时保存原始actual_outcome。

## 12. Excel导入映射

matrix英文列名按名称读取，不依赖列顺序；NONE转换为JSON null；variant_preview与variant_count为只读展示，不作为输入真值；全局inheritance_mode固定snapshot_and_roles。variants.expected_json解码为JSON对象。fixture/role/profile定义以本包JSON及对应说明表为准。修改Excel后，Codex实现的v2 compiler应重新导出规范JSON并执行同等结构/DAG校验，避免Excel与历史JSON并行漂移。
