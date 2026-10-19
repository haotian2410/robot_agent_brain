# WebEditor / Gateway 首期联调（brain-web/1）

本期 Brain 只规划，不连接 Control、不发送轨迹、不执行机器人。
`任务完成` 不等于机械臂执行成功；所有结果固定 `executed=false`。

## 当前交付边界

Brain 已增加协议兼容、持久化 AgentService、严格 Gateway 场景/相机适配器。
提供的 WebEditor 1.0.1 发布包 **尚未实现本协议**。需要前端同事提供源码或新包；
不修改 dist 压缩 JS，不降级到非原子的 `updateWorld`。
真实 Qwen/OLS、测试替身、真实浏览器的验证分别记录在 `demo/webeditor/VALIDATION.md`。

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
unzip -n /home/cscvlab/lht/yzk/ObjectLibraryServer-1.0.4-rel-res-1.0.4-rel.zip -d /home/cscvlab/lht/webeditor_runtime
unzip -n /home/cscvlab/lht/yzk/WebEditor-1.0.1-rel.zip -d /home/cscvlab/lht/webeditor_runtime
```

OLS 读取同一份 data；Brain 不复制模型到 wheel，不覆盖旧 final_models。
`config/webeditor.json` 的资源路径相对配置文件解析，运行产物路径相对启动目录。
模型名是当前 `/v1/models` 返回的服务端 model ID，部署到别的机器可设置
`ROBOT_BRAIN_MODEL`，而不是重启已有 Qwen。

生成派生缓存与完整 URDF 关节清单（只读资源目录）：

```bash
python scripts/validate_final_models.py \
  --root ../webeditor_runtime/ObjectLibraryServer-1.0.4-rel/data \
  --manifest config/ols_1_0_4_manifest.json \
  --cache var/webeditor/geometry_cache.json \
  --joint-cache var/webeditor/joint_inventory.json
```

各用一个终端启动 OLS、Gateway、Brain；先检查端口，已存在的服务不要重复启动：

```bash
ss -ltnp '( sport = :8000 or sport = :8080 or sport = :8099 or sport = :8500 )'
cd /home/cscvlab/lht/webeditor_runtime/ObjectLibraryServer-1.0.4-rel
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

快速返回 `{"taskID":1,"state":"已进入队列","code":0}`；不等待 Qwen。
同会话同 clientRequestID/相同完整请求返回原任务；不同内容 HTTP409。
首期场景串行：另一个未完成请求返回 `task_busy`，客户端等本轮终态后再获取新场景提交。
缺上下文明确 `session_context_required`；不兼容旧 Gateway 隐式续接方式。

| 接口 | 返回 |
|---|---|
| GET /queryTaskState?taskID=1 | taskID/state；已创建、已进入队列、进行中、任务完成、任务失败 |
| GET /queryTaskFailureReason?taskID=1 | taskID/state/failureReason，未失败为 null |
| GET /queryTaskResult?taskID=1 | 未完成 HTTP202；完成 HTTP200，详见下面 |
| GET /tasks/1/artifacts/commands | 只读白名单产物；不允许任意路径 |
| GET /health | service/qwen/browser/assets 分项能力，不用单个 HTTP200 代表全部可用 |

终态 result：`outcome=scene_updated|answered|clarification_required|plan_ready|failed`，
固定 executed=false，reply、scene_id/version/digest、metrics.model_calls、plan（完整 Commands）、
artifacts URL、commitReceipts。机器人任务显示“计划已生成，尚未执行”。澄清显示 reply 问题，
不是错误地显示成功执行。模型校验/几何拒绝等处理错误用任务失败，附原始结构化错误。

服务进程重启不会自动重放任务。中断任务变为 `service_restarted`；执行中的会话标记 uncertain，
必须人工核对浏览器事务/锁后显式建立新绑定；**未提供一键强制清除 unknown 的接口**。
恢复普通空闲会话仅读取 checkpoint，下一轮读 live 现场，不写旧 checkpoint。
同一任务数据库仅允许一个服务进程持有文件锁。

## Gateway 必须新增/扩展的契约

### 能力与现场读取

`GET /brainCapabilities?browser_id=browser-1`：

```json
{"protocol":"brain-web/1","browserID":"browser-1","capabilities":["atomic_commit","versioned_manual_edits","bound_browser","task_edit_lock"]}
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

同一 scene_id 手动编辑必须递增 scene_version。同版本不同内容冲突；删物体不重用 ID；
替换 MetadataRef 用新实例 ID。关节 now 值只是展示，不产生 holding/known 执行证据。
静态机器人、相机/桌子/光源等部署变化要求新会话，不能作为普通编辑悄悄吸收。

### 任务编辑锁

`POST /acquireSceneLease` 输入 `{taskID,browserID,scene_id,scene_version,sceneDigest}`。
Gateway 检查当前绑定和现场三元组，停止/拒绝轨迹播放并锁定所有手工编辑入口，返回
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
  "expected":{"scene_id":1,"scene_version":3,"sceneDigest":"旧摘要"},
  "scene":{"这里替换为完整目标Scene":true}
}
```

浏览器先验证所有对象/引用/资源，再 CAS 一次提交。任何拒绝均不能部分落地。
同 scene_id 目标版本必须旧版+1；original 派生/显式新场景 ID 允许版本1。
**不额外自增**。保留旧 updateWorld 语义，但 Brain 永不调用它。

成功回执：`{transactionID,browserID,status:"committed",scene_id,scene_version,sceneDigest,rejected_objects:[]}`。
`GET /queryWorldCommit?transactionID=...&browser_id=...` 返回持久回执。
同事务同内容只能提交一次；异内容冲突。浏览器刷新后也要能核对事务。
明确拒绝返回 `{transactionID,browserID,status:"rejected",reason:...}`（不修改现场）。
Brain 首期对无法证明成功的结果保守阻塞，宁可人工核对也不盲目重试写入。
POST 超时只查询事务并读 live 比对；不自动重发、不假装回滚。

### 相机

`GET /captureScene?id=5&type=rgbd&browser_id=...`：
`{browserID,scene_id,scene_version,sceneDigest,playback_state:"stopped",width,height,
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
- 无新操作技能。微波炉等新增资源不能据此推断可开门、加热、旋拧或倒水。

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
