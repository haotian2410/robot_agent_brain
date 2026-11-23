# Gateway ↔ Agent（Brain）通信流程（brain-web/2 定稿）

- 定稿：2026-10-20，WebEditor／Gateway 侧（本仓库是场景格式与协议的**唯一决策方**）
- 取代：`docs/gateway与Agent服务通信流程.md`（brain-web/1 的五态轮询口径）
- 配套：`docs/gateway修改点.md`（我方施工清单）、`docs/AgentBrain修改点.md`（对方施工清单）、
  `docs/场景文件描述.md` + `docs/Web前端需求规格v2.md` §3/§4.8/§5（**场景格式的唯一真值**）
- 本文用"必须／不得"书写。对方回函（`docs/webeditor_teammate_confirmation.md`）里那些"待双方确认"的
  条目，由本文第 12 节的决议表统一收敛；**不再往返确认**，双方按本文实现，契约测试按本文判定。

协议版本号：**`brain-web/2`**。摘要对象、会话阶段、现场身份元组三项改变了既有字段的含义，
沿用 `brain-web/1` 会让同一个版本号在两边各有含义，禁止。

> **本文当日第三次定稿（决议 Q114，取代当日第二次定稿 Q113 的相关部分）**：Q113 曾以
> "浏览器不再允许任何手动编辑"为由把现场身份收回三元组、整条作废 `scene_sub_version`。
> 现在的最终口径是**分三类的入口**（§1.3）：
> ① **删除**——gizmo 平移/旋转/缩放、Details 关节角度输入；
> ② **阶段闸门**——资产面板加入／删除物体等改现场的操作，在 `setup` 期可用，
>    **用户向 Agent 发出消息后即禁用**（点击进入时弹窗说明，不做静默吞掉）；
> ③ **渲染层本地**——灯光预设只改浏览器怎么画，**不出浏览器**（不进 `World.toJSON()`、
>    不进导出、不进 `getWorld`、因此不进摘要）。
> 因为 ② 仍然存在，"同 `scene_version` 而内容不同"在 `setup` 期是**合法状态**，
> 四元组身份 **`scene_sub_version` 保留**（§1、§1.2、§3），Brain 的版本判据必须改成词典序（`docs/AgentBrain修改点.md` §A3）。
> 两个字段都从未上线，故本轮调整仍不需要 `brain-web/3`；本文即 brain-web/2 的最终字段集合。

> **当日第四次定稿（决议 Q115、Q116）**。两条都**只新增响应字段、不改任何既有字段的含义**
> （`terminal`／`browser_id`／`tasks` 都是此前不存在的键），因此仍不需要 `brain-web/3`：
> ① **Agent 服务的健康状态必须对 Gateway 与浏览器可见**（Q115，§5.3）。核对结论：Brain 侧
> `GET /health` **今天已存在**（`web/service.py:299-309` 注册，实现在 `:177-199`，返回
> `service/protocol/executed/qwen/browser/assets/capabilities`），所以这一条不是"新加接口"，
> 而是**保留 + 定稿字段 + 让我方与浏览器读得到**：Gateway 新增转发、新增 `GET /api/agent/health` 透传，
> 并把结果并入浏览器启动即查的 `GET /api/health`。直接收益是面板能分清
> "Gateway 活着但 Agent 不可达"与"任务失败"这两件一直被我方混在一起显示的事。
> ② **任务运行状态词表归 Brain 所有**（Q116，§7.4）。`/queryTaskState` 的 `state` 是
> **Brain 自定义的任意非空字符串**，Brain 可随时扩充（今天固定五个：`task_store.py:11`
> `已创建/已进入队列/进行中/任务完成/任务失败`）；我方**不得内置状态枚举、不得按状态名判终态**，
> 终态判据改为同一响应里的 **`terminal` 布尔**。规格 §5.15 那张"Agent state → token → 中文文案 → CSS 类"
> 的五态映射表（`local_gateway.py:67-73,126-138`、`editor/src/logic.ts:agentStatusLabel`）**整表作废**，
> 面板改为原样显示上游字符串。`outcome` 五态（§7.3）是**结果分类**，不是运行状态，不受影响、仍然固定。

---

## 1. 场景身份：四元组

一个现场快照由四元组唯一标识：

| 字段 | 类型 | 谁能推进 | 归零时机 |
|---|---|---|---|
| `scene_id` | uint32 | 换场景（Load Scene／预设场景／original 派生／显式新建） | — |
| `scene_version` | uint32 | **只有 Agent 经 Gateway 的写路径**：`/updateWorld`／`/updateItem`／`/addObject`／`/removeObject`（`/commitWorld` 走的就是这条应用路径） | 新 `scene_id` 时取场景文件里写的值 |
| `scene_sub_version` | uint32 ★ | **只有 `setup` 阶段的浏览器本地内容改动**（§1.3 第 ② 类：资产面板加入／删除物体） | `scene_version` 推进时、或读入不带该键的场景文件时 |
| `sceneDigest` | 64 位小写 hex | 无人直接写；对线上文档算出 | — |

`scene_sub_version` 是**顶层可选 uint32**：文件里不写就等于 `0`，因此历史场景文件与
`docs/场景文件描述.md` 的既有字段表**不必改写**；它一旦出现就必须原样保留、原样回读、原样再导出
（§3 的不动点约束）。

### 1.1 为什么要第四元组：内容变更权与版本推进权不重合

浏览器仍然不能改位姿（gizmo 与关节输入已删），但**资产面板在 `setup` 期仍能往现场里加物体、
删物体**。这类改动：

- 真实改变了现场内容 ⇒ 摘要必然变；
- 不是一次 Agent 写入 ⇒ `scene_version` 绝不能变（否则任务计数与现场版本又脱钩）；
- 必须能被 CAS 分辨 ⇒ 否则 Brain 会把"用户加了两个物体之后的现场"当成与上一次的
  同版本冲突而拒收（Brain 现有判据 `session/brain_session.py:109-110` 正是这么做的）。

所以第四元组不是"以后也许有用"的预留位，而是 ② 类入口存在的**直接后果**；即便哪天把面板加物
也关掉，它作为可选字段留在格式里也没有成本。

灯光预设（③ 类）**不参与**这套机制：它根本不写进 `World` 的文档表示，
于是 `scene_sub_version` 不动、`sceneDigest` 不动、`/getWorld` 不动、导出不动，
Brain 侧永远看不到它存在过。这是它对协议的唯一要求。

### 1.2 推进规则（双方共同的不变式）

1. 同一 `scene_id` 内按 **`(scene_version, scene_sub_version)` 词典序严格增大**；
   词典序不增而内容变 ⇒ `browser_scene_version_conflict`；词典序不增且内容也没变 ⇒ 幂等接受
   （同一份文档重复上报不得报错）。
   **`scene_version` 相等而 `scene_sub_version` 更大且阶段为 `setup` 是合法的**（② 类编辑）；
   同样的推进发生在 `agent_owned` 阶段则非法（§4，`manual_edit_forbidden`）。
2. `commitWorld`：目标必须恰好 `previous.scene_version + 1`，且 candidate 的
   `scene_sub_version` **必须为 `0`**（Agent 写入把子版本重新基线化）。Brain 现有的
   `gateway_target_version_invalid`／`gateway_new_scene_version_invalid`
   （`web/gateway.py:149-152`）保持不变，子版本非 0 用新码 `gateway_scene_revision_invalid`。
3. 查询类／仅出计划类任务不调用 `commitWorld` ⇒ 四元组与摘要都不变。
   **任何一方都不得把 `scene_version` 解释成"用户提交任务的次数"**。
4. `scene_id` 变化 ⇒ `browser_new_session_required`（`session/brain_session.py:106-107`）；
   同一 id 下替换 `MetadataRef` ⇒ `browser_asset_replacement_requires_new_id`（`:113-115`）。两条保留。
5. Load Scene／预设场景切换**不自增版本**：生效版本就是文件里写的值（`docs/场景文件描述.md` §1）；
   文件不带 `scene_sub_version` 时按 `0`。它同时改变 `scene_id`，因此必然走第 4 条的新会话路径。
6. 整型检查沿用 `web_uint32_required`（`web/protocol.py:44-45`），并**把 `scene_sub_version` 纳入
   同一套 uint32 检查**。除它之外 brain-web/2 不新增顶层字段，`scene_schema_version` 仍为
   `Literal[1]`（`contracts/scene.py:195`）。

### 1.3 浏览器入口的三分类（本文对"手动编辑"的唯一定义）

**① 删除，任何阶段都不存在**（我方移除实现，不是禁用后保留）：

- gizmo 平移／旋转／缩放（含工具栏三把工具键）；
- Details 面板的关节角度输入（`allow_details_joint_angle_edit` 整个常量作废）。

**② 阶段闸门：`setup` 期可用，`agent_owned` 期禁用并弹窗**（点击进入时弹
"任务已下发，现场由 Agent 持有，不能手动增删物体"，不得静默无响应）：

- 资产面板"把模型／机械臂加入世界"；
- 层级面板的本地删除／新增；
- `Load Scene`（本地文件）与资产面板的预设场景切换——**这两个已在 `agent_owned` 期被 §4 冻结**，
  本轮把它们与面板增删并入同一道闸门、同一种提示。
- 每一次成功的 ② 类改动 ⇒ `scene_sub_version += 1`，并向 Gateway 重新上报现场（§5.8 的
  `browser.state_sync` 通路）。

**③ 渲染层本地：任何阶段都可用（持锁期除外，§7.2），但绝不出浏览器**：

- 灯光预设（§4.8.1，Q77 修订为"只影响渲染"）；
- Auxiliary layers（视锥／灯球／路点显隐）、轨道查看与缩放视角、选中与 Details 只读读数、
  `Load Traj` 与播放、视口截图、导出下载（§4.8.2 的既有契约）。
  ③ 类全部**不改四元组、不改摘要**，因此不构成 CAS 事件。

**改现场的两方**：Agent（推进 `scene_version`，唯一能落 `commitWorld` 的一方）与
`setup` 期的浏览器面板增删（只推进 `scene_sub_version`）。

---

## 2. 场景格式与解析：唯一真值与强制口径

**场景格式以 `docs/场景文件描述.md` 与规格 §3 为准，Brain 现有 `SceneConfig` 的严格 Schema 不是场景格式。**
Brain 的解析器必须是"**原样保留 + 类型化视图**"双层：文档层是逐字段保真的那份 JSON（摘要对象、回读来源），
视图层只是取已知字段的便捷入口，**视图层的默认值回退绝不允许写回文档层**。

以下 8 条是 Brain 解析器的硬性要求（完整依据见 `docs/AgentBrain修改点.md` §A1）：

1. **未知 `component_type` 不中断**：告警并原样保留（规格 §3.4）。
2. **`properties` 未声明字段不得丢弃、改名、换算**（规格 §3.4/§3.8，决议 Q6）。
   Brain 侧任何形式的 `extra="forbid"` 拒绝或"解析时剥掉不认识的键"都属违规。
3. **字段缺失按默认值回退，不报错**（规格 §3 组件表）：`Transform` 缺 `position`=`[0,0,0]`、
   缺 `quaternion_xyzw`=`[0,0,0,1]`、缺 `scale`=`[1,1,1]`（任一分量 ≤0 整体退回 `[1,1,1]`）、
   缺 `parent`=null（`0xFFFFFFFF` 亦映射 null）；**完全没有 `Transform` 的物体按单位位姿处理并且仍然创建**；
   **同一 `component_type` 重复出现只保留第一个并告警**（这两条分别对应
   `contracts/scene.py:176-178` 的 `scene_requires_one_transform` 与 `:179-180` 的 `scene_component_duplicate`，
   两者都必须从拒绝降级为告警）。
4. **拒绝粒度是物体／子树，不是整场景**：`object_id_in_scene` 缺失／非 uint／重复 → 拒绝该物体；
   `Transform.parent` 指向不存在的 id 或成环 → 拒绝该子树；前向引用必须靠两遍解析支持。
   被拒项进 `rejected_objects[]`，其 `index` **是提交数组 `objects[]` 的下标**（规格 §3.6，Q59）。
5. **`RobotAttachment` 覆盖语义**：`transform.position`/`transform.quaternion_xyzw` 覆盖 `Transform`
   同名字段，**不论后者是否存在**；`Transform.scale`/`parent` 仍生效（`docs/场景文件描述.md` §4.8，Q73）。
   因此挂载物体的 `Transform` 里出现位姿是**真实文件的既有形态**，解析端读取时忽略它，而不是拒绝它：
   已上线的 `docs/ur5e_passive_rig.json` 里物体 4（挂在 `wrist_3_link` 的 `type:"model"` URDF）
   的 `Transform` 就同时带 `position` 与 `quaternion_xyzw`。
   `parent_object_id` 与 `Transform.parent` 不一致、`parent_object_id` 非合法 uint32、
   `transform` 两份都没有 → **退回"当普通 Transform 处理"并告警**，不拒绝物体。
6. **宽容回退（不得升级为错误）**：`RobotDriver.role` 缺失或不是 `"passive"` 一律按 `"arm"` 且不告警
   （Q107）；`MetadataRef.type` 非 `model`/`robot` → 告警后由 `path` 形式决定（§4.2）；
   `Light.type` 未知 → Ambient；`intensity` 非有限 → 1；`color` 不可解析 → 白；
   `Camera` 的 `fov/near/far/resolution` 归一化**只发生在读取层，不回写数据**（Q12）。
7. **关节字典的键不要求 ⊆ `joint_sequence`**：`initial_joint_positions_rad` 与 `now_joint_positions_rad`
   可以命名任何关节名（含 `<mimic>` 派生关节与写错的名字），未知名字按 §4.7 **告警并跳过**；
   `joint_limits` 缺失合法（真实夹爪就没有它），有 `joint_limits` 时也**只约束它命名的关节**。
8. **`now_joint_positions_rad` 是内容**：它由 Agent 侧 `/updateItem` 写入并进摘要；
   浏览器只读显示它（合并口径：`initial` 打底、`now` 逐条覆盖、未命名的关节保持当前角）。

Brain 需要的挂载点世界位姿由自己算（`parent_link` 局部系 + 当前关节 FK），**不得要求场景文件提供世界位姿**。

---

## 3. 摘要（`sceneDigest`）

1. **对象是"传输层收到的那一份 JSON"**，不是任何解析／校验／重导出之后的模型。
   Brain 现在 `digest(scene)` 里那次 `model_dump(mode="json")`（`web/protocol.py:12-15`）必须去掉
   （或只允许规范形文档进这个函数）。
2. 算法：RFC 8785（JCS）规范化 + SHA-256，64 位小写 hex。键按 UTF-16 码元升序、数组保持顺序、
   `1` 与 `1.0` 同一规范形式、拒绝 NaN/Inf、**不做 Unicode 归一化**。
3. **无容差**：摘要比较只有相等／不相等。几何容差属于几何校验，不适用于摘要。
4. 摘要覆盖整份文档：`scene_schema_version`、`scene_id`、`scene_version`、**`scene_sub_version`**、
   `scene_name`、`objects` 与全部组件 `properties`，**包括 §2 里那些"本期不参与计算"的未知字段与
   `now_joint_positions_rad`**。字段集合 = `brain-web/1` 的顶层列表 + `scene_sub_version`，
   除此之外不增不减。
5. **不动点约束**（Brain 必须用测试钉住）：
   `digest(parse(x).document) == digest(x)`，且对同一现场两次 `getWorld` 得到同一 hex。
   只要解析会改写文档，`read_live → digest` 与 `submit → digest` 就会分叉，
   Brain `web/gateway.py` 现有十处 digest 相等判断（`:69,106,123,138,146,155,172,190,200,253`）全部失效。
   **特别注意**：把缺失的 `scene_sub_version` 回退成 `0` 只发生在**视图层**；文档层若没有这个键就
   继续没有这个键，否则"读旧文件"与"算旧文件摘要"直接分叉。
6. ③ 类渲染层改动（灯光预设、辅助图层）**不进文档**，因此"摘要相同 ⇒ 现场内容相同"仍然成立；
   反过来"同 `scene_version` 不同摘要"是**合法**的，当且仅当 `scene_sub_version` 变大且阶段为
   `setup`。我方前端的对应正控制测试：面板加一个物体 ⇒ 摘要变、`scene_version` 不变、子版本 +1；
   切灯光预设 ⇒ 三者全不变。
7. 摘要算法与字段范围的任何变更都必须走 `brain-web/3`，不得在 `brain-web/2` 内部悄悄改。

---

## 4. 会话阶段机

```
                     ┌──────────┐  第一次 /startTask 被接受  ┌─────────────┐
   页面加载 /sessions │  setup   │ ────────────────────────► │ agent_owned │
                     └──────────┘                            └─────────────┘
```

| 阶段 | 切场景（Load Scene／预设场景） | 面板增删物体（② 类） | 渲染层（③ 类） | 允许的任务 |
|---|---|---|---|---|
| `setup` | **允许**（切场景 = 新 `scene_id` ⇒ 新会话） | **允许**，每次成功 `scene_sub_version += 1` 并上报 | 允许 | 无 |
| `agent_owned` | **禁止**，弹窗 + `scene_switch_forbidden_after_first_task` | **禁止**，弹窗 + `manual_edit_forbidden` | 允许（不出浏览器） | 查询／计划／场景写回 |

- 阶段由 **Gateway 权威持有**并持久化。浏览器有三个读数点：WS 广播 `session.phase_changed`（★新帧）、
  `GET /api/sessionState?browser_id=`（★新端点，刷新后找回阶段用）、以及 Brain 侧 `GET /getWorld`
  的 `X-Session-Phase` 头。三者必须同源，不一致时以 `/api/sessionState` 为准并重取现场。
- 阶段转换发生在 **Gateway 把用户消息受理为任务的那一刻**（= `/startTask` 被 Brain 接受，幂等，只写一次），
  Brain 必须在 `/sessions` 响应里回 `session_phase`。**"向 Agent 发送消息后即禁用"就是这条边**：
  用户点发送、任务受理成功，② 类入口在同一次渲染里变灰并挂上弹窗，不需要用户刷新。
- 防线是**三层**（三道都必须在，缺一道就只剩"前端自觉"）：
  ① 前端禁用入口并在点击时弹窗说明原因（用户体验层）；
  ② Gateway 用持久阶段做 CAS 与转发判定，`agent_owned` 期收到 `scene_sub_version` 推进的上报即拒绝（权威层）；
  ③ Brain 对收到的现场再校验一次阶段与四元组（`manual_edit_forbidden`，防御层）。
- `agent_owned` 期 Brain 收到的现场只可能是「它自己上一次写回的结果」或「任务受理时的快照」，
  因此 `expected` 四元组的比对就是完整判据。
- **解除 `agent_owned` 的唯一途径是显式新建／切换会话**（`POST /sessions`），不是刷新页面。
  刷新后 Gateway 用持久化的 `browserID` 找回阶段，浏览器重新 `getWorld`，② 类入口保持禁用态。
- 租约（§7.2）**不是**阶段：租约期必然落在 `agent_owned` 内，租约只管停播与冻结切场景，
  编辑闸门一律由阶段决定，不由租约决定。

---

## 5. 端点与字段（定稿形状）

`X-` 开头的是响应头／请求头；带 ★ 的是 brain-web/2 新增或语义变更。

| 方向 | 端点 | 关键载荷 |
|---|---|---|
| B→G | `GET /api/runtimeConfig` | `gateway.port` 必须等于实际监听（8099） |
| B→G | `GET /events`（WS） | 上行 `browser.hello{browser_id}` 与 `browser.state_sync{world}`（★ 文档含 `scene_sub_version`）；`browserID` **持久化** ★ |
| G→B | `browser.request` | 定向到绑定浏览器，**写入永不广播** ★ |
| Brain→GW | `POST /sessions` | `{browserID, sessionID?, camera_id}` → `{sessionID, session_phase, browserID, camera_id}` ★ |
| Brain→GW | `GET /sessions?browser_id=` | `{sessionID, session_phase, lease, quarantine}` ★ |
| Brain→GW | `GET /brainCapabilities?browser_id=` | `{protocol:"brain-web/2", browserID, capabilities[]}` ★ |
| Brain→GW | `GET /getWorld?browser_id=` | 响应头见 §5.1，**永不回缓存** ★ |
| 前端→GW | `POST /api/agent/jobs` ★ | `{command, scene, clientRequestID}`（场景由浏览器 `World.toJSON()` 原样提供） |
| 前端→GW | `GET /api/sessionState?browser_id=` ★ | `{session_phase, lease, quarantine, scene_id, scene_version, scene_sub_version, sceneDigest}`（刷新后找回阶段） |
| GW→Brain | `POST /startTask` | `{command, scene, sceneDigest, scene_id, scene_version, scene_sub_version, sessionID, clientRequestID, browserID}` → `{taskID, state, terminal:false}` ★ |
| GW→Brain | `GET /queryTaskState` ★ | `{taskID, state, terminal}` —— `state` 是 **Brain 自定义字符串**，`terminal` 是**唯一终态判据**（§7.4） |
| GW→Brain | `GET /queryTaskFailureReason` ★ | `{taskID, terminal, failureReason}`——产出条件是 **`terminal && outcome=="failed"`**，非失败终态回 `failureReason:null` 且必须 200（§7.4 第 7 条） |
| GW→Brain | `GET /queryTaskResult` | 终态 result 见 §7.3（`outcome` 五态仍为固定契约） |
| GW→Brain | `GET /tasks/{taskID}/artifacts/{name}` | 白名单四项 |
| Brain→GW | `POST /acquireSceneLease` | `{taskID, browserID, scene_id, scene_version, scene_sub_version, sceneDigest}` ★ |
| Brain→GW | `POST /releaseSceneLease` | `{browserID, leaseToken, keepLocked}` → `{browserID, state}` |
| Brain→GW | `POST /commitWorld` | `{transactionID, browserID, expected{scene_id, scene_version, scene_sub_version, sceneDigest}, scene}` ★ |
| Brain→GW | `GET /queryWorldCommit?transactionID=` | 持久回执，浏览器刷新后仍可核对 ★ |
| Brain→GW | `POST /resolveUncertain` ★ | 字段见 §8.3 |
| Brain→GW | `GET /allocateObjectID` ★ | `{browserID, count}` → `{object_ids:[uint32…]}`，§6 |
| Brain→GW | `GET /captureScene`／`GET /get2DAABB` | 身份字段校验，§9 |
| GW→Brain | `GET /health` ★ | Brain 服务自身健康，字段见 §5.3；**已存在**，本次定稿字段与用途 |
| 前端→GW | `GET /api/agent/health` ★ | Gateway **原样透传**上面的响应（不裁剪、不改写、不缓存超过 5 秒），不可达时返回 §5.3 定义的 `unreachable` 视图 |
| 前端→GW | `GET /api/health` ★ | 今天只有 `{status,mode,uptimeSeconds}`（`local_gateway.py:361-362`），本次补 `agent_service`／`browser`／`assets` 三个分项 |

### 5.1 `GET /getWorld` 响应头（全部必填）

```text
X-World-Source: live                 # 唯一取值；cache 分支删除
X-Browser-ID: browser-7
X-Playback-State: stopped
X-Scene-ID: 1
X-Scene-Version: 3
X-Scene-Sub-Version: 2               # ★ 缺省 0；文档与头必须同源
X-Scene-Digest: <对响应正文这份 JSON 的 JCS+SHA256>
X-Next-Object-ID: 12                 # 持久高水位，> 所有现存 id，上限 2^32-1
X-Session-Phase: agent_owned         # ★
```

整型头、`X-Scene-Digest` 与响应正文必须来自**同一次现场读取**；不得用上次缓存的摘要配对本次正文。
`X-Scene-Sub-Version` 与正文里的 `scene_sub_version` 不一致 ⇒ 该次读取整体作废
（Brain 用 `browser_scene_version_conflict` 拒绝）。

### 5.2 capabilities（名字由我方定稿）

```json
{"protocol":"brain-web/2","browserID":"browser-7",
 "capabilities":["atomic_commit","sub_versioned_scene_identity","setup_only_local_edits",
                 "bound_browser","task_edit_lock","canonical_scene","agent_owned_phase",
                 "uncertain_recovery"]}
```

Brain 必须按**名字**判断能力（`{"atomic_commit", …} <= capabilities` 那套子集检查继续有效），
不得用版本号推断行为。逐项承诺：
`canonical_scene` = §2 的宽容解析 + §3 的摘要对象；
`sub_versioned_scene_identity` = 四元组 + §1.2 的词典序判据 + commit candidate 子版本必为 0；
`setup_only_local_edits` = §1.3 第 ② 类只在 `setup` 生效，于是 `agent_owned` 期任何子版本推进都是违规
（Brain 据此回 `manual_edit_forbidden`）；`viewport` 第 ① 类入口（gizmo／关节输入）在我方页面**已不存在**，
Brain 不必为位姿与关节的手动改动设计任何例外；
`agent_owned_phase` = §4 的阶段校验；`uncertain_recovery` = §8.3。
**八项缺一即 `gateway_protocol_upgrade_required`**（`atomic_commit`／`bound_browser`／`task_edit_lock`
沿用现有契约，其余五项本次定稿）。灯光预设（③ 类）不需要任何能力项：它不进协议、不进文档。
上一稿的 `versioned_manual_edits` 与 `viewport_read_only` 两个名字**都不得使用**——前者是未分阶段的
旧口径，后者在 Q114 之后语义已经不成立（面板在 `setup` 期能加物）。

### 5.3 Agent 服务健康（Q115 新增小节）

**Brain 侧 `GET /health`（8500，已存在，本次定稿字段与用途）**

```json
{"service":"ready","protocol":"brain-web/2","executed":false,
 "qwen":"ready|unavailable|model_not_found",
 "browser":"bound|not_bound","browser_id":"browser-7|null",
 "assets":"ok|unconfigured|{matched:false,error}","capabilities":{ … },
 "tasks":{"active_task_id":12|null,"queued":0}}
```

- `[必须]` 现有六个键（`service`／`protocol`／`executed`／`qwen`／`browser`／`assets`）与
  `capabilities` 的**取值口径不变**——核对基线 `web/service.py:177-199`，它已经在探 Qwen 与 OLS。
- `[必须]` 新增 `browser_id`（当前绑定浏览器，未绑定为 `null`）与 `tasks`（`active_task_id`／`queued`）。
  两者都是**诊断用**：占用判据仍然是 Brain 自己的 `task_busy` 拒绝，绑定判据仍然是 Gateway 的持久状态。
- `[必须]` **进程活着就返回 HTTP 200**，依赖坏掉只在分项里表达。不得因为 Qwen 或 OLS 不可达返回 5xx——
  Gateway 必须能区分"这个服务没起"和"这个服务起了但它的依赖坏了"。
- `[必须]` 该路由只读、无现场数据、不鉴权（本期无鉴权，§11）。
- `[不得]` 任何一方不得依据 `/health` 自行解除编辑锁或 `quarantined`（§8.3 的六步是唯一解锁路径）。

**Gateway 侧（我方新增，两处）**

| 路由 | 行为 |
|---|---|
| `GET /health` | 向 `agent_service_url + /health` 发一次请求，超时 **3 秒**，响应体**原样透传**。不可达／超时／非 JSON ⇒ `502 {"status":"unreachable","detail":"…"}`，**不是 200** |
| `GET /api/agent/health` | 浏览器用的同一条透传。缓存上限 **5 秒**（面板 15 秒轮询，不打穿 Brain），命中缓存时在响应头 `X-Agent-Health-Age` 里给出秒数 |
| `GET /api/health`（已有，`:361-362`） | 从 `{status,mode,uptimeSeconds}` 扩为 `{status,mode,uptimeSeconds, agent_service:{status,detail}, browser:{connected,browser_id}, assets:{reachable}}`。`agent_service.status ∈ {ready, degraded, unreachable}`：任一非 `ready`／`bound`／`ok` 分项 ⇒ `degraded`；`assets.reachable` 以 `GET {library_server_url}/list?type=model` 为准（`editor/src/library.ts:227-230` 用的就是这条路由，不新造探活路径） |

- `/api/health` 的三个分项**不阻塞彼此**：任一分项超时即单独记 `unreachable`，整体仍返回 200，
  因为"Gateway 自己活着"是这条路由的主语。
- 健康结果**绝不写进 job 视图**：Agent 不可达时正在跑的任务保持原状，按 §7.4 的轮询失败上限处理，
  不得因为一次探活失败把任务判成失败。

---

## 6. 对象 id 分配

- 唯一权威是 **Gateway 磁盘上的持久高水位**（`var/gateway_state.json`）。推进水位的三类事件：
  Agent 写回里含的新对象、Gateway 转发 `/addObject` 时的申领、**Gateway 采纳浏览器上报的现场**
  （`browser.state_sync`／`getWorld`）时取 `max(已存水位, 文档里所有 object_id_in_scene + 1)`。
  于是"浏览器在 `setup` 期本地分配过的一串 id"一定会被抬进持久水位，Gateway 之后发的号段不会撞它。
- `setup` 期浏览器**仍会本地分配 id**（资产面板加物，§1.3 第 ② 类），但必须遵守：
  本地计数器**只能用 `X-Next-Object-ID` 做种子**向上单调，不得只从文档里现有 id 推
  （否则"新增→删除→刷新"会复用旧 id，正是对方回函 §3.1 的反例）；
  进入 `agent_owned` 后浏览器不再有任何分配点（② 类入口已禁用），刷新也不解禁。
- 只升不降；删除不回退；刷新不丢；释放的 id 永不复用（规格 §5.5）。
- **Agent 增物前必须申领**：`GET /allocateObjectID{browserID, count}` → 号段，Gateway 原子推进水位。
  Brain 组 candidate 需要 N 个新 id 时一次领 N 个；离线增物本期不支持。
- 上限 **`2**32 - 1`**。水位到达上限时 Gateway 明确拒绝并返回 `object_id_space_exhausted`。
- Brain 侧：`X-Next-Object-ID` 的合法性检查必须收到 `<= 2**32 - 1`（今天 `web/gateway.py:109` 写的是
  `<= 2**32`，差一个数）；`scene_object_id_reused` 检查保留（Brain 自身水位 + Gateway 水位取较大者，
  现有 `session/brain_session.py:129-131` 逻辑不变）。

---

## 7. 任务与结果

### 7.1 提交

```
用户点"发送" → 前端复用 clientRequestID → POST /api/agent/jobs {command, scene, clientRequestID}
  Gateway：向绑定浏览器实时取**当时**现场，校验头自洽（含 X-Scene-Sub-Version 与正文同源）
        → POST /startTask {command, scene, sceneDigest, scene_id, scene_version, scene_sub_version,
                           sessionID, clientRequestID, browserID}
        → 拿到 taskID 建 job（非终态）→ 广播 agent.job_updated
  Brain：接受即把会话阶段置 agent_owned（幂等）；Gateway 同批把 ② 类入口禁用状态广播给浏览器
```

- 用户看到的画面与 Gateway 此刻取到的现场**同源**，因为改内容只有两条路（② 类推进子版本、
  Agent 写入），两条都会反映进同一份文档；③ 类（灯光预设）不改文档，因此**它对协议不可见**，
  也就不会出现"画面变了但现场没变"的 CAS 歧义（§3 第 6 条）。
- 同会话同 `clientRequestID` 且载荷相同 ⇒ 返回原任务；同 id 不同内容 ⇒ `request_id_reused`
  （Brain 现有码，`session/brain_session.py:263,511`）。
- 上一任务未终态时新请求 ⇒ `task_busy`。缺上下文字段 ⇒ `session_context_required`。
- Gateway 对 `scene` 只做"是不是 JSON 对象"与尺寸校验，**永不解析其语义**（规格 §5.15.1）。

### 7.2 执行期（编辑锁）

```
Brain → POST /acquireSceneLease {taskID, browserID, scene_id, scene_version, scene_sub_version, sceneDigest}
Gateway：校验绑定 + 四元组现场 → 停/拒轨迹播放 → 冻结切场景入口 → 灯光预设复位并冻结 → {browserID, leaseToken}
此后 Brain 的每个 Gateway 请求带 X-Brain-Lease，Gateway 验归属
Brain →（可选）POST /commitWorld，见 §8.1
Brain → POST /releaseSceneLease {browserID, leaseToken, keepLocked:false} → {state:"released"}
```

- 锁的语义是**三件事**：不许播放（采集要静止）、不许换场景（身份要稳定）、不许换灯光预设
  （§9 的像素可重复性）。② 类编辑不由锁管——租约期必然已在 `agent_owned` 内，
  编辑闸门在阶段那一层已经关掉了（§4）。
- 锁**不因超时自动解除**。断线、未知、超时一律保持 `quarantined`／待确认。

### 7.3 结果展示（Brain 的 `outcome` 是唯一分类依据，`executed` 恒 `false`）

| outcome | 前端显示 | 禁止 |
|---|---|---|
| `scene_updated` | 场景已更新（+ 新的 `(scene_id, scene_version+1, 0, sceneDigest)`，子版本重新基线化） | "机械臂执行成功" |
| `answered` | 回答文本 | — |
| `clarification_required` | 澄清问题（`reply`），等用户补充 | 当成失败或当成已执行 |
| `plan_ready` | **计划已生成，尚未执行** + 技能顺序 + 产物下载 | 任何"完成执行"字样 |
| `failed` | 失败原因（附原始结构化错误） | 静默变"成功" |

技能顺序取 `plan.commands`；Qwen 调用数取 `metrics.model_calls`（必须是真实调用计数）；
产物只列白名单四项 `scene_config`／`scene_patch`／`commands`／`query_result`；`debug/` 与服务器路径不展示不下载。

### 7.4 轮询与状态显示（Q116：运行状态词表归 Brain）

```
Gateway 每 agent_poll_interval_seconds（默认 5 秒）跑一轮，只对 terminal == false 的 job：
  → GET {agent_service_url}/queryTaskState?taskID=<int>
  → {taskID, state:<Brain 自定义字符串>, terminal:<bool>}
  → terminal 翻 true ⇒ GET /queryTaskFailureReason + GET /queryTaskResult
                    ⇒ 落 outcome / reply / plan / metrics / artifacts → 广播 → 停止轮询该 job
```

| # | 规则 | 落点 |
|---|---|---|
| 1 | `state` 是**不透明字符串**：Gateway 与浏览器**不得内置状态枚举、不得翻译、不得按状态名判断结束**。Brain 增加、改名、合并状态都不需要我方改代码 | 删 `AGENT_STATES`（`local_gateway.py:67-73`）、删 `agent_status_for`（`:126-138`）的映射语义、删 `editor/src/logic.ts:agentStatusLabel` 的五 token 映射 |
| 2 | **唯一终态判据是 `terminal == true`**。字段缺失或不是布尔 ⇒ 按 `false`（非终态）处理并 `LOGGER.warning` | 轮询循环 |
| 3 | job 视图字段：`agent_state`（上游原文，UI 直接显示）、`terminal`（布尔）、`outcome`（终态后才有的固定五值）、`state_detail`（Brain 可选给的进度文本，原样透传，无则 `null`） | `GET /api/agent/jobs[/{id}]` |
| 4 | CSS 类不再由状态名派生：`is-pending`（`terminal==false`）／`is-done`／`is-failed`（按 `outcome`）；结果区块仍按 §7.3 的 `outcome` 五态 | `main.ts` 状态渲染、`logic.ts` |
| 5 | **404 语义不变**：Brain 不再认识这个 `taskID`（通常是它重启过）⇒ 该 job 由 Gateway 置终态、`outcome="failed"`、`agent_state` 写上游 `error` 原文。这是"任务不存在"的事实，不是状态词 | 现有 `:303-308` |
| 6 | **传输类失败不判失败**：连不上／超时／响应非 JSON ⇒ 保持非终态并累计连续失败次数，达 **5 次**（≈25 秒）才落 `failed` 并停止轮询。Q116 不改这条上限，Q115 也不许用一次 `/health` 失败提前判死它 | 现有轮询 |
| 7 | `queryTaskFailureReason` 的产出条件从"状态名等于 `任务失败`"改为 **`terminal && outcome == "failed"`**；非失败的终态返回 `failureReason: null`，不得返回 404 或空对象 | Brain 工单 §A11 |
| 8 | `/startTask` 的响应也带 `terminal`，**必须为 `false`**。若上游给出 `terminal:true`，Gateway 不接受它建终态、记 warning，一切以第一次 `/queryTaskState` 为准 | `start_task` |
| 9 | 幂等（`clientRequestID`）、`task_busy`、`session_context_required` 与状态词表无关，全部不变 | §7.1 |

- **运行状态**与**结果分类**是两件事，不要混：`state` 是 Brain 的自由词表（进程此刻在做什么），
  `outcome` 是 brain-web/2 的固定五值（这次任务对用户意味着什么，§7.3）。本次只把前者放开，后者不动。
- 我方不再提供中文文案的映射表，因为词表放开后**任何按名字的翻译都会在上游新增状态的那天变成错译**。
  原样回显上游字符串是唯一不会错的口径；文案归 Brain 负责（它今天返回的五个态本来就是中文）。

---

## 8. 事务、恢复与故障

### 8.1 原子提交（全有或全无）

```
Brain 组 candidate：scene_version = previous.scene_version + 1，scene_sub_version = 0
Brain 落 prepared 记录 → POST /commitWorld {transactionID, browserID, expected{…四元组…}, scene}
Gateway：整份 candidate 交给**绑定浏览器**，先全量校验后一次落地
  成功 → 持久回执 committed {transactionID, browserID, status, scene_id, scene_version,
          scene_sub_version, sceneDigest, rejected_objects:[]}
  明确拒绝（校验失败、现场不符）→ 回执 rejected {reason, rejected_objects:[…]}，现场零改动
  传输失败／超时 → 只 GET /queryWorldCommit + 读 live 比对；**绝不重发**；查不到即 unknown 并保持锁
Brain 再做 live 回读 digest 相等才继续
```

- candidate 里 `scene_sub_version != 0` ⇒ `gateway_scene_revision_invalid`（Agent 写入必须把子版本
  重新基线化，否则"用户 `setup` 期加的两个物体"与"Agent 新加的一个物体"会算进同一个计数器，
  CAS 再也分不清是谁写的）。

- 任何拒绝都不得部分落地；同事务同内容只生效一次，同事务异内容 ⇒ 冲突。
- 浏览器刷新后 `queryWorldCommit` 仍能给出回执（回执在 Gateway 磁盘，不在浏览器）。
- `rejected` 必须携带**该事务未部分修改现场**的证据（回执 + live 比对一致）；
  仅超时、找不到回执、浏览器断线都只能算 `unknown`。`unknown` 不得按定时器变成 `rejected`。

### 8.2 故障矩阵

| 情形 | 行为 |
|---|---|
| 服务重启 | 中断任务 → `service_restarted`；执行中的会话 → `uncertain`；**不自动重放、不自动解锁** |
| commit 超时 | 查回执 + 读 live；匹配 → `committed`，否则 `unknown` 并保持不可写 |
| 解除 quarantine | 只走 `POST /resolveUncertain`（§8.3） |
| 旧计划 | 恢复后不得复活为可执行；不覆盖 `original`；不宣称回滚过浏览器操作 |
| 双臂／不支持的平台 | `web_platform_profile_unsupported` + 人类可读原因；前端按 `failed` 显示，不得显示执行成功 |

### 8.3 `POST /resolveUncertain`（字段定稿）

```json
{"browserID":"browser-7","sessionID":"s-1","transactionID":"<hex>",
 "evidence":{"receipt_status":"committed|rejected|missing","live_digest":"<hex>",
             "expected_digest":"<hex>","late_write_excluded":true},
 "resolution":"resume|new_session"}
```

响应：`{state:"resolved|kept_locked|quarantined", sessionID, scene_id, scene_version, scene_sub_version, sceneDigest, reason}`

流程固定为六步，任何一步不满足就返回 `kept_locked`：
① 保持现场锁定 → ② 查明原事务与当前活动浏览器 → ③ 排除迟到写入（旧 `leaseToken`/`transactionID` 已失效）
→ ④ 读 live 并校验 → ⑤ 结论与证据持久化 → ⑥ 才决定续用原会话（不覆盖 `original`）或显式建新会话。
**新建 `/sessions`、切换浏览器、重启服务、改数据库都不构成解锁证据**；人工确认文本也不构成证据。

---

## 9. 相机与视觉

```
Brain → GET /captureScene?id=<会话绑定的 camera_id>&type=<rgb|rgbd>&browser_id=<绑定>
Brain → 对每个候选 model 物体 GET /get2DAABB?id=&camera_id=&browser_id=
采集前 read_live、采集后 read_live，两次 digest 必须相等
```

- 相机 ID **在会话创建时显式选定**：`POST /sessions{camera_id}`，Brain 持久化该绑定，
  original 派生后按 `id_remap` 更新；首次绑定后不得改（要换相机 = 新会话）。
  我方 Gateway 只提供候选清单（现场带 `Camera` 的物体），**不做任何猜测**：
  UR5e 空模板同时有 ID4 腕部与 ID5 顶视，"读现场"只给候选。
- 采集响应／框响应必须齐备 `browserID/scene_id/scene_version/scene_sub_version/sceneDigest/playback_state/width/height`，
  逐项与本次现场一致，缺项或旧值即 `camera_frame_scene_mismatch`。播放中、旧缓存、错浏览器、
  尺寸不符、PNG 不完整一律拒绝。
- 灯光预设不改文档，因此**摘要相等并不保证像素相等**。Brain 不得把像素差异当成"现场被改过"
  的证据；采集的可重复性由 §7.2 的第三条保证——**持锁期内灯光预设复位为「跟随场景」并禁用**，
  于是两次采集之间像素只可能因现场变化而变。
- `rgb` 相机无深度；`rgbd` 深度为 `width*height` 个小端 float32（米，NaN 表示未命中）。
- segmentation 本期不支持，明确拒绝，不生成占位数据。
- 采集期间持有编辑锁（§7.2：停播 + 冻结切场景）。

---

## 10. 错误码（新增／变更／撤回）

Brain 现有码表是基线；brain-web/2 新增四枚，`browser_scene_revision_conflict` 仍然**不实现**
（四元组的"词典序不增"用现有码就够，改名只会让两边码表多一份对账）。

| 码 | HTTP | 含义 | 归属 | 状态 |
|---|---|---|---|---|
| `scene_switch_forbidden_after_first_task` | 409 | `agent_owned` 期切场景（Load Scene／预设场景） | Gateway／浏览器 | **新增** |
| `manual_edit_forbidden` | 409 | `agent_owned` 期出现 ② 类改动（收到 `scene_sub_version` 推进的上报或带新对象的 `state_sync`） | Gateway（权威）／Brain（防御） | **新增**（Q114 恢复：② 类入口仍在，只是被阶段关掉） |
| `gateway_scene_revision_invalid` | 400 | `commitWorld` candidate 的 `scene_sub_version != 0` | Brain／Gateway | **新增**（Q114 恢复） |
| `object_id_space_exhausted` | 409 | 持久高水位达 `2**32-1` | Gateway | **新增** |
| `browser_scene_version_conflict` | — | `(scene_version, scene_sub_version)` 词典序不增而内容变；或头与正文的子版本不一致 | Brain | **语义扩展到四元组**（码名不变） |
| `gateway_new_scene_version_invalid`／`gateway_target_version_invalid` | — | commit 目标不是恰好 `v+1` | Brain | **保留原样**（`web/gateway.py:149-152`） |
| `browser_scene_revision_conflict` | — | — | — | **撤回，不得实现**（与上一行同义，两套码会让反向对账测试出现两个真值） |
| `INVALID_WORLD_SCHEMA` | 400 | 顶层结构非法（§2 的缺失字段**不属于**此类；缺 `scene_sub_version` 属正常） | Gateway／浏览器 | 既有 |

其余沿用规格 §5.13 与 Brain 既有码（`browser_new_session_required`、
`browser_asset_replacement_requires_new_id`、`scene_object_id_reused`、`request_id_reused`、
`camera_frame_scene_mismatch`、`gateway_object_allocator_invalid`、`web_uint32_required`、
`gateway_protocol_upgrade_required`、`task_busy`、`session_context_required`、
`web_platform_profile_unsupported`）。双方错误码表必须逐条对齐，反向对账测试同规格 §13.15 的口径。

---

## 11. 端口与部署（已定稿，我方 P0 已落）

| 端口 | 用途 |
|---|---|
| **8099** | 正式联调 Gateway（我方 `config/constant_config.json`、`local_gateway.py`、`vite.config.ts`、`start-dev.ps1` 已迁） |
| 8500 | Brain AgentService |
| 8000 | OLS，双方同一版固定资源 |
| 8080 | 现有 Qwen 模型服务，不改其运行配置；**从此不再用作 Gateway** |
| 8098 | WebEditor 一次性验证栈（带 `X-Standalone-Verification: 1`），**不得作为 brain-web/2 联调对象** |

首期全部本机回环。Brain 的资源路径基准由 Brain 自己的配置文件负责；
我方配置文件不含相对资源路径（资产走 OLS URL，`dist/` 相对代码文件解析），
Gateway 的部署脚本与 runtimeConfig 必须与实际监听一致。

---

## 12. 决议表：对来函 C1–C6 与回函各节的最终答复

这一节是决定，不是问题。双方实现按本文，回函里的"待回复"作废。

| 编号 | 议题 | 我方决定 |
|---|---|---|
| D1 | 手动编辑的刻度（C1） | **`scene_sub_version` 保留，四元组定稿**（Q114，取代当日 Q113 的"收回三元组"）。三个候选里采用第三个（子版本字段），但**范围被压到最小**：只有 §1.3 第 ② 类（面板增删物体）会推进它，且只在 `setup` 阶段可用；位姿与关节的手动入口（第 ① 类）直接删除，灯光预设（第 ③ 类）改成渲染层、不进文档。**代价由我方承担**：gizmo 三把工具与 Details 关节输入从我方页面移除（规格 §4.8 就地改写），面板增删加阶段闸门与弹窗。§1、§4 |
| D2 | 摘要范围与 JCS（C2） | 完整文档进摘要、包含版本字段、无容差、不删字段；**摘要对象改为收到的 JSON 字节**，并加不动点约束。§3 |
| D3 | 场景解析严格性 | **Brain 重写解析器**以匹配 §2（我方 `docs/场景文件描述.md` + 规格 §3）。`extra="forbid"`、"挂载物体不得带 pose"、"非挂载物体必须带 pose"、"Transform 必须恰好一个／组件不得重复"这四类入口拒绝撤除；拒绝粒度改为物体／子树 + `rejected_objects[]`。 |
| D4 | 事务与 ID（C3） | 回执落 Gateway 磁盘 + `queryWorldCommit` 持久；ID 由 Gateway 持久水位单一权威给出、**Agent 增物前申领**（`/allocateObjectID`），上限 `2**32-1`；浏览器只在 `setup` 期本地分配，且必须以 `X-Next-Object-ID` 为种子，Gateway 采纳上报时把水位抬到 `max(持久, 文档最大 id + 1)`。Brain 的 journal 必须可回读对账；明确拒绝与 unknown 分离。§6、§8 |
| D5 | quarantine 恢复（C4） | 采用 B 类显式入口，字段与六步流程按 §8.3 定稿，Brain 直接实现。 |
| D6 | 相机与多标签页（C5） | `camera_id` 进 `POST /sessions`，Brain 持久化绑定；第二标签页允许连 `/events` 且只读。§9 |
| D7 | 阶段与场景切换 | 首任务后进入 `agent_owned`：**切场景冻结 + ② 类增删冻结（点击弹窗）**；`setup` 期浏览器仍可改现场，但只能推进子版本。§4 |
| D8 | 材料与交付（C6） | Brain 交付：宽容解析器 + 非空成对夹具 + 我方场景兼容性测试 + 无 Qwen 桩服务 + 真实 `clarification_required` 样例。我方交付：8099 新发布包（含 `config/constant_config.json` 与 `dist/`）。§11、`docs/AgentBrain修改点.md` §A8 |
| D9 | 双臂 | 前端可展示，任务侧拒绝；Brain 必须给出 `web_platform_profile_unsupported` 的人类可读原因字段与契约样例。§8.2 |
| D10 | 锁的语义 | 编辑锁管三件事：**停播**、**禁止切场景**、**灯光预设复位并冻结**（§7.2）。② 类编辑不由锁管，由阶段管（§4）。Brain 在持锁期内可以假定像素与身份同时稳定。 |
| D11 | 灯光预设（Q114 新增） | 灯光预设**只影响浏览器渲染，不出浏览器**：不写进 `World` 的文档表示 ⇒ 不进 `toJSON()`、不进导出、不进 `/getWorld`、不进摘要、不推进 `scene_sub_version`。它因此对协议完全不可见，Brain 不需要为它设计任何判据。规格 §4.8.1 与 **Q77** 就地改写为"渲染层覆盖"，**不废止**（废止的是它的持久化，不是它的可用性）。 |
| D12 | 入口三分类（Q114 新增） | 本文 §1.3 是"手动编辑"的唯一定义：**① 删除**（gizmo／关节输入）、**② 阶段闸门**（面板增删、切场景；`agent_owned` 期禁用且**点击必须弹窗**，不得静默无响应）、**③ 渲染层本地**（灯光预设与一切查看类）。任何一方不得在这三类之外自行恢复或新增入口。 |
| D13 | Agent 服务健康（Q115 新增） | Brain 的 `GET /health` **保留并定稿字段**（§5.3，核对结论：已存在，不是新增接口）；Gateway 新增 `GET /health` 转发与 `GET /api/agent/health` 透传，并把 `agent_service`／`browser`／`assets` 三分项并进浏览器启动即查的 `GET /api/health`。硬口径：进程活着就 200、依赖坏了只在分项里表达、健康结果不得写进 job 视图、不得作为解锁依据。 |
| D14 | 任务状态词表（Q116 新增） | **词表归 Brain**：`state` 是任意非空字符串，我方可随时接收未知值而不改代码；终态判据改为响应里的 **`terminal` 布尔**。我方删除五态映射表与 `agentStatusLabel` 的 token 映射，面板原样回显上游文案；`queryTaskFailureReason` 改按 `terminal && outcome=="failed"` 产出；`outcome` 五态不动。规格 §5.15 的映射表（`:368-379`）就地作废。 |

---

## 13. 联调验收顺序（替身不算，缺外部资源的用例必须显示 skip）

1. **场景兼容性**（先决）：Brain 用我方 7 份 OLS 场景 + `docs/ur5e_table_empty.json` +
   `docs/ur5e_passive_rig.json`（含物体 4 那份"挂载物体带 Transform pose"的真实形态）+
   一份"含未知组件与未知字段"现场，全部解析成功、`digest` 与文档层一致、未知字段原样回读。
2. **会话与身份**：持久 `browserID`、`/sessions` 新建／恢复／切换（含 `camera_id`）、第二 tab 只读。
3. **入口三分类（§1.3）**：① 类在页面上不存在（无 gizmo 工具键、无关节输入框，`allow_details_joint_angle_edit`
   常量已删）；② 类在 `setup` 可用、在 `agent_owned` 禁用且**点击弹窗**；③ 类灯光预设改完摘要不变。
   正控制：面板加一个物体 ⇒ `scene_sub_version +1`、`scene_version` 不变、摘要变；
   负控制：灯光预设切换 ⇒ 三者全不变，且 `getWorld` 正文逐字节相同。
4. **摘要一致**：TS 与 Python 对同一份**非空**文档算出同一 hex（成对夹具逐条比对，含"仅子版本变"一例）。
5. **阶段冻结**：首任务后 `Load Scene`、预设场景切换、面板增删都被拒（前两者
   `scene_switch_forbidden_after_first_task`，第三者 `manual_edit_forbidden`）、
   刷新后阶段仍在、`agent_owned` 期 `Load Traj`／播放／导出／截图／灯光预设**仍可用**（§4）。
6. **原子提交**：CAS、明确拒绝零落地、重复事务不重复应用、刷新后仍可核对回执、
   candidate 子版本非 0 被 `gateway_scene_revision_invalid` 拒。
7. **恢复**：kill Gateway 造 `unknown` → `resolveUncertain` 六步闭环 → 重新可写。
8. **相机**：真实截图、框与图同一现场、真实 Qwen 视觉消歧。
9. **连续对话**：`setup` 期用户面板加两个物体（子版本 0→2，本地 id 取自 `X-Next-Object-ID` 种子）→
   发任务（子版本 2 随 `/startTask` 上报，Brain 记为基线）→ Agent 加物（申领 id，`scene_version +1`、
   子版本归 0）→ Agent 改色 → 查询任务（四元组全不动）→ 删除续聊 →
   连续两次 original → Commands v2 产物；全程 `scene_version` 只在 Agent 写回时 `+1`，
   子版本只在 `setup` 期由浏览器推进。
10. **服务健康（Q115）**：Brain `GET /health` 返回 §5.3 全部分项；把 Qwen 停掉后**仍返回 200**
    且 `qwen:"unavailable"`（负控制：依赖坏掉不得变成 5xx）；把 Brain 停掉后浏览器
    `GET /api/health` 的 `agent_service.status == "unreachable"`，且**正在跑的 job 不受影响**
    （只有 §7.4 第 6 条的连续 5 次轮询失败才落 `failed`）；`/api/agent/health` 的
    `X-Agent-Health-Age` 不超过 5 秒。
11. **状态词表（Q116）**：用替身服务回一个我方从没见过的字符串（例如 `"规划中"`）⇒
    任务保持非终态、继续轮询、面板原样显示这四个字；替身改 `"规划中"+terminal:true` ⇒ 立刻停轮询并出
    `outcome` 区块；替身省略 `terminal` ⇒ 按非终态处理并留 warning 日志。
    全程我方代码里**不存在**状态名常量（`AGENT_STATES` 与 `agentStatusLabel` 的 token 映射已删）。

---

## 14. 时间轴：一次完整任务里谁在什么时候调什么

参与者：**用户** / **浏览器**（`editor/dist`，WS 客户端）/ **Gateway**（我方 `local_gateway.py`，8099）/
**Brain**（`AgentService`，8500）/ **OLS**（8000，静态资源）/ **Qwen**（8080，Brain 内部使用）。
"状态"列：**现** = 本仓库已实现；**新** = brain-web/2 新增；**改** = 已存在但载荷或语义变了。
WS 帧类型：上行 `browser.hello`／`browser.state_sync`／`browser.response`；下行 `browser.request`；
广播 `scene.applied`／`agent.job_updated`／**`session.phase_changed`（★新）**。除此之外不得自造帧类型。

### 14.1 阶段 A：启动与建联（`setup`）

| # | 发起 → 接收 | 调用 | 发出什么 | 返回什么 | 状态 |
|---|---|---|---|---|---|
| A1 | 浏览器 → Gateway | `GET /api/runtimeConfig` | 无参 | `{gateway:{host,port:8099}, agent_service_url, ols_base_url, traj_*, viewport_*}` | 现 |
| A2 | 浏览器 → Gateway | WS `GET /events` → `{type:"browser.hello",payload:{browser_id}}` | `browser_id` | 不单独回帧；Gateway 记 `browser_id→socket`，此后 `browser.request` 只定向它 | **改**：`browserID` 落盘持久化，刷新/第二 tab 认领同一现场 |
| A3 | Gateway → 浏览器 | WS `browser.request{request_id, action:"getWorld", payload:{}}` | 要求回读当时现场 | 浏览器 `{type:"browser.response", request_id, ok:true, payload:{world}}`；Brain 侧的 `GET /getWorld` 就是这条通路加 §5.1 的头部 | 现（★ 载荷新增子版本） |
| A4 | 浏览器 → OLS | `GET` 资产列表／模型文件 | — | 资产元数据与 `.glb`/URDF | 现（不变） |
| A5 | 浏览器 → Gateway | `GET /api/health`（启动即查，此后 15 秒轮询）★ | 无参 | `{status, agent_service:{status,detail}, browser:{connected,browser_id}, assets:{reachable}}`；其中 `agent_service` 由 Gateway 现向 Brain `GET /health` 取（3 秒超时，缓存 ≤5 秒） | **改**：今天只有 `{status,mode,uptimeSeconds}`（`local_gateway.py:361-362`） |

### 14.2 阶段 B：用户在 `setup` 期准备现场

| # | 发起 → 接收 | 调用 | 发出什么 | 返回什么 | 状态 |
|---|---|---|---|---|---|
| B1 | 用户 → 浏览器 | Load Scene 文件／预设场景切换 | 本地文件或 OLS 预设 | 页面重建现场，`scene_id` 变 ⇒ 后续必走 C2 的新会话 | 现 |
| B2 | 浏览器 → Gateway | WS `{type:"browser.state_sync",payload:{world}}` | 整份现场文档（**含 `scene_sub_version`**） | 广播 `{type:"scene.applied",scene_version,action,source_request_id}` 给其他 tab | **改**：Gateway 采纳时把 id 水位抬到 `max(持久, 文档最大 id + 1)` |
| B3 | 用户 → 浏览器 | 资产面板"加入世界"／层级面板删除 | 无网络调用 | 现场多／少一个物体，`scene_sub_version += 1`，然后重放 B2 | **新**：子版本推进；仅 `setup` 可用 |
| B4 | 用户 → 浏览器 | 灯光预设切换 | **无任何网络调用** | 只有画面变；`toJSON()`/导出/摘要/`getWorld` 全不变 | **改**（Q114：渲染层覆盖） |
| B5 | 用户 → 浏览器 | gizmo／Details 关节输入 | — | **入口不存在**（① 类已删） | **新**（删除） |

### 14.3 阶段 C：下发任务（阶段边 = 从这里开始）

| # | 发起 → 接收 | 调用 | 发出什么 | 返回什么 | 状态 |
|---|---|---|---|---|---|
| C1 | 浏览器 → Gateway | `POST /api/agent/jobs` | `{command, scene, clientRequestID}` | `{id,task_id,state,...}`（job 视图）；同 `clientRequestID` 同载荷 ⇒ 原任务 | **改**：新增幂等 `clientRequestID` |
| C2 | Gateway → 浏览器 | WS `browser.request{request_id, action:"getWorld"}` → 浏览器 `{type:"browser.response",request_id,ok,payload:{world}}` | 取**当时**现场 | 现场 + 四元组 + 摘要，头/正文同源 | **改**：不得用 B2 的缓存替代 |
| C3 | Gateway → Brain | `POST /startTask` | `{command, scene, sceneDigest, scene_id, scene_version, scene_sub_version, sessionID, clientRequestID, browserID}` | `{taskID, state, terminal:false}`；拒绝 ⇒ 错误码原样透传给前端 | **改**：现在只发 `{command, scene}`，响应新增 `terminal`（§7.4 第 8 条） |
| C4 | Brain → Gateway | `GET /sessions?browser_id=` 或 `POST /sessions` | `{browserID, sessionID?, camera_id}` | `{sessionID, session_phase:"agent_owned", browserID, camera_id}` | **新**：阶段在此翻牌 |
| C5 | Gateway → 浏览器 | WS 广播 `{type:"session.phase_changed", payload:{browser_id, session_phase:"agent_owned"}}` **★新帧** | 阶段翻牌 | ② 类入口置灰；用户再点 ⇒ **弹窗**"任务已下发，现场由 Agent 持有" | **新** |
| C6 | Gateway → Brain | `GET /queryTaskState?taskID=`（每 5 秒，只针对 `terminal==false` 的 job）★ | `taskID` | `{taskID, state, terminal}`——`state` 是 **Brain 自定义字符串**，原样存进 `agent_state`；**停止轮询只看 `terminal`，不看状态名**（§7.4） | **改**：词表归 Brain，我方五态映射表作废 |
| C7 | 前端 → Gateway | `GET /api/agent/jobs`／`GET /api/agent/jobs/{jobId}` | job id | `{agent_state（上游原文）, terminal, state_detail?, outcome?}`；状态变化另有 `agent.job_updated` 广播 | **改**：字段口径见 §7.4 第 3 条，面板文案不再由我方产出 |

### 14.4 阶段 D：Brain 执行（持锁）

| # | 发起 → 接收 | 调用 | 发出什么 | 返回什么 | 状态 |
|---|---|---|---|---|---|
| D1 | Brain → Gateway | `GET /brainCapabilities?browser_id=` | — | `{protocol:"brain-web/2", browserID, capabilities[8]}` | **新**：八项能力（§5.2） |
| D2 | Brain → Gateway | `POST /acquireSceneLease` | `{taskID, browserID, scene_id, scene_version, scene_sub_version, sceneDigest}` | `{browserID, leaseToken}` | **新**（Brain 侧已有调用，我方路由待实现） |
| D3 | Brain → Gateway | `GET /getWorld?browser_id=`（`read_live`） | 带 `X-Brain-Lease` | 现场 + 头；digest 与 `scene_sub_version` 必与 D2 一致 | 改 |
| D4 | Brain → Gateway | `GET /captureScene?id=<绑定的 camera_id>&type=<rgb\|rgbd>&browser_id=` | 带 `X-Brain-Lease` | PNG／深度 + `browserID/scene_id/scene_version/scene_sub_version/sceneDigest/playback_state/width/height` | 改（§9） |
| D5 | Brain → Gateway | `GET /get2DAABB?id=<候选>&camera_id=&browser_id=` | 同上 | 屏幕框 + 同一份身份字段 | 现 |
| D6 | Brain → Gateway | `GET /allocateObjectID?browserID=&count=N` | — | `{object_ids:[N 个 uint32]}`，水位原子推进 | **新** |
| D7 | Brain → Gateway | `POST /commitWorld` | `{transactionID, browserID, expected{四元组}, scene}`（candidate 子版本必为 0） | `{status:"committed"\|"rejected", scene_id, scene_version, scene_sub_version, sceneDigest, rejected_objects[]}` | **新** |
| D8 | Gateway → 浏览器 | WS `browser.request{action:"updateWorld", payload:{world}}` | 整份 candidate | `{type:"browser.response", ok:true}` ⇒ 落地一次；浏览器再 `browser.state_sync` 上报 | 改 |
| D9 | Brain → Gateway | `GET /queryWorldCommit?transactionID=` | 超时／断线后**只查不重发** | 持久回执（磁盘，不在浏览器） | **新** |
| D10 | Brain → Gateway | `POST /releaseSceneLease` | `{browserID, leaseToken, keepLocked:false}` | `{state:"released"}`；灯光预设解冻 | **新** |

### 14.5 阶段 E：结果与异常

| # | 发起 → 接收 | 调用 | 发出什么 | 返回什么 | 状态 |
|---|---|---|---|---|---|
| E1 | Gateway → Brain | `GET /queryTaskFailureReason`＋`GET /queryTaskResult`（都在 C6 报 `terminal:true` 之后各取一次） | `taskID` | `failureReason`（产出条件＝`terminal && outcome=="failed"`，§7.4 第 7 条）+ 终态 `outcome ∈ {scene_updated, answered, clarification_required, plan_ready, failed}`、`executed:false` | 改（§7.3、§7.4） |
| E2 | Brain → Gateway | `GET /tasks/{taskID}/artifacts/{name}` | 白名单四项名 | `scene_config`／`scene_patch`／`commands`／`query_result` 内容 | **新** |
| E3 | Gateway → 浏览器 | `agent.job_updated` 广播 + 前端轮询 | 结果视图 | 前端按 outcome 显示；`plan_ready` 必须写"尚未执行" | 改 |
| E4 | Brain → Gateway | `POST /resolveUncertain` | §8.3 的六步证据体 | `{state:"resolved"\|"kept_locked"\|..., 四元组, reason}` | **新** |
| E5 | 浏览器 → Gateway | `GET /api/agent/health` ★（→ Gateway → Brain `GET /health`） | 无参 | Brain 的 §5.3 响应**原样透传**；不可达／超时 ⇒ `502 {status:"unreachable", detail}`，与任何 job 的状态无关 | **新** |

### 14.6 五条最容易踩的顺序约束

1. **C2 必须在 C3 之前**：`/startTask` 里的 `scene`／`sceneDigest`／`scene_sub_version` 必须是同一次
   实时读取的结果；用 B2 的缓存会让用户 `setup` 期最后一次加物被吞掉。
2. **D3/D4 必须在 D2 之后、D10 之前**：`read_live → 采集 → read_live` 两次摘要相等，
   且灯光预设在这段里被冻住（§7.2、§9）。
3. **D7 失败后只能走 D9，不得重发 D7**；D9 无回执 ⇒ `unknown` 并保锁，解锁只有 E4 一条路。
4. **停止轮询的唯一依据是 C6 的 `terminal`**：`state` 字符串在我方代码里不得有任何分支（Q116）。
   一旦按名字判终态，Brain 未来新增一个状态就会让任务永远停在半路；反过来把未知名字误判成进行中，
   面板就再也分不清"服务在动"和"我们猜的"。
5. **健康检查与任务判定互不干涉**（Q115）：A5/E5 失败只能改服务状态条，不得改 job 状态；
   job 状态只由 C6 的 `terminal`、404、以及"连续 5 次轮询失败"上限三者决定。
