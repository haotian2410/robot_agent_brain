# Agent（Brain）侧施工单（brain-web/2）

- 收件方：Brain 同事，仓库 `F:\robot_agent_brain\robot_agent_brain`，核对基线 `80f4d1a`
- 发件方：WebEditor／Gateway，仓库 `F:\web-frontend`
- 日期：2026-10-20
- 规范依据：`docs/gateway与Agent新通信流程.md`（协议）、`docs/场景文件描述.md` + `docs/Web前端需求规格v2.md` §3/§4.7/§4.8/§5（**场景格式的唯一真值**）

**本文是施工单，不是讨论稿。** 每条给出「现状（文件:行）→ 必须改成什么 → 验收判据」。
Brain 侧没有需要我方再确认的分支；场景格式以我方文档为准，Brain 现有 `SceneConfig` 的严格 Schema
**不是**场景格式，必须按本文 §A1 重写解析器。
所有条目完成后，`docs/gateway与Agent新通信流程.md` §13 的验收顺序第 1 项（场景兼容性）是唯一的准入门。

标记：**[必须]** 不做完不得进入联调；**[必须删除]** 该规则与场景格式冲突，撤除；
**[保持不动]** 你方现有实现已经对了，不要改；**[交付物]** 需要连同代码一起交来的东西。

> **本文当日第三次定稿（决议 Q114，覆盖 Q113 的相关段落；与你有关的结论如下）**：
> 我方浏览器入口最终分成三类（流程文档 §1.3）：**① 删除**——gizmo 平移/旋转/缩放、Details 关节角输入；
> **② 阶段闸门**——资产面板加入/删除物体，只在 `setup` 阶段可用，用户向 Agent 发出消息后禁用并弹窗；
> **③ 渲染层本地**——灯光预设只改浏览器怎么画，不进文档、不进导出、不进摘要。
> 因为 ② 还在，**`scene_sub_version` 保留**，现场身份是**四元组**，
> 于是 §A1.2（加字段）与 §A3（版本判据改词典序）**恢复为必须项**，
> §A4 的 `manual_edit_forbidden` 也恢复。上一稿"净简化、只需改解析器与摘要"的说法**作废**。

> **当日第四次定稿（决议 Q115、Q116，见 §A11）**，两条都与场景格式无关，是任务侧口径：
> **Q115 服务健康可见**——你方 `GET /health` 我方核对过**已存在**（`web/service.py:299-309` 注册、
> `:177-199` 实现），所以这不是让你新写接口，而是**字段定稿 + 补 `browser_id`／`tasks` 两键 +
> 保持"进程活着就 200"**；Gateway 会转发它并把它并进浏览器的 `GET /api/health`。
> **Q116 运行状态词表归你方**——`state` 从此是**你方自定义的任意非空字符串**，可自由扩充，
> 我方删除按名字的映射表；代价是你方必须在 `/queryTaskState` 与 `/startTask` 的响应里给出
> **`terminal` 布尔**，那是我方的**唯一**终态判据（§A11.3）。`outcome` 五态照旧，不动。

---

## 0. 先给几条实测证据（我方已在你方代码上跑过、或逐键比对过）

```
SceneConfig.model_validate(docs/ur5e_table_empty.json)  -> OK
SceneConfig.model_validate(docs/ur5e_passive_rig.json)  -> REJECT
    ('objects',3,'components',2,'role')  extra_forbidden "Extra inputs are not permitted"
```

另外几条来自直接读你方 Schema 与我方文件的逐键比对（末两条是上一稿已有的取证，保留）：

- **我方"③ 类只影响渲染"这条不是空话，但它需要我方自己改造**：今天灯光预设确实是改文档的
  （`editor/src/main.ts:307-315` → `applyLightingPreset(state.world, preset)` 会增删物体节点），
  我方把它改成渲染层覆盖之后，它才不进 `toJSON()`、不进摘要。
  **对你方的影响只有一句**：灯光预设永远不会出现在任何文档、任何头、任何回执里，
  不要为它预留字段（§A8 末尾清单）。

- **挂载物体的 `Transform` 带位姿是已上线文件的既有形态**，不是我方未来功能的产物：
  ```
  docs\ur5e_table_empty.json   obj 3 attached transform keys: ['parent', 'scale']
  docs\ur5e_passive_rig.json   obj 3 attached transform keys: ['parent', 'scale']
  docs\ur5e_passive_rig.json   obj 4 attached transform keys: ['parent', 'position', 'quaternion_xyzw', 'scale']
  ```
  物体 4 是 Q107 那份挂在 `wrist_3_link` 的 `type:"model"` URDF。§A1.4 的依据就是这一行，
  与"用户能不能拖"再无关系（那个入口我方已删）。
- **`contracts/scene.py:176-180` 的 `scene_requires_one_transform` / `scene_component_duplicate`
  与规格 §3 组件表冲突**：我方对"没有 `Transform` 的物体"按单位位姿创建（`docs/场景文件描述.md` §4.1、
  规格 §3），对"同类型重复"保留第一个并告警（§3.4）。
- **顶层字段的缺失回退**：我方 `readWorldMeta`（`editor/src/world.ts:350-363`）在
  `scene_version`／`scene_id` 不是合法 uint 时按 `0`、`scene_name` 不是字符串时按 `""`，
  而 `SceneConfig:196-199` 要求三者必填。`objects` 不是数组时**两边都整份拒绝**
  （我方 `world.ts:356` 抛 `INVALID_WORLD_SCHEMA`），这条不必改。
- 一份**严格合规**的文档在你方是**无损重导出**的（逐键 diff = 0，省略可选键与把浮点写成 `1` 都不漂移）。
  所以我方此前"两边永远算不出同一个摘要"的说法作废；问题从来不在 JCS，在 `extra="forbid"` 与那几条入口拒绝。
- 上面这份 `role` 是**已上线场景格式的一部分**（`docs/场景文件描述.md` §4.7、规格 §4.7，决议 **Q107**），
  它导致整份场景被拒，进而让 §A3 的每一次 CAS 失败。
- **Q115 是"补两键"不是"新接口"**：`GET /health` 在你方今天就有——
  路由注册 `web/service.py:309`，实现 `:177-199`，实测返回
  `{service, protocol, executed, qwen, browser, assets, capabilities}`，其中 `qwen` 与 `assets`
  已经在做真实探测（Qwen `/models`、OLS 资产根）。你方自己的 preflight 也已经在打它
  （`scripts/webeditor_preflight.py:21`）。所以本轮只要求**字段定稿 + 新增 `browser_id`／`tasks` +
  保住"进程活着即 200"这条语义**（§A11.1）。
- **Q116 的三处按名字判终态，我方逐处核对过**：
  ```
  web/task_store.py:11      STATES = ("已创建","已进入队列","进行中","任务完成","任务失败")
  web/service.py:259-261    state()  -> {"taskID", "state"}                 # 没有 terminal
  web/service.py:263-268    failure() -> 只在 record['state']=='任务失败' 时给 failureReason
  web/service.py:149        update(identifier, "任务失败" if outcome=="failed" else "任务完成")
  brain_tests/test_web_service.py:40   轮询到 state ∈ {"任务完成","任务失败"} 才 break
  ```
  最后一行说明：**连你方自己的测试都在按名字判结束**。词表放开后这类断言必须改读 `terminal`（§A11.5）。
  另外 `task_store.py:37-42` 的 busy／uncertain／孤儿任务 SQL 也是按状态名集合写的——那是你方内部实现，
  允许保留，但 **`terminal` 必须与它同源**（同一处常量或同一个函数），不许两处各判一次（§A11.3）。

---

## A1 解析器重写（本轮核心，[必须]）

### A1.0 目标结构：文档层 + 视图层

`contracts/scene.py` 现在把"校验"和"表示"合成了一件事：`SceneConfig` 是 `StrictModel`
（`:12-13` `extra="forbid"`），任何不认识的键都在**入口**就把整份场景打死。改成两层：

```python
class SceneDocument:        # 文档层：收到的原始 JSON，逐字段保真，不可变
    raw: dict               # 摘要对象、回读来源、diff 基准都只读它
class SceneView:            # 视图层：按 §3 组件表给已知字段，缺失按默认值回退
    def transform(self, object_id) -> TransformView | None
    def robot_driver(self, object_id) -> RobotDriverView | None
    ...                     # 视图不得回写 raw；raw 永远等于收到的那份 JSON
```

`validate_web_scene()`（`web/protocol.py:41`）的调用方一律改吃 `SceneView`，
`digest()` 改吃 `SceneDocument.raw`（见 §A2）。**校验失败的处理粒度按 §A1.7 改成物体／子树级。**

### A1.1 [必须删除] 已知组件的 `extra="forbid"`

`contracts/scene.py:139-157` `SceneComponent.validate_properties` 里
`COMPONENT_PROPERTIES[component_type].model_validate(self.properties)` 用的是严格模型。
场景格式明确规定："`properties` 里未声明的字段**不丢弃、不改名、不换算**，随原始字典整体保留"
（`docs/场景文件描述.md` §3 与规格 §3.8，决议 Q6）；导出还要求"逐字节保真：未知组件、未知字段、
`MeshRenderer` 的空字典都按 §3.8 原样带出去"（规格 §4.8.2）。

**改法**：视图模型 `extra="ignore"`，并且**只服务读取**；文档层永远保留原始键；
被忽略的键**必须仍进摘要**（因为摘要求自文档层，§A2）。禁止"解析时剥掉不认识的键再算 digest"。

### A1.2 [必须] 新增唯一顶层字段 `scene_sub_version`（可选 uint32，缺省 0）

`SceneConfig`（`contracts/scene.py:194-199`）与 `SceneSnapshot`（`:271-275`）各加
`scene_sub_version: int = 0`，并把它纳入 `web/protocol.py:44-45` 的 `web_uint32_required` 同一套检查。

- **为什么必须有**：`setup` 阶段用户仍可通过资产面板往现场加／删物体（流程文档 §1.3 第 ② 类）。
  这类改动改变内容与摘要，却**不是** Agent 写入，所以 `scene_version` 绝不能动；
  没有第四个字段，你方 §A3 的判据就会把用户加完物体的现场当冲突拒收。
- **可选**：历史场景文件与 `docs/场景文件描述.md` 的字段表都不含它，缺失即 `0`，
  **不得**因此报 `INVALID_WORLD_SCHEMA`；`scene_schema_version` 仍为 `Literal[1]`。
- **不得回写补齐**：文档层缺键就继续缺键（§A2.4 的不动点约束），补齐只在视图层生效。
  也就是说 `digest` 对"不带该键的文档"与"该键写成 0 的文档"**不相等**——这是对的，
  两者本来就是两份不同的文档；夹具（§A8.B3）里要有一例专门钉住它。
- 除此之外 brain-web/2 **不新增任何顶层字段**。

### A1.3 [必须] 缺失字段按默认值回退，不报错

- `contracts/scene.py:189-190` 的 `transform_pose_required_without_attachment` 撤除。
  场景格式是**缺失即回退**：`position`=`[0,0,0]`、`quaternion_xyzw`=`[0,0,0,1]`、`scale`=`[1,1,1]`
  （任一分量 ≤0 整体退回 `[1,1,1]`）、`parent`=null；**完全没有 `Transform` 的物体按单位位姿处理，
  并且物体仍然被创建**（规格 §3 组件表、`docs/场景文件描述.md` §4.1）——
  因此 `:176-178` 的 `scene_requires_one_transform` 同样撤除（缺 `Transform` 不再是否决条件），
  `:179-180` 的 `scene_component_duplicate` 降为"保留第一个 + 告警"（规格 §3.4）。
- 顶层：`scene_name` 缺失/非字符串 → `""`；`scene_version`、`scene_id` 非合法 uint32 → `0`；
  **`scene_sub_version` 缺失 → `0`**（视图层），判据与我方 `world.ts:357-363` 逐字对齐。
- 我方解析器对 `{parent: null}` 这种写法今天就是正常加载（`editor/src/world.test.ts:401`），
  你方必须同样正常加载，**不得回写补齐**（补齐即改写文档 → §A2 的 digest 分叉）。

### A1.4 [必须删除] "挂载物体的 `Transform` 必须省略 pose"

`contracts/scene.py:186-188` 的 `robot_attachment_transform_must_omit_pose` 撤除。
这是本轮最硬的一条冲突：

- 场景格式的语义是**覆盖**，不是**禁止**——"存在 `RobotAttachment` 时，连接位姿由
  `transform.position`/`transform.quaternion_xyzw` 决定，物体 `Transform` 里原有的 `position`
  与 `quaternion_xyzw` **一律忽略（不论是否存在）**；`Transform.scale` 与 `Transform.parent` 保留"
  （`docs/场景文件描述.md` §4.8；规格 §4.8 组件行同样写明"不论后者是否存在"）。
- 现实形态见 §0 第二条：已上线的 `docs/ur5e_passive_rig.json` 物体 4 就是
  "带 `RobotAttachment` 且 `Transform` 同时含 `position` 与 `quaternion_xyzw`"，
  你方今天会整场景拒绝这份文件（先被 `role` 挡住，修完 `role` 就撞这一条）。
- 我方删除拖动入口**不会**让这种文件消失：它是资产与场景文件本身的写法，与浏览器交互无关。

**改法**：视图层读取挂载物体的位姿时**忽略** `Transform.position`/`quaternion_xyzw`，
以 `RobotAttachment.transform`（`reference_frame` 局部系）+ 当前关节 FK 自行计算世界位姿；
文档层原样保留被忽略的键。你方需要 FK，`RobotDriver` 的合并位姿口径见
`docs/场景文件描述.md` §4.7（`initial` 打底、`now` 逐条覆盖、`<mimic>` 派生、`joint_limits` 裁剪）。

同时 `robot_attachment_parent_mismatch`（`:184-186`）降级为**告警 + 退回"把 `Transform` 当普通变换"**，
不得拒绝物体（`docs/场景文件描述.md` §4.8："parent_object_id 与 Transform.parent 不一致 → 退回并报告"）。

### A1.5 [必须] 宽容回退清单（逐组件）

以下每一行都是我方的**规范条款**，你方必须实现为"告警＋回退"，不得升级为错误、不得改写文档：

| 组件 | 场景 | 依据 |
|---|---|---|
| `component_type` | 未知类型：告警并原样保留，不中断加载 | 规格 §3.4 |
| `component_type` | 同类型重复：只保留第一个，其余告警忽略 | 规格 §3.4（O5 的 v1 口径） |
| `Transform` | 整个组件缺失：按单位位姿 + 场景根创建 | 同上 §4.1 |
| `Transform` | `parent=0xFFFFFFFF` 映射为 `null`；父不存在或成环 → 拒绝**该子树**；前向引用必须靠两遍解析支持 | 规格 §2.5、§3.6 |
| `MetadataRef` | `type` 非 `model`/`robot` → 告警后丢弃该 `type`，由 `path` 形式决定 id 空间；`path` 缺失 → 该物体是空节点 | `docs/场景文件描述.md` §4.2 |
| `MeshRenderer` | `forceOverrideColor` 非法（不是 `#`+6/8 位十六进制）→ 告警并保留原材质；`properties={}` 完全合法 | 同上 §4.3 |
| `Semantic` | `support` 本期不参与任何计算，但必须原样保留并进摘要 | 同上 §4.4、Q6 |
| `Light` | `type` 未知 → Ambient；`intensity` 非有限 → 1；`color` 不可解析 → 白；**方向/射程类附加字段不读**（沿局部 −Z） | 同上 §4.5 |
| `Camera` | `fov/near/far/resolution` 的缺省与 `far ≥ near×10` 归一化**只在读取层**，不得回写数据、不得进摘要前改写 | 同上 §4.6、决议 Q12 |
| `RobotDriver` | **`role`**：缺失、`"arm"`、其它字符串、非字符串一律按 `"arm"` 且**不告警** | 同上 §4.7、Q107 |
| `RobotDriver` | `now` 缺席／空对象／值为 null／字符串／数字／数组 → 完全不参与，显示 `initial` 原样 | 同上 §4.7、Q75 |
| `RobotDriver` | 关节名不在该 URDF 里 → 报告一次并跳过该项，其余照常；值非有限 → 忽略该关节 | 同上 §4.7 |

### A1.6 [必须] `RobotDriver` 的关节校验放松到规范口径

`contracts/scene.py:79-98` `valid_joints` 目前有三条比规范更严：

1. `:82-83` `set(joint_sequence) != set(joint_limits)` 即拒。规范只说 `joint_limits` 用来裁剪播放值，
   **不要求覆盖** `joint_sequence`；改成"只校验 `joint_limits` 命名的那些关节"。
2. `:84-85` `joint_limits` 与 `available_connect_joints` 都没有即拒（`robot_joint_limits_missing`）。
   规范允许两者都缺（缺 `joint_limits` 就是不限幅，`docs/场景文件描述.md` §4.7 物体 3 明确写了
   "没有 `joint_limits`：场景侧不限幅"）。撤除。
3. `:89-92` `initial`/`now` 的键必须 ⊆ `joint_sequence`（`robot_initial_joint_invalid`/`robot_current_joint_invalid`）。
   规范允许命名任何关节：`<mimic>` 派生关节可以合法地不写进 `joint_sequence`（夹爪只写
   `robotiq_2f85_right_driver_joint`，其余五条靠 `<mimic>` 派生，见 `docs/场景文件描述.md` §4.7）。
   我方 Details 面板把 `initial`/`now` 里点到但不在 `joint_sequence` 的名字**逐条列成只读行**
   （`editor/src/drivers.ts:declaredJointPositions` 的合并结果，规格 §4.7；Details 面板按 Q114 的
   ① 类口径是纯只读读数，关节角度输入框已删，列名规则不变）——
   写错的名字必须可见可诊断，不能在你方 Schema 层就整份否决。
   改成：未知命名按 §4.7 告警跳过，不在 Schema 层拒绝。

`joint_sequence` 非空、去重、名字非空这三条保留（与规范一致）。
`deployment_configuration()`（`:100-101`）排除 `now` 的做法保留，用途限定见 §A3.3。

### A1.7 [必须] 拒绝粒度与 `rejected_objects`

`validate_web_scene` 现在任何一条不合就抛 `ValueError`（整份失败）。改成：

- 逐物体处理，产出 `(accepted_objects, rejected_objects[])`；
- `rejected_objects[]` 的 `index` **必须是提交数组 `objects[]` 的下标**（规格 §3.6、决议 Q59：
  "条目本身畸形时没有 id 可用，只能靠 `index` 定位"，不得改用"存活节点列表的下标"）；
- 父不存在／成环 → 整个子树进 `rejected_objects`；
- 你方现有的 `commitWorld` 回执与 `_check_receipt`（`web/gateway.py:136-138`）
  已经在比较 `rejected_objects == []`，**这条比较必须保留**：非空即视为提交未完全落地，
  按 §A6 的语义处理，不得当 `committed` 继续用。

### A1.8 [交付物] 兼容性测试：拿我方真实文件跑

新增 `tests/test_webeditor_scene_compat.py`，把下列输入**逐份**喂给新解析器，断言解析成功、
文档层与输入逐键相等、`digest` 稳定、回读不丢字段：

1. 我方 7 份 OLS 场景（`docs/ur5e_table_empty.json` 等，含 `type:"model"` 与 `type:"robot"` 两种资产）；
2. `docs/ur5e_passive_rig.json`（`role:"passive"` + **物体 4 那份"挂载物体带 Transform pose"**的真实形态）；
3. 一份**含未知组件与未知字段**的现场：`component_type:"GazeboExtension"` +
   `Transform.properties.note="keep me"` + `Semantic.properties.support` 非 null；
4. 一份**缺字段**现场：`Transform` 只有 `parent`；一个物体**完全没有 `Transform`**；
   `RobotDriver` 只有 `joint_sequence`；`MetadataRef.type:"scene"`；`Camera` 只有 `type`；
   顶层缺 `scene_name`；
5. 一份**同类型组件重复**现场（`Transform` 之外的组件重复 → 保留第一个 + 告警，不拒绝物体）；
6. 一份**前向引用**现场：子物体排在父物体之前；一份**父环**现场（环内物体全部进 `rejected_objects`）。
7. 一对**子版本**现场：同一份内容，一份顶层写 `scene_sub_version: 2`、一份**完全不写该键**。
   断言：两份都解析成功；视图层分别读作 `2` 与 `0`；两份的 `digest` **不相等**（文档层没被补齐）；
   把 2 改成 3 ⇒ 摘要变，且这条推进只有在 `setup` 阶段才合法（§A4）。

第 2、3 两条在今天的代码上必然失败，它们就是本节的回归探针。
**注意**：上一稿的第 3 条"拖动后的挂载物体现场"不再需要单独构造——它就是 §0 里那份 passive rig 文件，
我方也确认过位姿入口的删除不会影响文件的形状（挂载位姿是资产与场景文件本身的写法）。

---

## A2 摘要：对象与算法（[必须]）

1. `web/protocol.py:12-15` `digest()` 去掉 `scene.model_dump(mode="json")` 那条分支，
   改为**对收到的 JSON 文档求** JCS + SHA-256（小写 hex）。
2. 键按 UTF-16 码元升序、数组保序、`1` 与 `1.0` 同一规范形式、拒绝 NaN/Inf、
   **不做 Unicode 归一化**。你方现在依赖的 `rfc8785` 包本身合规，问题只在那次重导出。
3. 摘要覆盖整份文档，**包含** `scene_version`、**`scene_sub_version`**、`now_joint_positions_rad`、
   `Semantic.support`，以及 §A1.1 里视图层忽略的未知键。
   顶层字段集合 = `brain-web/1` + `scene_sub_version`（§A1.2），除此之外不增不减。
4. **不变式测试**（两条，写成 pytest）：
   - `digest(parse(x).raw) == digest(x)`（解析不改写文档）；
   - `digest(parse(x).raw)` 对同一份输入两次调用相等（稳定）。
5. 无容差、无 epsilon。几何容差只属于几何校验，不适用于摘要比较。
6. 算法或字段范围今后变更必须升 `brain-web/3`，不得在 `brain-web/2` 内改语义。

## A3 版本判据（[必须] —— 改成语义是四元组词典序，码名不变）

### A3.1 判据从"单版本严格增大"改为"四元组词典序严格增大"

`session/brain_session.py:109-110` 现在是：

```python
if candidate.scene_version < current.scene_version or (changed and candidate.scene_version == current.scene_version):
    raise ValueError("browser_scene_version_conflict")
```

**必须改成**（保持现有 `changed` 变量与抛出方式）：

```python
candidate_pair = (candidate.scene_version, candidate.scene_sub_version)
current_pair = (current.scene_version, current.scene_sub_version)
if candidate_pair < current_pair or (candidate_pair == current_pair and changed):
    raise ValueError("browser_scene_version_conflict")
```

理由：`setup` 阶段用户通过面板增删物体时，`scene_version` 不变、`scene_sub_version` 变大、内容变，
这是**合法现场**（流程文档 §1.2.1、§1.3 第 ② 类），今天这条判据会把它拒了。
反过来"四元组完全相同而内容不同"仍然非法，同一份文档重复上报（四元组与摘要都不变）必须**幂等接受**，
不得报错。

- 错误码名 `browser_scene_version_conflict` **保留不改名**；上一稿提过又撤的
  `browser_scene_revision_conflict` **仍然不要实现**（同一语义两套码，反向对账测试会出现两个真值）。
- `browser_new_session_required`（`:106-107`）与 `browser_asset_replacement_requires_new_id`
  （`:113-115`）同样保留。

### A3.2 `commitWorld` 的目标与 `expected`

- `web/gateway.py:149-152`：同 `scene_id` 时目标必须是**恰好** `previous.scene_version + 1`
  （`gateway_target_version_invalid`／`gateway_new_scene_version_invalid` 两条判据保持）。
- **新增**：candidate 顶层的 `scene_sub_version` **必须为 `0`**——Agent 写入把子版本重新基线化，
  否则"用户 `setup` 期加的两个物体"与"Agent 新加的一个物体"会挤在同一个计数器里，CAS 分不清谁写的。
  非 0 ⇒ `gateway_scene_revision_invalid`（新码，流程文档 §10）。
- `web/gateway.py:155` 的 `expected` 从三元组扩成**四元组** `{scene_id, scene_version, scene_sub_version, sceneDigest}`；
  `:70` 的 `acquireSceneLease` 载荷同步加 `scene_sub_version`。
- `:138` 的回执校验字段集合加 `scene_sub_version`；`SceneSnapshot`（`:126,180`）同 §A1.2 加字段。
- 查询／仅出计划任务不调 `commitWorld` ⇒ 四元组与摘要都不变；`SceneSnapshot`／Commands 产物的身份
  一律用四元组，**不得**把 `scene_version` 当"任务提交次数"。

### A3.3 `now_joint_positions_rad` 的定位

它是**内容**：进摘要；由 Agent 侧 `/updateItem` 写入并 `+1` 版本。
`session/brain_session.py:120-126` 的 `static()` 与 `contracts/scene.py:100-101` 的
`deployment_configuration()` 对它的排除**保留**，用途限定为"部署是否需要重新绑定"这种粗判据，
不得反过来当作"改关节不算场景变化"的依据。

## A4 会话阶段（[必须]）

- `POST/GET /sessions`（`web/service.py:306-307`）响应加 `session_phase`；首次 `/startTask` 被接受即
  置 `agent_owned`（幂等，只写一次）。
- **`agent_owned` 阶段的越权编辑校验（恢复）**：该阶段浏览器侧的面板增删已被禁用（流程文档 §1.3 ②），
  所以你方收到"`scene_version` 不变而 `scene_sub_version` 变大"的上报时，**必然是违规**：
  不得按 §A3.1 的词典序放行，必须回 `manual_edit_forbidden`。判据顺序固定为
  ① 阶段是否 `agent_owned` → ② 词典序是否合法 → ③ 四元组相同而内容变 ⇒ `browser_scene_version_conflict`。
  这一条是三道防线里的第三道（前端弹窗、Gateway 权威拒绝、你方防御拒绝）。
- `setup` 阶段的子版本推进是**合法输入**，不要拒绝，也不要在你方任何日志里当异常报上来。
- 该阶段你方还要防的是**换场景**：已由 `browser_new_session_required` 覆盖（§A3.1）。
- `browser_asset_replacement_requires_new_id`（`:113-115`）保留，并在你方文档里标注为
  "同一 `scene_id` 下换资产必须新会话"，避免前端把它当 bug 报上来。

## A5 对象 id 分配（[必须]）

1. `web/gateway.py:109` 的 `<= 2**32` 收到 `<= 2**32 - 1`（对象 id 合法上限，`contracts/scene.py:9`
   与 `web/protocol.py:44-45` 一致）。今天这个差一个数会让 Gateway 给出的水位被你方拒。
2. 申领制：我方 Gateway 新增 `GET /allocateObjectID`，**Agent 侧每一个增物入口在落地前申领号段**。
   `setup` 阶段的浏览器面板加物仍会本地分配 id，但它**以 `X-Next-Object-ID` 为种子**，
   而我方 Gateway 采纳上报时把水位抬到 `max(持久, 文档最大 id + 1)`（流程文档 §6），
   所以你方申领到的号段不会与用户 `setup` 期用过的 id 相撞；进入 `agent_owned` 后浏览器无任何分配点。
   你方读到 `X-Next-Object-ID` 的规则不变，`scene_object_id_reused`
   （`session/brain_session.py:129-131`）保留。
3. 你方 `next_scene_object_id` 与 Gateway 水位取 `max()` 的现有逻辑（`:134`）保留。

## A6 事务、明确拒绝与恢复（[必须]）

1. **journal 必须可回读对账**：`web/gateway.py:141-176` 现在写 `prepared`／`unknown`／`committed`
   但整个文件没有一处回读。改成可按 `(transactionID, scene_id, digest)` 查询，
   并作为 §A6.3 `resolveUncertain` 的证据来源。
2. **明确拒绝不得归为 unknown**：`web/gateway.py:160-165` 的 `except Exception` 会把
   结构性拒绝（回执字段不匹配、`rejected_objects` 非空）也标成 `gateway_commit_unknown`。
   必须分开：① 服务端明确"未部分修改现场"（`rejected`，可解锁）；② 回执读不到／格式不认识
   （`unknown`，保持锁）。超时**永远不是**拒绝证据。
3. `POST /resolveUncertain` 按流程文档 §8.3 的**定稿字段**实现（请求含 `evidence{receipt_status,
   live_digest, expected_digest, late_write_excluded}` 与 `resolution`，响应含
   `state ∈ {resolved, kept_locked, quarantined}`），六步顺序不得省略，
   任何一步不满足返回 `kept_locked`。新建 `/sessions`、换浏览器、重启服务、改数据库都不是解锁证据。
4. 传输失败**绝不重发** mutating 请求（`:158-165` 的现有做法正确，保持）。

## A7 相机、能力、端口与结果（[必须]）

1. `_frame_identity`（`web/gateway.py:188-192`）**加一项 `scene_sub_version`**（上一稿的"不加字段"作废），
   其余不变；响应缺 `scene_id`／`scene_version`／`scene_sub_version`／`sceneDigest`／`playback_state`／
   `width`／`height` 任一项即 `camera_frame_scene_mismatch`。`CameraFrame`（`:255`）字段集合同步加这一项。
   注意：`_frame_identity` 的比对是**身份**比对，与像素无关——灯光预设（③ 类）不改文档，
   所以它不会让身份比对失败；持锁期内我方会把预设冻结，采集像素因此也可重复（流程文档 §9、§7.2）。
2. `camera_id` 进 `POST /sessions`（首次绑定必填，之后不得改，换相机＝新会话）；
   Brain 持久化绑定并按 `id_remap` 更新 original 派生。**不猜相机**：UR5e 空模板同时有 ID4 腕部与
   ID5 顶视，"读现场 Camera"只给候选；我方 Gateway 只提供候选清单。
3. `web/protocol.py:9` `PROTOCOL_VERSION = "brain-web/2"`；`web/gateway.py:90` 的能力子集检查
   按**名字**加 `canonical_scene`／`sub_versioned_scene_identity`／`setup_only_local_edits`／
   `agent_owned_phase`／`uncertain_recovery`（**八项**见流程文档 §5.2）。
   `versioned_manual_edits`、`sub_versioned_manual_edits`、`viewport_read_only` 三个名字**都不得使用**——
   前两个是 Q113 之前的旧口径，第三个在 Q114 之后语义已不成立。
4. Gateway 地址基线 **8099**（我方 P0 已迁）；**8098 是一次性验证栈**（带
   `X-Standalone-Verification: 1`），不得作为 brain-web/2 联调对象；8080 是 Qwen 模型服务。
5. 结果口径：五态 `outcome`（`scene_updated`／`answered`／`clarification_required`／`plan_ready`／`failed`）
   与 `executed=false` 保持不变；`web_platform_profile_unsupported` 必须附**人类可读原因字段**
   与一份契约样例（我方 UI 按 `outcome` + 原因展示，永不显示"执行成功"）。
6. `GET /health` 保留，字段按 **§A11.1** 定稿（六键口径不变，新增 `browser_id`／`tasks`）；
   我方不据它自行解除编辑锁，也不据它判任务终态。

## A8 交付物（[交付物]）

> **编号说明（本轮重排）**：上一稿本节与 `docs/SendToTeammate.md` §3 各有一套 B 编号
> （同名不同物，例如两边都写 B5 却分别是"resolveUncertain"和"桩服务"）。
> **以本节 B1–B10 为唯一编号**，`SendToTeammate.md` 已改为镜像本节。

| 项 | 内容 | 验收判据 |
|---|---|---|
| B1 | §A1 的解析器重写 + §A1.8 的兼容性测试 | **七类**输入全部通过；`role`／挂载 pose／未知字段／缺 `Transform`／重复组件／子版本成对六条不再被拒 |
| B2 | §A2 的 digest 改造 + 两条不变式测试 | 同一份文档两侧算出同一 hex |
| B3 | **成对夹具**（非空、真实）：每例给 `scene.json` + `normalized_utf8` + 期望 `digest` + 相等／不等标记 | 覆盖流程文档 §3 全部字段范围，并加四例：`role` 现场、**挂载物体带 pose 现场**（passive rig 物体 4）、"仅 `now_joint_positions_rad` 变"⇒ 摘要变且 `scene_version` **必须由写回路径 +1**、**"仅 `scene_sub_version` 变"**⇒ 摘要变而 `scene_version` 不变（`setup` 期合法） |
| B4 | §A3 判据 + §A5 上限 + §A6 事务 | 四元组词典序生效；`X-Next-Object-ID` 收到 `2**32-1`；journal 可回读、`rejected` 与 `unknown` 分离 |
| B5 | §A6.3 `resolveUncertain` 六步 | 流程文档 §8.3 的定稿字段，任一步不满足回 `kept_locked` |
| B6 | §A7.1–A7.2 相机绑定 + §A7.3 `PROTOCOL_VERSION`／能力名 | `_frame_identity` 与 `expected`／租约载荷含 `scene_sub_version`；`camera_id` 首次必填、之后不得改；能力按**名字**含八项（`sub_versioned_scene_identity` 等） |
| B7 | 无 Qwen 的 **Brain 桩服务** | 可重置固定任务序列、澄清与失败分支、可下载白名单产物、响应里明确标 `synthetic`（含 `real_qwen_tested:false` 一类字段），给出启动与重置方式；**且能回一个不在现有五态里的状态字符串**（§A11.5） |
| B8 | **真实 `clarification_required` 样例** | 必须实际触发；脱敏处逐字段标注；`metrics.model_calls` 来自真实调用；artifact URL 指向可交付资源，不给私人绝对路径。合成澄清与 `scene_scale_forbidden` **不得**充当真实澄清样例 |
| B9 ★ | §A11.1–A11.2 服务健康 | `GET /health` 含定稿全部分项；停掉 Qwen 后**仍 200** 且 `qwen:"unavailable"`；`browser_id`／`tasks` 与实际状态一致 |
| B10 ★ | §A11.3–§A11.6 状态词表与 `terminal` | `/queryTaskState` 与 `/startTask` 响应带 `terminal`；`failureReason` 按 `terminal && outcome=="failed"` 产出；你方测试与桩服务不再按状态名判结束 |

**我方对应交付（不是你方工时）**：8099 新发布包（含 `config/constant_config.json` 与 `dist/`）与版本号——
你回函 §一 说"尚未收到新源码／发布包核验"，这条由我方在 P4 关闭，你方不必等待。

**明确不需要你方做的**（避免白工，逐条都是上一稿里出现过又被 Q114 取消的）：
`scene_sub_version` 之外的任何顶层字段；错误码改名（`browser_scene_revision_conflict`）；
能力项 `versioned_manual_edits`／`sub_versioned_manual_edits`／`viewport_read_only`；
为"用户拖动位姿／改关节角"设计的任何校验或例外（① 类入口在我方页面**已删除**，永不恢复）；
为灯光预设设计的任何协议字段（③ 类**不出浏览器**，你方永远看不到它）。

## A9 不得做的事（防止用放宽绕过）

1. 不得为了让 digest 相等而**删字段**或**排除未知键**——正确做法是 §A2 换摘要对象。
2. 不得在解析时把默认值、归一化值、FK 结果**写回**文档（§A1.3／§A1.5，`Camera` 归一化尤其明显）。
3. 不得用缓存回答 `getWorld`；不得回 `X-World-Source: cache`。
4. 不得把超时、找不到回执、浏览器断线当作 `rejected` 的证据。
5. 不得为通过校验要求我方前端修改导出格式（导出格式是规格 §4.8.2 的既有契约）。
6. 不得把 `plan_ready`／`answered`／`clarification_required` 显示或报告成"机器人执行成功"。
7. 不得把"用户在 `setup` 期通过面板增删物体"当成越权——那是 §A3.1 词典序合法推进的**唯一**来源。
   也不得反过来越界校验：你方不需要知道浏览器**怎么**画（灯光、辅助图层、相机姿态都不进协议），
   只需要按四元组与阶段判定。
8. 不得让 `terminal` 与状态名**各判一处**（§A11.3）。`/health` 与状态字符串都不是任务是否结束的依据；
   反过来也不得要求我方按名字翻译状态——词表放开后我方没有任何状态名常量可改。

## A10 Brain 侧施工顺序与完成定义

```
第 1 步  §A1 解析器（含 §A1.2 新字段）+ §A1.8 兼容性测试   （唯一准入门，其余全排在它后面）
第 2 步  §A2 digest + §A8.B3 夹具             （B3 交我方，我方 digest.test.ts 等它）
第 3 步  §A5 上限 + §A7.1–A7.3 相机/能力/端口
第 4 步  §A3 四元组判据 + §A4 阶段 + §A6 事务／resolveUncertain
第 5 步  §A8.B7/B8 桩服务与真实样例 + §A11.5 桩服务的任意状态字符串
第 6 步  §A11.1–A11.6 健康字段与 terminal
```

**§A11 与解析器／摘要／CAS 没有依赖，可以并行开工**，但它必须**早于或同步于第 5 步**落地：
我方的未知态负控制（流程文档 §13 第 11 项）要用桩服务的任意状态字符串，
而桩服务又必须按 §A11.3 回 `terminal`。两件事拆开交付的话，我方那条验收只能记 skip。

**第 4 步必须整体交付，不得只做 §A3.1 的词典序**：词典序放开后，"同版本不同子版本"在
`agent_owned` 期也合法了，只有配合 §A4 的 `manual_edit_forbidden` 才封得住。两步拆开发运会留下
一个真实窗口：用户在任务下发后仍改动画。

**完成定义**：`pytest` 全绿 + §A1.8 七类输入通过 + 流程文档 §13 第 1～4 项在我方 8099 真实栈上跑通
（真实浏览器，不用测试替身；外部资源缺失的用例显示 skip，不得算通过）。
你方回函 §5.2 的四档支持范围与本完成定义不冲突：本文所有条目都属于"确认后要补齐"，
现在由流程文档 §12 的决议表确认完毕，请按档执行。

## A11 服务健康与运行状态词表（Q115／Q116 新增，[必须]）

### A11.1 `GET /health` 字段定稿

```json
{"service":"ready","protocol":"brain-web/2","executed":false,
 "qwen":"ready|unavailable|model_not_found",
 "browser":"bound|not_bound","browser_id":"browser-7 或 null",
 "assets":"ok|unconfigured|{\"matched\":false,\"error":"…"}",
 "capabilities":{ …现有形状不动… },
 "tasks":{"active_task_id":12 或 null,"queued":0}}
```

- 现有六键与 `capabilities` 的**取值口径不动**（今天 `web/service.py:178-181` 就是这个形状，别重构它）。
- **新增两键**：`browser_id`（当前绑定的浏览器；`browser=="not_bound"` 时必须为 `null`）、
  `tasks`（`active_task_id`＝正在执行的任务 id 或 `null`，`queued`＝排队数量）。
- **"进程活着就 200"是不变式**：Qwen／OLS 坏掉只体现在分项里。今天 `:187-193` 的
  `except` 分支已经满足，请把它钉成测试——**不得**改成依赖不可达即返回 5xx，
  因为我方必须能区分"这个服务没起"和"这个服务起了但它的依赖坏了"。
- 两新键都是**诊断用**：占用判据仍是你的 `task_busy`，绑定判据仍是 Gateway 的持久状态。
  两边读数不一致时我方只记 warning，不互相否决（流程文档 §5.3）。

### A11.2 健康路由的边界

- 只读、不携带现场数据、不鉴权（本期无鉴权，见流程文档 §11）。
- 我方 Gateway 转发**超时 3 秒**、透传缓存 **≤5 秒**，浏览器面板 15 秒轮询。
  所以 `/health` 必须能在 3 秒内返回：**把 Qwen／OLS 的探测超时压到 2 秒以内**，
  或缓存上一次探测结果——不要让我方的转发因为你方的依赖慢而超时。
- 我方与你方都不得依据 `/health` 解除编辑锁或 `quarantined`（§A9 之外再钉一次）。

### A11.3 `terminal` 是唯一的终态判据

`GET /queryTaskState?taskID=` 响应改为：

```json
{"taskID":12,"state":"进行中","terminal":false,"state_detail":"规划第 2 步"}
```

- `state`：**任意非空字符串**，词表由你方定义、可随时扩充，与我方无需同步、无需通知。
- `terminal`：**布尔，必填**。`false` ⇒ 我方继续每 5 秒轮询；`true` ⇒ 我方停止轮询并取 result。
- `state_detail`：可选字符串，给我方面板当次要文案（进度、子步骤名都行）。
  **不得**用它承载"是否结束"——那个信息只有 `terminal` 一个来源。
- **派生必须同源一处**：在 `web/task_store.py` 里给出唯一判定入口（一个常量集合或一个函数），
  `service.state()`／`service.failure()`／孤儿与 busy 的 SQL（`task_store.py:37-42`）／你方测试一律走它。
  两处各判一次是 §A9.8 明令禁止的情形——今天 `:11` 的 `STATES` 只能作为**默认词表**，
  不得当校验用（新状态字符串必须能写入并被 `terminal` 正确分类）。
- `POST /startTask` 的响应同样带 `terminal`，**恒 `false`**。我方若收到 `terminal:true` 会忽略它并记
  warning，一切以第一次 `/queryTaskState` 为准（流程文档 §7.4 第 8 条）。

### A11.4 `queryTaskFailureReason` 的产出条件

```python
# 现在（web/service.py:263-268）：按状态名
"failureReason": … if record['state'] == '任务失败' else None
# 改为：按终态 + 结果分类
terminal and (record["result"] or {}).get("outcome") == "failed"  ⇒ 给原因
否则                                                             ⇒ {"taskID":…, "terminal":…, "failureReason": None}
```

- **非失败的终态也要 200**，带 `failureReason: null`；不得返回 404、不得省略该键。
  我方今天对这条路由的 404 是容错的（`local_gateway.py:313-318` 退化成 `None`），
  但 brain-web/2 把"终态必返 200、无原因即 `null`"定成契约，桩服务不得用 404 表达"没有原因"。
- 未知／重启后不再认识的 `taskID` 继续 404——那是"任务不存在"的事实，我方据此把 job 落 `failed`，
  与状态词表无关（流程文档 §7.4 第 5 条）。

### A11.5 你方测试与桩服务同步改造

- `brain_tests/test_web_service.py:40` 的 `state in {"任务完成","任务失败"}` 改为读 `terminal`；
  `brain_tests/test_web_protocol.py:63` 这类按名字 `update(..., "进行中")` 的写法可以保留，
  但断言终态的地方一律不许再出现状态名字面量。
- §A8.B7 的**桩服务必须能喂任意状态字符串**，至少提供一条脚本化序列：
  第一次 `"规划中"` + `terminal:false`，第二次同名或改名 + `terminal:true` + 可取的 result。
  我方要用它跑未知态负控制（流程文档 §13 第 11 项）——**这是本次新增的桩服务能力**，
  不做的话我方那条验收只能 skip。

### A11.6 不变式（两边各一条测试）

1. **你方**：`terminal==true` 之后 `GET /queryTaskResult?taskID=` 必须**立即可取**，
   且 `outcome` 是五态之一；`terminal==false` 期间取 result 必须是明确的"未完成"错误，而不是空对象。
2. **我方**：状态字符串无论认识与否，`terminal` 缺失或非布尔 ⇒ 按非终态处理并 warn，继续轮询
   （`tests/test_agent_polling.py` 扩一支，替代原"未知状态"那支的按名字断言）。

判据：流程文档 **§5.3**（健康字段）与 **§7.4**（状态词表）是这两件事的唯一真值，
§13 第 10、11 项是联调验收档。


本文只新增／修订文档，不改你方代码、不启动服务、不生成新的真实模型样例。
