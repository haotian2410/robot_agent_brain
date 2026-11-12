# Scene Edit：缩放与实例颜色

Scene v1 公共协议保持不变。缩放仅写 `Transform.scale`；改色仅写
`MeshRenderer.forceOverrideColor`。原始 OBJ/MTL/PNG、metadata、平台模板不修改。

## 资产字段与默认值

- `semantic_properties.scalable` → 内部 `BrainAssetView.scalable`。
- `physical_properties.scale=[min,max]` → 内部 `scale_range`，不是 XYZ 或导入默认值。
- `semantic_properties.tag` → 原有标签及明确颜色集合 `color_tags`，多色不压成单一 HEX。
- `scalable=false` 禁止缩放；缺少权限/范围时拒绝，不能默认允许。
- 创建对象仍使用 `[1,1,1]`；导入场景的原 Transform、机器人附件保持原样。

苹果当前禁止缩放；蓝色篮子允许每轴局部 scale 在 `[1,1.8]`。从 1 缩小到 .9
会被拒绝，从 1 放大到 1.1 合法。资产限制和配置限制取交集，不截断越界值。

## 操作与配置

`scale` 只接受一种表示，不能混填：

- `scale_mode=multiply, scale_xyz=[1.2,1,1]`：当前局部 X 放大 20%。
- `scale_mode=set, scale_xyz=[1.2,1.1,1.1]`：设置绝对局部 scale。
- `scale_direction=enlarge|shrink, scale_amount=small|medium|large`：Python 查策略。

模糊放大倍率由 `scene_scale_small/medium/large` 配置，默认 `1.1/1.5/2.0`；
缩小取倒数。`scene_scale_min/max` 默认 `.1/10`。配置均参与会话 fingerprint，
与移动距离的 MotionPolicy 无关。XYZ 指对象局部轴，明确世界轴缩放不支持。

目标必须有可用几何。支撑对象缩放保持世界 XY，调整 Z 使 bottom 贴原支撑 top，
检查 footprint、适用工作区和已知 AABB。无 support 不自动贴桌面。
机器人、附件、有子对象或承载物的对象不支持缩放；缺少必要位姿/几何明确拒绝。
未知机器人/附件不参与 AABB 检查，检查通过不代表真实碰撞或抓取可行。

多个实例和 translate → scale → color 等操作按顺序预览，整轮只提交一次版本。
失败不提交部分结果，目标在首次选择后保持稳定 ID。原 quaternion、parent 和
非目标组件保留，Semantic.support 仅在可证明时重新建立。

## 颜色修改与查询

`update_properties` 仅接受 `{"color":"blue"}` 等单个 color 字段。常用中英文
颜色由 Python 映射，HEX 接受 `#RRGGBB`、`#RRGGBBAA`，转大写并保留 alpha。
未知颜色需要澄清；禁止通用属性写入。本轮没有 reset_color。

颜色证据优先级：实例 override → 资产明确颜色标签 → 整批都没有证据时丢掉颜色词，
只按主体匹配；颜色永远不能因为“查不到”而让整轮报错（policy v3）。
override 是实例渲染属性，不是永久改写资产颜色。`#FFFFFF` 就是白色，不是“未覆盖”。
多色标签可匹配已声明颜色，但不能用于推断任意精确 HEX。RGBA 的颜色名查询使用
声明 RGB，不推断透明混色。

### 证据三态与颜色退化（policy v3）

单个实例的颜色证据有三种读数，不再只有“匹配/不匹配”：

- 成立：实例 override 或资产颜色标签命中请求颜色。
- 不成立：实例声明了别的颜色。
- 无证据：实例既没有 override，资产也没有颜色标签。非 `#RRGGBB` 资产标签遇到
  字面 HEX 请求同样读作无证据，不做最近色推断。

无证据既不算命中，也不能否决同批里确有证据的兄弟：一个被染绿的苹果不会被旁边两个
从没染过色的苹果拖成整批失败。整批都无证据时，颜色词直接丢弃，按名称/类别/tag
选出主体，再由歧义规则决定是选唯一一个还是追问——贴图颜色系统分辨不出来的东西，
不作为拒绝回答的理由。读不出来的颜色词（如「彩色」）与读不出来的 override 一样，
按无证据处理，不报 `scene_edit_color_unknown`。全链路只剩一处
`grounding_evidence_missing: tags`（整批连 tag 证据都没有），颜色不再抛错。

`COLOR_POLICY_VERSION` 记录该读数，随诊断载荷一起输出。

“有证据但与请求矛盾”仍需退化放行，且只在不会乱选的两种出口：句中带方位/极值/
nearest 选择关系（用退化后的整池再解算关系），或退化后只剩一个对象。其余情况保持
不匹配，由 Grounding 报「找不到」。以下两种情况绝不退化：`quantity_mode=all` 或
显式 count（不能把批量操作施加到用户排除的集合上）、查询路由。查询与 Grounding
共用同一个选择入口，但 `allow_description_fallback` 只在 `SceneGrounder` 打开：
桌上一只苹果被染成绿色时，「有几个红苹果」答 0，不会退化成桌上苹果的数量。整批
无证据的计数则按上一条走主体，因为颜色词在那里本来就无从校验。场景编辑沿用同一
入口的非退化规则。

例如：“把苹果改蓝”后，“蓝色苹果有几个”和“把蓝色苹果放进篮子”会使用该实例，
不能再用资产原 red 标签判定其为红色。款式标签仍保留。

`tags` 是主匹配信号：名字与别名都落空时再按 tag 重叠打分拓宽一次候选池，取最高
分集合；拓宽只能扩大“找不到”，不会改变已有命中结果。颜色词在打分前从 tags 中摘
出，仍留在硬过滤位，因此 33 号青苹果不会因「绿色」被选中，只有用户说「青苹果」
才按整词 tag 命中它。理解阶段的场景上下文只给 `color_override` 原值：模型不再被
要求核对场景，颜色由用户话语进入 `color`，证据比对全部留在 Python。

颜色覆盖只验证 Brain 数据语义，未验证外部平台纯色显示。随包参考渲染脚本仍绑定
纹理且未完整处理 alpha，必须由平台独立确认，不以 JSON 成功冒充渲染成功。

## 验证

`python -m pytest brain_tests/test_scene_scale_color.py brain_tests/test_final_models_integration.py`

染过色实例的选择与退化：`python -m pytest brain_tests/test_recolored_selection.py
brain_tests/test_component_runtime.py`。

真实 Qwen 多轮：`python demo/final_models/scale_color_demo.py`。
资产包缺失时集成测试明确跳过，普通 fixture 测试仍运行。metadata 颜色/缩放更新
不需要重算 geometry cache；新建 Application 后 fingerprint 反映其变化，恢复旧
会话发出配置变化提示，不自动重写旧 Scene。

### 2026-10-13 本地验收记录

- Python 3.12：481 passed；独立 Python 3.11.14 环境：481 passed。
- 独立 wheel 安装及 `scripts/wheel_smoke.py` 通过；wheel 不含 OBJ/PNG/URDF/7z。
- 本地真实 Qwen（8080）：13 轮全部符合预期，含两篮子批量缩放与改色。
  详细结果：`var/scale-color-demo-final/scale_color_summary.json`（本机产物，不提交）。
- `final_models` 资产树 SHA-256 未变：
  `277e178d61eede9acdc0388cd43d9ad0c39cd450d8036a9873de2310b84c376c`。
- 保留既有 PR2 的 `material.mtl` 缺失问题；不宣称资产验证完整通过。
- GitHub Actions 仍配置 Python 3.11/3.12，并显示缺少外部资产时的 skip 原因。
  本轮未推送，远端 CI 未触发；以上是本地验证，不冒充远端运行记录。
- 外部渲染纯色/透明效果未验证，无 MuJoCo 执行。
