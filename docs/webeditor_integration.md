# WebEditor / Gateway 首期联调（brain-web/2）

本期 Brain 只规划，不连接 Control、不发送轨迹、不执行机器人。
`terminal=true` 才表示任务处理终止；`任务完成` 不等于机械臂执行成功，所有结果固定
`executed=false`。

## 当前交付边界

Brain 已增加协议兼容、持久化 AgentService、严格 Gateway 场景/相机适配器。
提供的 WebEditor 1.0.1 发布包 **尚未实现本协议**。需要前端同事提供源码或新包；
不修改 dist 压缩 JS，不降级到非原子的 `updateWorld`。
真实 Qwen/OLS、测试替身、真实浏览器的验证分别记录在 `demo/webeditor/VALIDATION.md`。

## 本地 WebEditor 联调记录（2026-10-25）

上述旧版部署说明与当前工作区的联调配置不一致。此工作区使用 `F:\web-frontend` 的 Gateway 和前端、
`F:\ObjectLibraryServer`、`F:\QwenMock` 与本仓库 Brain；Brain 使用 `config/webeditor_local.json`，
监听 `127.0.0.1:8500`，通过 `http://127.0.0.1:8080/v1` 访问固定响应的 QwenMock。
前端仓库中的 `tools/restart_stack.ps1` 负责每轮停止四服务、备份旧运行态、启动服务并等待 OLS、
QwenMock、Gateway、Brain 健康检查。联调流程和已验证浏览器行为以
`F:\web-frontend\docs\前端和AgentBrain联调流程.md` 为准。

Brain 的首次 OLS 目录校验在 HTTP 服务开始接受请求前完成。后续目录刷新在后台运行，`/health` 读取缓存，
不在 Gateway 的三秒上游时限内扫描 OLS。冷缓存的直接探针会报告 `assets=checking` 并发起后台刷新，
不会同步等待目录读取。

## 本机部署

| 服务 | 地址 | 说明 |
|---|---|---|
| Qwen | http://127.0.0.1:8080/v1 | 沿用已启动服务及 mmproj，不重启、不改端口 |
| Gateway | http://127.0.0.1:8099 | 页面、浏览器路由、任务转发；需升级 |
| OLS | http://127.0.0.1:8000 | 固定资产，无动态上传 |
| Brain | http://127.0.0.1:8500 | 仅回环监听，单工作队列 |

在仓库根目录使用已安装 Brain 的 Python 环境。可选服务依赖：

```bash
python -m pip install -e '.[web]'
```

原始包保留于 `/home/cscvlab/lht/yzk`，解压副本放在仓库外：

```bash
mkdir -p /home/cscvlab/lht/webeditor_runtime
unzip -n /home/cscvlab/lht/yzk/ObjectLibraryServer-1.0.5-rel-res-1.0.5-rel.zip -d /home/cscvlab/lht/webeditor_runtime
unzip -n /home/cscvlab/lht/yzk/WebEditor-1.0.1-rel.zip -d /home/cscvlab/lht/webeditor_runtime
```

OLS 读取同一份 data；Brain 不复制模型到 wheel，不覆盖旧 final_models。
`config/webeditor.json` 的资源路径相对配置文件解析，运行产物路径相对启动目录。
模型名是当前 `/v1/models` 返回的服务端 model ID，部署到别的机器可设置
`ROBOT_BRAIN_MODEL`，而不是重启已有 Qwen。

生成派生缓存与完整 URDF 关节清单（只读资源目录）：

```bash
python scripts/validate_final_models.py \
  --root ../webeditor_runtime/ObjectLibraryServer-1.0.5-rel/data \
  --manifest config/ols_1_0_5_manifest.json \
  --cache var/webeditor/geometry_cache.json \
  --joint-cache var/webeditor/joint_inventory.json
```

各用一个终端启动 OLS、Gateway、Brain；先检查端口，已存在的服务不要重复启动：

```bash
ss -ltnp '( sport = :8000 or sport = :8080 or sport = :8099 or sport = :8500 )'
cd /home/cscvlab/lht/webeditor_runtime/ObjectLibraryServer-1.0.5-rel
python server.py --port 8000
```

```bash
cd /home/cscvlab/lht/webeditor_runtime/WebEditor-1.0.1-rel
python local_gateway.py --host 127.0.0.1 --port 8099
```

注意：旧包的监听 `--port` 与返回给浏览器的 runtimeConfig 不一定同步；
同事还需将 runtimeConfig 的 Gateway=8099、Agent=8500、OLS=8000 一起更新。
仅上述命令启动旧包不代表完成对接。

```bash
cd /home/cscvlab/lht/robot_agent_brain
robot-brain serve --config config/webeditor.json \
  --gateway-url http://127.0.0.1:8099 --ols-url http://127.0.0.1:8000 \
  --joint-inventory var/webeditor/joint_inventory.json --camera-id 5 --port 8500
python scripts/webeditor_preflight.py --browser-id ACTUAL_BROWSER_ID
```

`--camera-id` 是首次绑定场景的明确对象 ID，不按名字猜相机；original 派生后根据明确
id_remap 持久更新绑定，不能继续使用旧 ID。双臂场景可在网页展示，但此服务拒绝初始双臂绑定任务。

## Brain HTTP 契约

所有 POST 必须 `Content-Type: application/json`。由 Gateway 服务端转发；不开放 CORS。
携带 Origin 时仅接受配置的 Gateway origin。服务不接受远程服务 URL。

### 会话

`POST /sessions {"browserID":"browser-1"}` 创建并激活稳定 sessionID。
`POST /sessions {"browserID":"browser-1","sessionID":"已保存的ID"}` 恢复/显式切换。
`GET /sessions` 查看绑定和 uncertain 状态。**scene_id 不是 sessionID**。
忙碌或 uncertain 时不能切换；切换浏览器是显式调用，不靠新请求偷偷抢占。
切换只更新绑定，不写入浏览器；下一轮必须 live 校验。

### 提交与轮询

`POST /startTask`：

```json
{
  "command": "把苹果放进篮子",
  "scene": {"这里替换为完整的Component Scene v1": true},
  "sceneDigest": "完整场景RFC8785序列化后SHA256小写HEX",
  "sessionID": "由sessions接口返回",
  "clientRequestID": "frontend-generated-uuid",
  "browserID": "browser-1"
}
```

上面是字段说明，不是可执行 Scene。运行 `scripts/export_webeditor_contract.py` 导出真实 Schema
和不含模型文件/个人路径的有效协议 fixtures。

快速返回 `{"taskID":1,"state":"已进入队列","terminal":false,"code":0}`；不等待 Qwen。
同会话同 clientRequestID/相同完整请求返回原任务；不同内容 HTTP409。
同一会话仍保持一条未终态任务的互斥（同会话重复提交返回 `task_busy`）；不同会话可以排队到同一个 Brain worker。Gateway 会为每个会话隔离场景快照和租约，因此用户切换到 B 后，A 的晚到提交不会覆盖 B；切回 A 时会读到 A 的最新场景。需要当前浏览器画面的截图时，非活动会话会明确返回 `session_browser_not_active`，不会误读 B 的画面。
缺上下文明确 `session_context_required`；不兼容旧 Gateway 隐式续接方式。

| 接口 | 返回 |
|---|---|
| GET /queryTaskState?taskID=1 | taskID/state/terminal；`state` 是 Brain 自定义非空字符串，不能按名称判断终态 |
| GET /queryTaskFailureReason?taskID=1 | taskID/terminal/failureReason；仅 `terminal=true` 且 outcome=failed 时返回原因 |
| GET /queryTaskResult?taskID=1 | 未完成 HTTP202；完成 HTTP200，详见下面 |
| GET /tasks/1/artifacts/commands | 只读白名单产物；不允许任意路径 |
| GET /health | service/qwen/browser/assets 分项能力，不用单个 HTTP200 代表全部可用 |

终态 result：`outcome=scene_updated|answered|clarification_required|plan_ready|failed`，
固定 executed=false，reply、scene_id/version/digest、metrics.model_calls、plan（完整 Commands）、
artifacts URL、commitReceipts。机器人任务显示“计划已生成，尚未执行”。澄清显示 reply 问题，
不是错误地显示成功执行。模型校验/几何拒绝等处理错误用任务失败，附原始结构化错误；
执行阶段的失败原因由桥按控制端自己的 `demo/error_messages.py` 造句（保留穿透毫米数、
持物滑移毫米数、规划预算这些实测证据，并在句尾带回 `error_code`），控制端目录读不到时
退回原始报文。能力拒绝（`capability_unsupported` 等）也按 `outcome=failed` 返回，并另带
`failure_class=capability_unsupported`；`state` 只在场景落地、回答、出计划或换机器人配置时写
“任务完成”，澄清写“等待澄清”，其余一律“任务失败”——Gateway 只按 `terminal` 判终态，
但面板标题用的就是这个字符串，不能把没做成的事报成完成。

单臂能力门禁只看场景，不看型号名：恰好一台 `role=arm` 且它的场景 `RobotDriver`
与 OLS 条目的 joint sequence/limits 一致即 `supported`（控制端运行时按场景自带的
URDF 解析模型与关节表）。双臂仍必须显式注册 `RobotProfile`，否则规划前就被
`check_turn` 拒绝，拒绝原因拼在错误码后，例如
`capability_unsupported: single_arm_required: scene_has_2_arms`、
`joint_sequence_mismatch: ...`。已知边界：非 UR 关节命名或非 6 关节的单臂能通过
门禁，但仍会在控制端碰撞/关节约束处硬失败。

服务进程重启不会自动重放任务。中断任务变为 `service_restarted`；执行中的会话标记 uncertain，
必须通过 `POST /resolveUncertain` 提交现场、事务回执和迟到写入排除证据后才能恢复；没有证据时保持锁定。
恢复普通空闲会话仅读取 checkpoint，下一轮读 live 现场，不写旧 checkpoint。
同一任务数据库仅允许一个服务进程持有文件锁。

## Gateway 必须新增/扩展的契约

### 能力与现场读取

`GET /brainCapabilities?browser_id=browser-1`：

```json
{"protocol":"brain-web/2","browserID":"browser-1","capabilities":["atomic_commit","sub_versioned_scene_identity","setup_only_local_edits","bound_browser","task_edit_lock","canonical_scene","agent_owned_phase","uncertain_recovery"]}
```

`GET /getWorld?browser_id=browser-1` 返回完整 Scene，必须实时询问指定浏览器，响应头：

```text
X-World-Source: live
X-Browser-ID: browser-1
X-Playback-State: stopped
X-Scene-Digest: <RFC8785 SHA256>
X-Next-Object-ID: <不可回退的实例分配高水位>
```

不能用缓存冒充 live。摘要对整个协议 JSON 做 RFC8785/JCS，再 SHA256；对象键顺序无关，
数组顺序/未知组件/当前关节等内容不忽略。`1` 与 `1.0` 一致。
高水位必须大于所有现存 ID，最大 2^32（表示已耗尽）；所有编辑入口共用并持久化。

`X-Playback-State` 的读入口径按「读的是文档还是像素」分开：`read_live()` 接受 `stopped` 与
`paused`，其余（`playing`/`seeking`）仍抛 `gateway_playback_must_stop`。理由是暂停的画面是一张
静帧，浏览器此刻供出的文档仍是已提交场景——实测一次把苹果放进篮子后停在 `paused` 的读取，
返回的是篮子处的苹果而非屏幕上那一帧；若连 `paused` 也拒，看过上一条轨迹就会让下一轮在任何
理解发生之前直接失败。像素仍然只信 `stopped`：`_frame_identity()` 在播放态不是 `stopped` 时
抛 `camera_frame_scene_mismatch`，所以 `capture()` 拿不到静帧当现场照片。

同一 scene_id 在 `setup` 期的资产面板增删只递增 `scene_sub_version`；Agent 写入才递增
`scene_version` 并将子版本归零。同版本不同内容冲突；删物体不重用 ID；
替换 MetadataRef 用新实例 ID。关节 now 值只是展示，不产生 holding/known 执行证据。
静态机器人、相机/桌子/光源等部署变化要求新会话，不能作为普通编辑悄悄吸收。

### 任务编辑锁

`POST /acquireSceneLease` 输入 `{taskID,browserID,scene_id,scene_version,scene_sub_version,sceneDigest}`。
Gateway 检查当前绑定和现场四元组，停止/拒绝轨迹播放并锁定所有手工编辑入口，返回
`{browserID,leaseToken}`。锁直到显式释放；不要仅因超时自动解锁。
后续 Brain 请求携带 `X-Brain-Lease`，Gateway 验证归属。
`POST /releaseSceneLease {browserID,leaseToken,keepLocked:false}` 返回
`{browserID,state:"released"}`；keepLocked=true 返回 `state:"quarantined"`，继续禁止编辑，
显示待人工确认。断线或未知提交不能自动回到可写。

### 原子提交

`POST /commitWorld`：

```json
{
  "transactionID":"唯一事务ID",
  "browserID":"browser-1",
  "expected":{"scene_id":1,"scene_version":3,"scene_sub_version":0,"sceneDigest":"旧摘要"},
  "scene":{"这里替换为完整目标Scene":true}
}
```

浏览器先验证所有对象/引用/资源，再 CAS 一次提交。任何拒绝均不能部分落地。
同 scene_id 目标版本必须旧版+1；original 派生/显式新场景 ID 允许版本1。
**不额外自增**。保留旧 updateWorld 语义，但 Brain 永不调用它。

成功回执：`{transactionID,browserID,status:"committed",scene_id,scene_version,scene_sub_version,sceneDigest,rejected_objects:[]}`。
`GET /queryWorldCommit?transactionID=...&browser_id=...` 返回持久回执。
同事务同内容只能提交一次；异内容冲突。浏览器刷新后也要能核对事务。
明确拒绝返回 `{transactionID,browserID,status:"rejected",reason:...}`（不修改现场）。
Brain 首期对无法证明成功的结果保守阻塞，宁可人工核对也不盲目重试写入。
POST 超时只查询事务并读 live 比对；不自动重发、不假装回滚。

### 一次任务内的多次提交

一个租约允许多次 `commitWorld`（`web/gateway.py::load_scene`）：

* 每次写的 `expected` 都是「本 Brain 上一份落地/冻结的世界」，目标版本逐次 +1，
  `scene_sub_version` 每次归 0，每次写各得一份独立回执。
* **任务的第一次写**比对 acquire 时冻结的 `lease_snapshot` 副本，因此浏览器正好在握手期间掉线时，
  这一次仍可走 Gateway 的离线兜底分支落地。
* **第二次及以后的写**改用不带 `lease_snapshot` 的 live 读重建 `expected`：冻结副本已被第一次写替换，
  拿它当基准会被大脑自己的 `gateway_scene_conflict` 和 Gateway 的 CAS 同时拒绝。
* 两次写之间落地的面板编辑会在 POST 之前被 `gateway_scene_conflict` 拒绝；若 Gateway 给出可归因的
  `rejected` 回执，则按有据拒绝处理（干净停点），不置 unknown、不进 quarantine。
* 已知边界：浏览器掉线后，同一任务的**第二次**写会在 POST 之前失败——Gateway 的离线兜底判据比对
  `held["world_snapshot"]`，而该字段只在 acquire 时写入、在线 commit 不刷新。要放开这条，需要前端网关
  在每次在线提交成功后同步刷新 `held["world_snapshot"]` 与 `held["scene_identity"]`。
  一句话拆成多个子任务（下一节）时，这条边界同样适用：第 2 步之后的写需要浏览器在线。

### 一句话里的多个子任务

`contracts/decomposition.py` + `models/task_decomposition.py` 的拆分轮（C3b）产出一串有序子任务，
`web/service.py::AgentService._run_steps` 在**同一个租约内**按语义先后逐步执行：场景步 = 一次
`commitWorld`，臂步 = 一次 `dispatch()`（执行 + 执行后写回，即再一次 `commitWorld`）。

* 策略是「分一个做一个」：某步被拒就**停在那一步**，之前落地的世界保留。没有回滚通道——再写一次场景
  本身是新副作用，比留下可见的中间态更危险，所以回复必须点名停在哪一步、后面几步没做。
* 停点：该步 `clarification_required` 或 `failed`；或该步只导出计划（`plan_ready`）而后面还有步骤——
  未执行的导出占着它派生时的场景版本，再往下写就会让给用户看过的计划作废（`stop_reason`
  = `plan_not_executed`）；或该步报告执行成功却没有回写任何物体位姿（`execution_writeback_missing`）——
  下一步的仿真从浏览器文档重建，接着跑等于让后一步作用在一个「据说已被改动、但文档里没有」的世界上；
  或该步结束时夹爪仍持有物体（`arm_still_holding`）——重建出来的机器人手指是空的，手里的物体会同时
  出现在两个地方。后两个停点只断链，单步任务的行为不变。
* 有据的拒绝仍是干净停点：租约正常释放、不进 quarantine，与上一节同一条规则。
* 「没落地」的失败允许重采样：控制端的抓取点和放置点都取自 RGB-D **单像素**深度，同一份原子命令两次跑的
  点会差约 1cm，而篮筐内壁留给夹爪外廓只有约 4mm 余量——同一条「抓篮子里的苹果」在离线探针里 3/3 成功、
  在串链作业里偏了 4.7cm 就抓空；一次「放进篮子」的实测拒绝理由写着 `robotiq_2f85_base` 与 `Basket`
  相距 **0.05mm**，于是 0～10cm 的 11 档放置高度全部判为碰撞。`AgentService.RETRYABLE_EXECUTION_CODES`
  = `GRASP_NOT_CONFIRMED`（闭爪到底、两侧接触力都是 0）、`GRASP_DEPTH_SEARCH_FAILED`（没找到可行抓深）、
  `GRASP_FAILED`（抓到后在 `move_to` 途中掉物）、`PLACEMENT_HEIGHT_SEARCH_FAILED`（未执行放置）、
  `PLACEMENT_PERCEPTION_FAILED`、`PATH_CONSTRAINT_INFEASIBLE`（作业 79 第 ② 步：approach/pick/lift_up 都跑完了，
  `retreat` 却发现手里的苹果已经陷进托盘壁 0.324mm——拒绝的是**这一发物理造出来的状态**，不是场景几何，
  同一条命令在相隔两次尝试里过得去，所以它虽然是个 planning 码也照样重采样）。这些回执都在说「这一技能没有落地」：该步 0 次 commit、场景文档没变、
  下一次 dispatch 仍从浏览器文档重建仿真，所以整步重跑不引入新副作用，换来的是重新采样一次落点。
  上限 `AgentService.MAX_STEP_ATTEMPTS = 5`（篮内抓放的成功率明显低于 100%，一次尝试约 70–150s，
  最坏情况仍留在作业超时内），
  次数写进 `metrics.steps[].attempts`，回复点名是第几次做成的（`（已执行并写回场景、第 2 次尝试）`、
  `重试 4 次后仍未成功`）。其它失败码——尤其派发前就对计划本身下的碰撞判断——重复它不会变好，因此不重试。
* `platform_rebind` 是原子的装配变更，永不拆分；没有拆分阶段、句子本身没有先后语义、或模型不给合法
  拆分时，`decomposition()` 返回 None，走与以前完全相同的单 turn 路径。
* 终态只用既有 outcome 词表，按「最不寻常的事」取优先级：`failed` > `clarification_required` >
  `scene_updated` > `plan_ready` > `robot_configured` > `answered`。分步细节在 `metrics.steps[]`
  （`state` = completed / stopped / not_run，含 kind、instruction、request_id、commits、attempts、verdict），
  `reply` 逐条列出完成与未执行的步骤。
* 拆分上限是 `contracts/decomposition.py::MAX_SUBTASKS = 6`，其中 `robot_task` **可以有多条**：每条形如
  approach→…→retreat 的一抓一放，runner 一次只吃一份原子命令文件，所以步与步之间是串行的、后一步
  从前一步写回的世界继续。跨步指代（「再把他拿出来」「把它…」）要成立靠两条一起：拆分层**不许**把
  「它/他/她」换成对象名（`models/prompt_templates/task_decomposition_v1.txt` 第 4 节），否则「就是刚那个
  对象」这条唯一信息在拆分那一步就被丢掉了；每步仍走一次普通 C3，`DialogueState.contextualize` 在这一步
  自己的 `scene_context` 上把指代词标成 `[dialogue_ref=…]`，`bindings` 用**上一步留下的 focus 实例 id**
  绑定，实例编号不由模型猜。作业 77 的第 4 步就是踩在替换规则上：「把它放到托盘里」被写成「把香蕉放到
  托盘里」，而场景里有两个香蕉，于是停在澄清。改掉这条规则后重跑（作业 78），第 2 步的用户原话「他」被保留，
  产出的原子命令直接瞄准上一步那个苹果实例（`approach/pick` 的 `target = 7`），说明这条链路真的按 focus
  实例 id 绑定，而不是重新按名字挑一个。`他/她` 与 `它` 同判（用户原话写的就是「再把他拿出来」），
  `(?<!其)` 把「其他/其它」挡在外面，「把其他的香蕉改成绿色」不会被当成指代词。回归见
  `brain_tests/test_same_turn_understanding.py::test_the_pronoun_a_split_leaves_alone_binds_the_object_that_split_added`。
  但**同一类里有两个实例时这条链以前是断的**（作业 83–89 逐层取证，模型侧与 Python 侧各有一处要修）：
  ① `[dialogue_ref=…]` 的说明文字只在 `task_understanding_v2.txt` 第 108-109 行写过，而真正生效的
  `models/prompts.py:126` 加载的是 `task_understanding_clean_v3.txt`——v3 从没接过这条规则，模型把方括号
  当成噪声，于是「两个香蕉（8 和 17），您指哪个？」是**模型自己**发的澄清（作业 83）。规则已补回 v3。
  ② 补回后模型确实写了 `dialogue_ref=true`，却把 `semantic_name`/`tags` 这两个键**从整条响应里省掉了**
  （`…/6085dad2e37c4ed2b1d2c814a20573f4/debug/raw_model_response.txt`：`banana_ref` 和 `basket` 都只有
  `{entity_id, category, dialogue_ref}`）。而 `grounding/semantic_entity_selector.py::bind` 要求 Python 给的
  id 落在**该实体自己搜出的候选池**里——无描述实体的候选池是空集，正确的绑定反被 `grounding_binding_invalid`
  拒掉（作业 84，traceback 同目录）。现在 `bind` 对「既无 semantic_name 又无 tags/aliases/color、
  也不是 category_only」的实体直接信任对话绑定（仍校验 id 在场景里、且不与 `exclude_scene_object_ids` 冲突），
  有自描述的实体保留原来的子集校验，因为那条正是抓「绑定漂到别的物体上」的。回归见
  `brain_tests/test_scene_edit_selection_counts.py::test_a_pronoun_with_no_description_trusts_the_previous_turn_binding`。
  ③ 修掉 ② 之后失败点跳到同一发响应里的**参照物**：`grounding_missing: tray`——作业 85（`1a9b46a07f554a8bbc6f3c6f7151f4ec`）、
  86（`5ad073713614474a9cb5561155ecb544`）、87（`f146324d4bde46e6a9b31d5b0c176441`）三发的 `apple`/`tray` 两个实体
  全都是省名形状，指代那半句被 ② 兜住了，「托盘」这半句没人兜。中间试过两轮文案：第一版写「标记里没有的名字不要
  自己补」，被模型推广到全句（连托盘也留空名）；收紧成「只有被标记指代的那个 entity 走这套，其余实体照常填
  `semantic_name` 与 `tags`，一个都不许留空」之后仍然不稳。**prompt 改两轮都不稳，所以名字这一环改由 Python 兜**：
  `models/task_understanding.py::TaskParseWireOutput.to_task_intent`
  建实体时 `payload["semantic_name"] = payload.get("semantic_name") or payload["entity_id"]`——`entity_id` 是
  schema 里必填且按对象名起的 snake_case 短名，拿它当名字比丢对象好；`entity_id` 是 `target` 这类角色词时仍然
  匹配不到，退回原有的歧义路径，不会假绑定。**注意这个类**：`parse_qwen_turn` 对 v3.1 走的是
  `TaskParseWireOutput`／`_parse_robot_task_wire`，同文件里 `TaskParseOutput.to_task_intent`（第 307 行起）只服务
  legacy replay 与直接调用，改在它上面等于没改——作业 87 之后第一次修复就是这样落空的。离线重放作业 87 那份
  省名答复可以看见差别：`parse_qwen_turn(u, "把他拿出来放到托盘左边 [dialogue_ref=apple]")` 改前两个实体的
  `semantic_name` 都是空串，改后是 `apple`／`tray`。
  ④ 三层修完后的实测形状（作业 89 第 2 步 `5dadf777ca914714bd7032fab88c9d71`）：模型终于把
  `semantic_name="banana"`、`tags=["香蕉"]`、`dialogue_ref=true` 一起给全，`basket` 也不再省名；这一发场景里有
  两个香蕉，而计划里 `approach`/`pick` 的 `target = 19` **正是上一步「新增一个香蕉」刚造出来的那个实例**，
  即跨步指代已由对话状态绑到实例编号，不再靠模型猜名字。同轮第 2 步停在控制端
  `GRASP_DEPTH_SEARCH_FAILED`——撞的是新香蕉所在**桌面中心位**的抓取走廊（`robotiq_2f85_right_coupler` × Tray，
  见下文五步句表格作业 89 一行与其后的「出口 3」），语义侧无残留问题。
* 前端无需改代码就能读到 `metrics` 与 `reply`（Gateway 原样透传）。`artifacts` 按名字合并，同名以
  后一步为准：多个臂步骤会共用 `commands`、`scene_patch` 这些名字，所以终态产物是**最后一步**的那份，
  逐步的 `request_id` 仍完整留在 `metrics.steps[]` 里取证。
* `metrics.steps[].commits` 只统计 `status == "committed"` 的回执：Gateway 给出的 `rejected` 回执
  意味着「什么都没落地」，不能算成这一步写了一次场景。

* 分步轮的收尾会把会话 checkpoint 落盘（`session/store.py::SessionStore.save`），落盘前要验证
  「写下去的文档读回来还是同一份状态」。这道门禁原本比较两份 `model_dump(mode="json")`，而
  `dispatched_requests` 是 `set`：同一套 id，增量 `add` 出来的哈希表和从写好的 list 重建出来的表
  迭代顺序不同，于是 dumps 不等、模型相等 —— 分步轮第二步之后集里有了两个以上 id，就会被判成
  `session_state_readback_mismatch: dispatched_requests`，临时文件不 `os.replace`、整份结果被
  「会话保存失败，现场状态需要人工确认」顶掉，逐步 verdict 全部丢失（作业 75）。现在改成比较模型本身、
  点名差异字段时对 set 排序；回归测试 `brain_tests/test_session_store.py::test_a_rebuilt_set_is_not_reported_as_a_lost_checkpoint`
  用 40 次 add + 36 次 discard + 3 次 add 复刻这张表，改回旧写法即失败。

联调证据（scene 3 `ur5_table_sorting`，本地 Qwen，2026-11-12）：

| 句子 | 结果 |
|---|---|
| 缩放 + 改色 + 数数 | 拆分出 3 步；第 1 步 `provider_output_schema_invalid`（模型给 `scale_mode` 却不给 `scale_xyz`/`scale_amount`，**与拆分无关，同一句单独发也一样失败**）→ 第 1 步 stopped、后两步 not_run、0 次写。 |
| 改色 + 左移 10cm + 数数 | 第 1 步 committed（v10→v11）；第 2 步 `scene_edit_transform_collision` → stopped；第 3 步 not_run。 |
| 改色 + 改色 + 数数 | 3 步全部 completed，一个租约内两次 committed（v11→v13），终态 `scene_updated`，回复逐条列出 ①②③。 |

五步句「把苹果放到篮子里，再把他拿出来放到桌子左边，再新增一个香蕉，把它放到篮子里，把所有香蕉改成绿色」
（scene 3 出厂几何，作业 69–89）：

| 世界 | 结果 |
|---|---|
| 篮子槽位换成浅盘资产 | 拆 5 步；第 1 步 committed（v39→v40），第 2 步 `approach/pick/lift_up/retreat/move_to` 五条全部成功、第 6 条 `approach` 报 `PLACEMENT_REGION_UNOBSERVED` —— **从容器里取出并抬起是通的**，卡死的只有桌面侧向落点。（作业 71） |
| 篮子被整体缩放 / 下沉进桌面 | 缩放连编译都进不去：`This scene compiler currently requires world-parented objects with unit scale`（控制端 `execution/resources.py:115`）；把筐体下沉到台面则在第 1 步 `put` 报 `TARGET_POSE_COLLISION`，接触对 Apple × WorkTable 距离 0.0/2.7mm。用位姿/缩放「造」一个浅筐是死路。（作业 70、72） |
| 出厂真篮子（21.75cm 深筐，v43） | 拆 5 步；第 1 步「把苹果放到篮子里」第 2 次尝试 committed（v43→v44）——深筐的**放入**是通的；第 2 步在计划阶段被拒（见上一节 `atomic_placement_side_off_surface`），后 3 步 not_run。（作业 73） |
| 同一句，v45 出厂几何 | 全程 19.8s：第 1 步 committed（v45→v46），第 2 步直接以 `atomic_placement_side_off_surface` 停在计划阶段，`failure_reason` 带着「请把落点换成桌面上的某个物体／去掉方位」这句可执行建议；改动前同一步要跑约 4 分钟才以 `PLACEMENT_REGION_UNOBSERVED` 收场。（作业 74） |
| 「把苹果放到篮子里，再把它拿出来放到托盘里」（把方位换成合法落点，单独验证深筐取出） | 第 1 步第 2 次尝试 committed；第 2 步三次尝试都停在 `pick` 的 grasp 阶段：`GRASP_NOT_CONFIRMED`、`closure_completed=true` 而 `measured_width_m = 1.7e-05`、两侧接触力 0 —— **夹爪在半空合上了，指尖根本够不到筐底的苹果**（2F-85 的指长在筐沿下只有几厘米，`models/12/basket.obj` 高 21.75cm）。同一个动作在 7.5cm 的托盘上（作业 71）approach/pick/lift_up/retreat/move_to 五条全成功。深筐的「放进去」通、 「拿出来」不通。（作业 75；该轮收尾又被上面那道 checkpoint 门禁顶掉，所以回复只剩「会话保存失败」） |
| 同一句，修掉 checkpoint 门禁后重跑 | 18.0s，第 1 步 committed（v49→v50），第 2 步用满 5 次尝试后停在 `GRASP_DEPTH_SEARCH_FAILED`，回复如实写出「共 2 步，已完成 1 步：①…（已执行并写回场景）。第 2 步「…」未完成…」——上面那道门禁不再顶掉逐步 verdict。失败码从 `GRASP_NOT_CONFIRMED` 变成 `GRASP_DEPTH_SEARCH_FAILED` 是同一件事的另一面：`16 档抓深均不可行：目标位姿间距不足或碰撞 64 次；桌面底限兜底失败 8 次`，即控制端把 30mm→0mm 的抓深全试完，每一档都撞筐壁。（作业 76） |
| 把「篮子」换成 7.5cm 的托盘、「桌子左边」换成「托盘左边」，其余照原句 | 拆 5 步：①把苹果放到托盘里 committed；②再把他拿出来放到托盘左边 第 3 次尝试 committed——**四方位写到容器上是实测通的**；③新增一个香蕉 committed；④停在「两个香蕉（对象编号 8 和 16）」的澄清；⑤ not_run。第 ④ 步是拆分层的指代词被换成对象名导致的，见下一节。（作业 77） |
| 同一句，改掉拆分层替换规则后重跑 | ①committed（v55→v56），且第 ② 步的计划里 `approach/pick` 的 `target = 7`——就是上一步那个苹果的实例编号，说明「他」真的按 focus 实例绑上了；第 ② 步用满 5 次尝试：`pick` 本身确认成功（两侧接触力 6.9N、`reason = stable_bilateral_grasp`），抬出托盘、home 过渡也都成功，滑脱发生在第 6 条 `approach`（带着苹果下探托盘），终态 `GRASP_FAILED`「command 结束后，持物未保持双侧指垫接触」，其中一次是 `PLACEMENT_HEIGHT_SEARCH_FAILED`；③④⑤ not_run。同一条动作在作业 77 里第 3 次尝试成功，所以这一步是物理裕量不足的重试型抖动，不是够不着。（作业 78） |
| 同一句，第三次重跑（抖动复核） | ①committed（v57→v58）；②三次尝试撞了三种墙：前两次 approach/pick/lift_up/retreat/move_to 全过、第 6 条 `approach` 报 `PLACEMENT_HEIGHT_SEARCH_FAILED`，理由是 `wrist_1/2_link` 与 **Basket** 相距 1.4–1.6mm——「托盘左边」算出来的落点正好紧贴旁边那个 21.75cm 深筐的外壁；第三次在 `retreat` 报 `PATH_CONSTRAINT_INFEASIBLE`「Apple 与 Tray 穿透 0.324 mm」，即这一发的物理把苹果推进了筐壁，笛卡尔退让连起步状态都不接受。当时 `PATH_CONSTRAINT_INFEASIBLE` 不在重试集里，链路在第 3 发就断了（回复如实写「重试 2 次后仍未成功」）。这条证据把该码补进重试集：它拒的是本发物理造出的状态，同一条命令在相邻两次尝试里过得去。 |
| 同类两实例的跨步指代（作业 83→84→85→86→87） | 同一句逐层取证，语义侧三层各修一次：83 由**模型自己**发澄清（v3 prompt 没接 `[dialogue_ref=…]` 规则）；84 `grounding_binding_invalid`（对话绑定被无描述实体的空候选池比掉）；85/86/87 `grounding_missing: tray`（模型把整条响应的 `semantic_name`/`tags` 两个键都省掉，参照物搜不到）。逐层修法见上一节。 |
| 指代链修完后重跑同一句（作业 88） | ①「把苹果放到篮子里」1 次即 committed 并写回；②「把他拿出来放到托盘左边」5 发尝试：4 发的 `approach/pick/lift_up/retreat/move_to` **全过**——深筐这一次取得出来，卡在第 6 条 `approach`（带物下探托盘左侧落点）报 `PLACEMENT_HEIGHT_SEARCH_FAILED`「碰撞 132 次」，第 5 发停在 `pick`；③④⑤ not_run。**取得出来的原因写在第 ① 步的提交回执里**：写回后苹果停在 z=0.6551，而筐体原点 0.600036，即只落在筐口上方约 5.5cm 而非筐底，抓深裕量因此落进 16 档以内。所以「深筐取不出」（作业 75/76）真正卡的是**物体静止高度**，不是筐的标称深度；写回位姿乐观一分，取出就通一分。 |
| 只跑后三步（作业 89：「再新增一个香蕉，把它放到篮子里，把所有香蕉改成绿色」） | ①committed（新香蕉拿到实例编号 19）；②`target = 19`——就是上一步刚造出来的那个实例，两个香蕉（8 和 19）在场时没有澄清、没有绑错，**语义侧这条链已彻底闭合**；执行停在 5 发 `GRASP_DEPTH_SEARCH_FAILED`（16 档抓深全撞，256 次碰撞）；③not_run。 |

* 想「换个资产」来绕开几何限制在大脑侧走不通：`ur5_table_sorting` 的平台清单覆盖 id 12，改它的
  `MetadataRef` 会让 `validate_scene` 判部署与模板不一致，提交 422 `web_platform_profile_unsupported`，
  而 `POST /sessions` 走同一条校验——连开新会话都被挡。带外修复只剩浏览器中继 `POST /updateWorld`
  （它只过网关，不过大脑门禁，v39/v43 就是靠它写回的）。位姿与 Semantic 名字不在比较范围内，所以
  「挪动出厂物体」合法、「换资产」不合法。

* 「桌子左边」已经不再是需要换世界的死路（见下文「侧向落点在支撑面上」一条，改成了携带+`release` 展开），
  第 2 步剩下的硬约束只有取出深筐那一件，它是对着只读的控制端代码逐条核过的能力下限：

  * 「桌子左边的落点」用 `put` 表达不了——`put` 的落点由 `demo/interaction/relative_placement.py:30-48` 从**落点物体自己的包围盒**
    往外投影（`reference` 恒为 `target_boundary`），`region_points` 还额外要求候选点在这道边界外侧，所以
    台面的侧向落点必然在桌面以外。想改用姿态目标绕开也不行：`demo/task_commands/converter.py:143-155`
    硬性要求 `put.target` 是场景物体 id，named target 与 pose target 一律 `CommandConversionError`；
    局部锚点那条 `spatial.anchors` 分支只在 `move_to` 上开放（`converter.py:236`），且本地 42 个模型无一个
    声明 `spatial`。四个方位与八个方位无关，四方言同样落在盒外。
  * 「从深筐里拿出来」——指尖能伸多深是写死的：夹爪 TCP 在法兰下 `0.1558m`（`utils/simulation_runtime.py:93`），
    抓取中心在 `robotiq_2f85_base` 下 `0.145m`（`demo/scene/assembler.py:227`），抓深搜索 `GRASP_DEPTHS_M`
    只有 30mm→0mm、2mm 一档共 16 档（`demo/interaction/grasp_depth_search.py:7`），合计约 18.6cm，够不到
    21.75cm 深的筐底；`_DOWNWARD_GRASP_ROTATION` 把进给方向锁成竖直向下（`demo/interaction/vlm_grasp.py:26,411`），
    VLM 通路又把每个候选都记成 `grasp_index 0`（`vlm_grasp.py:442`），所以苹果模型里那 3 条抓取姿态（含一条侧抓）
    也调不出来。控制端还有 `TABLE_FLOOR_OFFSET_M=.017` 的桌面底限兜底（`demo/interaction/table_clearance.py:6`）
    主动阻止往下探。
    但这条地板量的是**物体静止高度**而不是筐的标称深度：作业 88 第 ① 步把苹果提交进同一个 21.75cm 筐后，
    写回的苹果原点 z=0.6551、筐体原点 0.600036，即只落在筐口上方 5.5cm，于是第 ② 步 5 发里有 4 发的
    approach/pick/lift_up/retreat/move_to 全过。换句话说「放进去」那一步写回的位姿乐观一分，「取出来」就通一分——
    作业 75/76 卡在筐底、作业 88 卡在落点，同一句话的两种死法都来自这个乐观写回。
  * 「新增一个香蕉」的默认落点是**桌面几何中心**，而中心位正好是这台 UR5e 的俯视抓取走廊最差的地方：
    作业 89 新香蕉拿到 (0.006, 0.002)，第 2 步第 1 条 `approach` 就报 `GRASP_DEPTH_SEARCH_FAILED`，逐档细节是
    `robotiq_2f85_right_coupler` × **Tray** 距离为负——16 档抓深全撞，共 256 次碰撞。出厂那一排
    （y≈-0.185，苹果/香蕉/螺丝刀/魔方都在这条带上）没这个问题：带上的苹果 (0.18, -0.185) 在第 ① 步每轮都抓得起，
    而基座在 y=-0.55，靠近基座这一侧才是手腕张得开的带。
    排序在 `scene/scene_layout.py::surface_candidates`：`(.5,.5)` 中心位永远第一个被试，而编辑器的准入只有
    **占位/支撑/穿模**三条，没有「以后抓不抓得到」这一条，所以中心位一过就收。要改就得给大脑装一个抓取可达判据
    （控制端才有那套碰撞器），或者把默认带挪到出厂那一排——后者是**放置策略**变更，会改掉每一句「新增一个 X」
    的落点，留给使用方决定，代码没动。
  * 「从浅容器里取出来再放到它旁边」这一发**能不能握住**是抖的：换成 7.5cm 托盘只拆掉了够不着那道地板，
    没拆掉抓取裕量。作业 77–80 在这条句子的第 ② 步上共 16 次尝试（3+5+3+5），只有 1 次真的落进场景
    （作业 77 第 3 发）。逐发取证（作业 80 的 5 发全看过）：4 发是握著握著掉——`pick` 当场是确认过的
    （两侧 6.9N、`stable_bilateral_grasp`），掉物发生在第 3 条 `lift_up`（1 发）或第 5 条 `move_to(home)`（3 发），
    届时指幅 0.064–0.065m 全开、`object_present=false`、`slip_detected=true`；1 发 `PLACEMENT_HEIGHT_SEARCH_FAILED`
    是手腕与**篮子**外壳差 1.4–1.6mm——「托盘左边」的落点算在托盘左沿外 10cm，正好落进旁边深筐的走廊；
    作业 79 还有一发 `PATH_CONSTRAINT_INFEASIBLE`，是本发物理把苹果压进筐壁 0.324mm 后笛卡尔退连起步状态都不接受。
    三类都在「没写回任何世界」的前提下重采样（所以都进了重试集），但大脑改不了指长、摩擦与相邻资产的位置。
    两个能由大脑调的旋钮都用离线对照量过了，**都不是杠杆**（同一份场景文档重投 `SubprocessExecutionAdapter`，
    每发都从头重建仿真，所以逐发可比）：
    * `put.distance_m` 侧向偏移 0.100m vs 0.050m：0.100 那发跑到第 5 条命令才拒在 `PLACEMENT_HEIGHT_SEARCH_FAILED`，
      0.050 那发更早死在 `pick` 后的 `GRASP_FAILED`——把落点往回挪并没有换来更高的成功率，只是换了个失败位置。
    * 携带计划里那句 `move_to(home)`（有它 8 条命令、没它 7 条）：`distance_m=0.1` 下**含 home 与去 home 各 5 发，
      两侧 0/5 落地**，9 发在 `GRASP_FAILED`、1 发在 `PLACEMENT_HEIGHT_SEARCH_FAILED`。当时差异是零，而 home 又是
      控制端 `skill.md` 参考序列里写着的，就没动携带形状。
      **2026-11-12 上游 `414195b` 把这条参考序列自己删掉了**——`skill.md` §3 示例、§4 抓放图和
      `commands.003/005` 都不再带 home，并新增「抓取后默认直接接近目的地，非必要不插入 `move_to(home)`」。
      于是大脑跟着改成 7 条：`atomic_planner` 不再自动插，`skill_planning_atomic_v1.txt` 规则 4 写明只有任务
      明确要求回原位或中转姿态才写 `home`（校验器两种都接受）。顺带一条证据：那 4 发掉物里有 3 发正是掉在
      home 那一发上，去掉它就少一段带物的长距离移动。

  这一句要一轮跑满五步，剩下的口子按「谁改」分四条，逐条都带实测：

  1. **换世界**（历史上第一条，如今已不是必需）：把「桌子左边」换成一个桌面上的合法落点，例如
     「把苹果放到篮子里，再把他拿出来放到**托盘**左边，…」。同一句在作业 77 的第 ② 步第 3 发真的 committed 过；
     现在「桌子左边」由大脑展开成携带+`release`，不必再改句子（作业 90 起）。
  2. **换世界**（第二条，独立于第 1 条）：把 21.75cm 的深筐槽位换成 7.5cm 浅容器，或把落点算出来的那条走廊
     （紧贴深筐外壁）让开——作业 79/88 的 `PLACEMENT_HEIGHT_SEARCH_FAILED` 都是手腕 × Basket 差 1.4–1.6mm。
  3. **改大脑**（唯一还没动的一条，属放置策略）：`surface_candidates` 的默认带从桌面几何中心挪到出厂那一排
     （y≈-0.185）。改完之后「新增一个香蕉」不再落在 Tray 的抓取走廊里，作业 89 那种第 2 步开局即 `GRASP_DEPTH_SEARCH_FAILED`
     会消失；代价是每一句「新增一个 X」的落点都会变，需要一并回归 `brain_tests/test_scene_default_grid.py`。
  4. **改控制端**：给 `put` 加「面内方位」（落点算在支撑面**之内**而不是包围盒之外），或给深容器开侧抓通路。
     「桌子左边」这一句除此之外无解——`relative_placement.py` 的投影方向是写死的。

  大脑这边已经做完的是别让人空等：落点在计划阶段就拒、取放在 5 次尝试后如实报哪一步没成。

### 会话身份与陈旧会话

* `commitWorld` 的 `X-Brain-Session` 必须等于 Gateway 在 `acquireSceneLease` 时记下的那个会话；会话号由
  浏览器向**网关** `/sessions` 申请、网关再转发给大脑。脚本若自己造一个只在大脑存在的 sessionID，
  租约会照样授予，但每次提交都会被 `scene_lease_required` 拒绝。
* 大脑的 `validate_scene` 在会话已有世界时，按 `editor_scene_manifests` 声明的 id 逐个比对部署是否变化
  （只排除 `now_joint_positions_rad`）。`ur5_table_sorting` 的清单覆盖全部 15 个对象，所以**别的会话把
  版本推过之后**，这个旧会话再次上线会直接 422 `web_platform_profile_unsupported`——面板上表现为
  「能力不支持」，解法是点「新会话」让大脑以当前世界重新初始化，而不是修场景。

### 相机

`GET /captureScene?id=5&type=rgbd&browser_id=...`：
`{browserID,scene_id,scene_version,scene_sub_version,sceneDigest,playback_state:"stopped",width,height,
image_encoding:"png",image_base64,depth_encoding:"float32le",depth_base64}`。
RGB 请求可不返回深度；rgbd 深度是 width*height 个小端 float32。
PNG 必须真实完整图像；相机配置尺寸需匹配，不能替换为占位图片。

`GET /get2DAABB?id=OBJECT_ID&camera_id=5&browser_id=...` 返回相同身份/尺寸字段及
`visible`、`box:{x_min,y_min,x_max,y_max}` 像素框。不可见用 visible=false，不编造框。
采集期间锁定场景；capture、所有 AABB、前后 getWorld 必须对应同一现场。
旧缓存、错误浏览器、播放中、尺寸错误、无效 PNG 均拒绝。
segmentation 未实现，明确拒绝；视觉只在现有语义绑定无法消歧时调用。

## 协议兼容和数据边界

- 空 MeshRenderer 保留 `{}`，回退资产颜色；真实 #FFFFFF 仍是白色覆盖。
- now_joint_positions_rad 验证关节名/有限值；静态 profile 比较排除 now，其他配置严格保留。
- available_connect_joints 按离线 URDF 清单校验，固定关节可不在驱动序列。
- 七场景原字段往返、未知组件显式引用规则不变。uint32 只在联调配置启用；旧 CLI 不静默重编号。
- 各原始场景的光源 ID 不同，平台清单见 editor_scene_manifests；不能误把苹果 ID7 冻结为平台。
- 新导入的配置工作台允许无参照增物；仅在 MetadataRef、世界变换与配置模板一致时使用默认工作区。
  任意上传场景不套默认桌面范围。
- 操作技能只有控制端已实现的八个：抓、放、抬、撤、平移与 `pull`/`push` 直线推拉。
  「打开抽屉」这类 open/close 现在能展开成 approach→pick→pull→retreat，但前提是那个资产
  自己标了把手抓取点；微波炉加热、旋拧、倒水仍不支持，新增资源不能据此推断出能力。
  `put` 只认四个水平外侧方向，`above`/`below` 悬空放置是 skill.md 里先写、控制端还没做的部分。
* **侧向落点在支撑面上**的请求（「放到桌子左边」）现在在计划阶段展开成携带+松手，不再是一条 `put`，
  判据与展开都在 `planning/atomic_plan_validator.py`（`SURFACE_CATEGORIES` 命中且任务给了四侧之一时
  走 `_surface_carry`）。原因是控制端把 `put` 的侧向区域算成*目的地自身包围盒*沿基座水平方向的边界再向外
  `distance_m`（`demo/interaction/relative_placement.py::relative_region`，`reference` 恒为
  `target_boundary`）：筐/盘的盒子是筐壁，向外那段仍落在沿内，所以写到容器上是成立的——「托盘左边」实测
  committed（作业 77 第 ② 步，第 3 次尝试）。桌面的盒子却是整个工作区
  （`$LIBRARY_SERVER/29` 的 AABB x±0.75、y±0.375、z 0→0.6），向外 10cm 落到桌沿以外、高度还停在桌腿中段，
  RGB-D 里没有这块区域，真跑要几分钟才以 `PLACEMENT_REGION_UNOBSERVED` 收场——所以这条 `put` 仍然不能下发。
  能落在这块桌面的方言形状是**带物体平移再原地松手**：`move_to(target="end_effector", relation, distance_m)`
  从该条命令实测到的 TCP 位姿做笛卡尔平移并保住抓取（`converter.py:500-515`，方向取自机器人自身的
  `end_effector_rotation`，本场景 q=[0,0,0.7071,0.7071] ⇒ 左=世界 −X、右=+X、前=+Y、后=−Y，与大脑
  `left_half` 的 x<mid 约定一致），`release{target}` 只解绑+张爪+settle，不动、也不查支撑
  （`atomic_skill/release.py`、`runner.py:461-492`）。两个数都不问世界要尺寸：先上抬
  `SURFACE_CARRY_LIFT_M=0.08` 越过取出来源那只筐的筐沿，再平移既有的 `PLACEMENT_EDGE_OFFSET_M=0.1`，
  松手，最后退 `SURFACE_CARRY_RETRACT_M=0.10`；展开后 `command_id` 统一重发成 1..N。
  离线实测（`/tmp/inplane_probe.py`，出厂场景重投 `SubprocessExecutionAdapter`）：苹果从 (0.180,−0.185)
  被握著平移 0.25m 到 (−0.075,−0.185)，第 4 条 `move_to` success、x 位移与请求一致——**面内携带是真跑得通的**；
  随后固定 0.02m 的下探把苹果压进桌面 0.659mm（`COLLISION_DETECTED`），所以这版展开**不下探**，让物体从
  抬升高度自己 settle。回归见 `brain_tests/test_atomic_plan_validator.py::test_a_side_onto_the_work_table_becomes_a_carry_and_a_release`。
* 这类「任务本身没要求的落点」的码刻意不带 `atomic_plan_` 前缀：`models/qwen_http.py::plan_atomic`
  把该前缀（连同 `ATOMIC_OUTPUT_CODES`）当作「把违规句回给模型重投一次」的信号，而象限/侧向支撑面这类
  拒绝重投多少次都不会出现落点。作业 73 第 2 步正是踩在这条规则上——回炉的那一轮模型回了个空
  `commands: []`，于是 `AtomicCommandDraft` 的 min_length 先炸，终态显示的是
  `skill_plan_output_invalid` 加一句「List should have at least 1 item」，真正的原因被盖掉了。
* 失败回复带上控制端自己拼的那句中文证据，而不只是一个枚举码：`web/service.py::composite_result` 停在失败
  步时写「第 N 步「…」未完成：16 档抓深均不可行：目标位姿间距不足或碰撞 64 次（GRASP_DEPTH_SEARCH_FAILED），
  重试 4 次后仍未成功，未执行。」，单步的 `dispatch` 回复同规则。此前两处都只印 `error.code`，中文证据句
  只在 `failure_reason` 里——面板读的是 `reply`，所以作业 76 那种「抓深用尽」和「碰撞挡路」在看的人眼里是
  同一个码。回归见 `brain_tests/test_composite_orchestrator.py::test_a_grasp_that_never_contacts_stops_after_the_attempts_are_spent`。
  证据句本身已由 `error_messages` 拼成「中文句（CODE）」，所以拼句走 `web/service.py::failure_detail`：
  码已经出现在句子里就不再重复，否则面板会读出「…（GRASP_FAILED）（GRASP_FAILED）」（作业 78 第 ② 步原样踩过），
  回归见同文件的 `test_an_evidence_sentence_that_already_names_its_code_is_not_repeated`。

## 产物与前端协作验收

默认 `var/webeditor/tasks/`：

```text
agent_tasks.sqlite3                  # taskID、幂等、绑定、结果
<sessionID>/original_scene.json      # 首次编辑前冻结，只读原件
<sessionID>/<request_id>/
  scene_config.json / scene_patch.json / commands.json / query_result.json
  request_record.json / result.json / debug/model_calls.json
<sessionID>/gateway_transactions/    # prepared/committed/unknown 回执、相机绑定、真实采集记录
```

不保证每类任务都有每种文件：颜色/缩放/查询不生成 commands；失败不生成伪命令。
下载白名单是 scene_config、scene_patch、commands、query_result；debug/服务器路径不公开下载。

前端交付清单：

1. 透传稳定 sessionID/clientRequestID/browserID 和完整场景摘要；重复点击复用幂等键。
2. 新建/恢复/显式切换绑定 UI，第二浏览器不能抢写；任务期间禁用编辑和轨迹。
3. 结果查询和展示回答/澄清/计划/技能顺序/Qwen 调用/下载；不显示机械臂执行成功。
4. 手工增删拖动颜色关节均增版本；共用持久 ID 高水位。
5. 新 commitWorld 全量原子验证、CAS、持久事务回执；拒绝广播写入/部分应用。
6. 实时 getWorld 身份头、真实 capture/AABB 身份字段；runtimeConfig 端口与监听一致。
7. 完成后联合验收：增物→改蓝→查询→缩放/拒绝→网页拖动/删除续聊→连续两次 original→
   真实 Qwen commands v2→真实浏览器视觉消歧。替身测试不替代这一步。

执行 `pytest -ra brain_tests`、独立 wheel smoke；CI 配置覆盖 Python3.11/3.12 并安装 web extra。
外部资源缺失的集成测试必须显示 skip，不算资产验收通过。不自动提交或推送。
