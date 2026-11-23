# 致 Brain 侧：brain-web/2 定稿函（取代 2026-10-19 的确认函）

- 发函方：WebEditor／Gateway（`F:\web-frontend`）
- 收函方：Brain（`F:\robot_agent_brain\robot_agent_brain`，核对基线 `80f4d1a`）
- 日期：2026-10-20（当日第四次定稿，决议 **Q114、Q115、Q116**；本函是最终形态）
- 性质：**定稿通知**。本函不再是讨论稿，也不要求逐条回复。

## 0. 本函作废了哪些先前表述

上一版（2026-10-19）末尾有 7 条"请回复的确认项"，正文里还有几条**已被我方自己推翻**的表述。
它们连同你回函（`docs/webeditor_teammate_confirmation.md`）末尾的 C1–C6 一起作废，
由下面三份文档收编，**以这三份为准**：

| 文档 | 作用 |
|---|---|
| `docs/gateway与Agent新通信流程.md` | brain-web/2 协议正文：四元组身份、场景格式与摘要、会话阶段、端点字段、恢复流程、验收顺序、**§14 完整调用时间轴** |
| `docs/AgentBrain修改点.md` | **你侧施工单**：解析器重写、摘要改造、事务与恢复、相机绑定、**§A11 服务健康与运行状态词表**、交付物与完成定义 |
| `docs/gateway修改点.md` | 我方施工单与施工顺序 |

明确撤回的三条，逐条说明为什么撤回：

1. "`(scene_id, scene_version)` 是任务提交次数的刻度" —— 错。查询与仅出计划的任务不调用
   `commitWorld`（你在回函 §2.1.5 的指正成立），版本从来不是任务次数。
2. "我方按去掉 `scene_version` 后求摘要实现" —— 不采用。摘要继续覆盖整份文档（含版本字段），
   要动的是**摘要对象**（收到的那份 JSON 字节），不是摘要范围。
3. **"四元组作废"这一条本身作废**（当日 Q113 → 同日 **Q114** 修正）：上一段我写的
   "浏览器取消一切手动编辑、`scene_sub_version` 整套作废、你方版本判据一字不改即可用"**不成立**。
   我方入口的最终处置是三分类（流程文档 §1.3）：
   **① 删除**——gizmo 平移/旋转/缩放、Details 关节角度输入；
   **② 阶段闸门**——资产面板加入／删除物体与切场景，只在 `setup` 阶段可用，
   **用户向 Agent 发出消息后即禁用并弹窗**；
   **③ 渲染层本地**——灯光预设只改浏览器怎么画，不进文档、不进导出、不进摘要。
   因为 ② 还在，"同 `scene_version` 而内容不同"在 `setup` 期是**合法现场**，
   所以 **`scene_sub_version` 保留**、身份是四元组、你方 §A3 的版本判据**必须改成词典序**，
   `manual_edit_forbidden` 与 `gateway_scene_revision_invalid` 两枚码也恢复要求。
   给你方的净影响只有一句话：**上一稿的"不用改判据"撤销，请按 §A3 的码改。**

**另两条是新增定稿，不是撤回**（正文见 §2 第 5、6 条，施工落点 `docs/AgentBrain修改点.md` §A11）：

4. **Q115 服务健康可见**：我方上一稿把 `GET /health` 写成"四分项保留"一句带过，现在核对到你方
   实现（`web/service.py:299-309` 注册、`:177-199` 实现，`scripts/webeditor_preflight.py:21` 已在用它），
   所以要求收敛为**三件小事**：字段定稿、新增 `browser_id`／`tasks` 两键、保住"进程活着就 200"。
   Gateway 侧新增转发与透传，浏览器从此能分清"Gateway 活着但 Agent 不可达"和"任务失败"。
5. **Q116 运行状态词表归你方**：我方**取消**brain-web/1 里那五个状态字符串的约定（`已创建`／
   `已进入队列`／`进行中`／`任务完成`／`任务失败`），并删掉我方的映射表与前端 token 文案。
   这不是让你方少做事——恰恰相反，你方要新增 `terminal` 布尔、把 `queryTaskFailureReason`
   的产出条件从状态名改成 `terminal && outcome=="failed"`，并把自己测试里按名字判结束的断言改掉
   （`brain_tests/test_web_service.py:40`）。换来的是你方以后加状态不用通知我方。

## 1. 场景格式：唯一真值在我方，解析器由你侧重写

`docs/场景文件描述.md` 与 `docs/Web前端需求规格v2.md` §3 是场景格式的权威文本
（规格 §3 开头那句"结构以本节为准；逐组件的取值口径见 `docs/场景文件描述.md`"就是定序）。
你侧 `contracts/scene.py` 的 `SceneConfig` 严格 Schema **不是**场景格式，而是它的一个过窄子集，
实测已经拒掉我方已上线的真实场景文件：

```
SceneConfig.model_validate(docs/ur5e_table_empty.json)  -> OK
SceneConfig.model_validate(docs/ur5e_passive_rig.json)  -> REJECT: ('objects',3,'components',2,'role') extra_forbidden
```

因此要求是明确的：**按规格 §3 的宽容口径重写解析器**（原样保留 + 类型化视图双层，
默认值回退不回写文档，拒绝粒度到物体／子树并回报 `rejected_objects[]`），
并撤除这几条与格式冲突的入口拒绝：已知组件的 `extra="forbid"`、
`robot_attachment_transform_must_omit_pose`（`:186-188`）、
`transform_pose_required_without_attachment`（`:189-190`）、
`scene_requires_one_transform` 与 `scene_component_duplicate`（`:176-180`，降级为告警）。
逐条落点、行号、回归测试清单见 `docs/AgentBrain修改点.md` §A1。

关于"挂载物体的 `Transform` 为什么允许带位姿"，**依据换了一条，请注意**：
上一稿我引的是我方 Q80"任何物体都可以拖"——那个入口现在删了。剩下的依据是格式本身与真实文件：
`docs/场景文件描述.md` §4.8 写的是**覆盖**语义（挂载位姿覆盖 `Transform` 的同名字段，"不论后者是否存在"），
而我方已上线的 `docs/ur5e_passive_rig.json` 里物体 4 的 `Transform` 就同时带
`position` 与 `quaternion_xyzw`。这条与浏览器有没有编辑功能无关，仍然必须实现。

这一条是准入门。它不通，后面每一项都会在真实数据上失败。

## 2. 我方已经定案、不再讨论的六点

1. **端口**：联调 Gateway **8099**（我方 `config/constant_config.json`、`local_gateway.py`、
   `start-dev.ps1`、`editor/vite.config.ts` 已落地，`/api/runtimeConfig` 的 `gateway.port` 同一个数）；
   **8098 是 WebEditor 一次性验证栈**（响应带 `X-Standalone-Verification: 1`），不得作为联调验收对象；
   OLS 8000、Brain 8500、Qwen 8080 不变。请把你侧配置默认指向 8099。
2. **两条旧规约已授权废止**：写入不再对所有浏览器广播，只发绑定浏览器；
   `GET /getWorld` 不再回缓存，`X-World-Source: live` 成为唯一取值，无绑定浏览器即 `503 NO_BROWSER_CONNECTED`。
3. **现场身份是四元组**：`(scene_id, scene_version, scene_sub_version, sceneDigest)`。
   `scene_version` 只由落到浏览器现场的 Agent 写操作推进（`/updateWorld`／`/updateItem`／`/addObject`／
   `/removeObject`，`/commitWorld` 走的就是这条应用路径），目标恰好 `previous + 1`，且 candidate 的
   `scene_sub_version` **必须为 0**；`scene_sub_version` 只由 `setup` 期浏览器的 ② 类增删推进；
   查询与仅出计划的任务两者都不动。`scene_sub_version` 是**可选顶层 uint32**，
   缺失即 `0`，历史场景文件一律合法。
   摘要对象仍然是"收到的那一份 JSON 文档"，因此**必须包含**该键（缺键与写 `0` 是两份不同文档）。
4. **会话阶段**：第一次任务被接受后进入 `agent_owned`，此阶段**冻结切场景与 ② 类增删**
   （我方前端置灰 + 点击弹窗，Gateway 权威拒绝，你方再校验一次——三道防线，流程文档 §4）；
   编辑锁的语义是三件事：停播、禁止切场景、灯光预设复位并冻结（§7.2、§12.D10）。
   第二标签页允许连 `/events` 但只读。
5. **Agent 服务的健康必须可达浏览器，但只到"状态条"这一层**（Q115）：`GET /health` 字段按
   `流程文档 §5.3` 定稿（六键口径不动，新增 `browser_id`／`tasks`），**进程活着就返回 200**，
   Qwen 或 OLS 坏掉只在分项里表达；探测要在 3 秒内返回（我方转发超时 3 秒、缓存 ≤5 秒）。
   边界同时定死：健康读数**不得进 job 视图**，任何一方都**不得**据它解除编辑锁或 `quarantined`——
   解锁仍然只有 `/resolveUncertain` 一条路。
6. **任务运行状态词表归你方，终态判据是 `terminal`**（Q116）：`/queryTaskState` 的 `state` 是
   **任意非空字符串**，由你方定义、可随时扩充，我方不再持有状态名常量，也不得被你方要求同步词表；
   `/queryTaskState` 与 `/startTask` 的响应必须带 **`terminal` 布尔**，那是我方的**唯一**停轮询依据
   （缺失 ⇒ 非终态 + warn）。`terminal` 必须与你方内部那套状态名同源一处派生，不许两处各判。
   `outcome` 五态（`scene_updated`／`answered`／`clarification_required`／`plan_ready`／`failed`）
   是**结果分类**，仍是固定契约，本轮不动。

## 3. 你侧交付物（时间由你方排，验收判据已写在施工单里）

> **编号与 `docs/AgentBrain修改点.md` §A8 完全一致（B1–B10）**。上一稿本函与施工单各有一套 B 编号
> （同名不同物），那是我方文档的疏漏；**以后以 §A8 为唯一编号**，本表只是索引。

| 项 | 内容 | 判据落点 |
|---|---|---|
| B1 | 宽容解析器 + 我方真实场景兼容性测试 | §A1、§A1.8 |
| B2 | `digest()` 改为对收到的文档求摘要 + 两条不变式测试 | §A2 |
| B3 | **成对夹具**（非空真实场景：`scene.json` + 规范化字节 + 期望 digest + 相等／不等标记） | §A8.B3 |
| B4 | §A3 词典序判据 + `X-Next-Object-ID` 上限收到 `2**32-1` + journal 可回读 | §A3、§A5、§A6.1 |
| B5 | `/resolveUncertain` 按流程文档 §8.3 的定稿字段实现六步恢复 | §A6.3 |
| B6 | 会话内显式绑定 `camera_id`；能力按**名字**八项门控；`_frame_identity` 与 `expected`／租约载荷**加 `scene_sub_version`**；§A3.1 判据与 §A4 的 `manual_edit_forbidden` **必须同批交付** | §A3.2、§A4、§A7.1–A7.3 |
| B7 | 无 Qwen 的 Brain 桩服务（合成数据必须标 `synthetic`），**且能喂任意状态字符串** | §A8.B7、§A11.5 |
| B8 | 真实 `clarification_required` 样例 | §A8.B8 |
| **B9 ★** | `GET /health` 字段定稿：六键口径不动 + 新增 `browser_id`／`tasks` + **进程活着即 200** | §A11.1–A11.2 |
| **B10 ★** | 状态词表：`/queryTaskState` 与 `/startTask` 带 `terminal`；`failureReason` 改按 `terminal && outcome=="failed"` 产出；你方测试与桩服务不再按状态名判结束 | §A11.3–A11.6 |

**不需要你方做的**（本函明确取消，别浪费工时）：`scene_sub_version` 之外的任何顶层字段；
错误码改名（`browser_scene_revision_conflict`）；能力项 `versioned_manual_edits`／
`sub_versioned_manual_edits`／`viewport_read_only`；为"用户拖动位姿或改关节角"设计的任何校验或例外
（① 类入口已删，永不恢复）；为灯光预设设计的任何协议字段（③ 类**不出浏览器**，你方永远看不到它）；
**状态词表的双方同步与兼容层**（Q116 之后我方不持有状态名常量，你方加／改名状态无需通知我方）；
**在 `terminal` 之外再留一处按状态名判结束的代码**（§A9.8）。
详见 `docs/AgentBrain修改点.md` §A8 末段。

我方对应交付：8099 新发布包（含 `config/constant_config.json` 与 `dist/`）与版本号 ——
你回函 §一 说"尚未收到新源码／发布包核验"，这条由我方在 P4 关闭，你方不必等待。

## 4. 本期双方都不做的事

不接 Control、不发轨迹执行、不做 IK／物理抓取、双臂只展示不接任务；`executed` 恒 `false`；
不做 segmentation；不做动态资产上传；不做多用户／登录鉴权／用户隔离
（理由与最小前置见 `docs/Agent服务集成修改计划.md` §8）；不做公网部署；不提供无证据强制解锁；
**不做位姿与关节的手动编辑（① 类已删），也不做撤销／重做**；② 类只到"加／删物体"为止
（三分类与闸门施工点见 `docs/gateway修改点.md` §2）。
界面必须按 `outcome` 五态区分，`plan_ready` 固定显示"计划已生成，尚未执行"，
任何终态都不得出现"机械臂执行成功"；**任务的运行状态不做任何一方的翻译表**，
面板原样显示你方 `state` 字符串（Q116）。

## 5. 变更途径

本文三份文档构成 brain-web/2 的完整承诺。此后任何一方要改变字段含义、摘要范围或版本判据，
**必须升 `brain-web/3` 并同批更新夹具**；不允许在 `brain-web/2` 内部各自解释。
实现过程中的缺陷修复走契约测试，不走往返确认。

本函只新增／修订文档：不改你方代码、不启动服务、不生成新的真实模型样例、不自动提交或推送。
