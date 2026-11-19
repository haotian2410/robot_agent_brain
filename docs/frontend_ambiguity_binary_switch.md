# 前端对接说明：歧义处理二值开关

本文说明 WebEditor 如何接入 Brain 的歧义处理开关。当前协议字段名为
`prefer_auto_resolve`，它不是“所有歧义都自动选择”的总开关，而是一个安全范围内的二值偏好：

| 值 | 前端含义 |
|---|---|
| `false` | 默认模式。存在多个候选时向用户澄清。 |
| `true` | 安全自动选择模式。仅允许对非破坏性的源对象／操作者候选进行确定性选择。 |

目标协议仍是 `brain-web/2`。前端不需要自行实现候选排序、哈希选择或场景对象绑定；这些由 Brain 完成并写入审计结果。

## 1. 推荐的前端交互

开关文案建议使用：

> 歧义自动选择（仅安全操作）

打开开关时给出提示：

> Brain 只会在安全的源对象选择中自动决定；目标容器、删除/替换、查询集合、明确 ID、缺少颜色证据等情况仍会要求确认。

前端应把开关绑定到“当前会话”，而不是只保存在浏览器 localStorage。页面刷新、切换会话后，以 Brain 返回的会话状态为准。

## 2. 创建或更新会话

### 创建新会话

`POST /sessions`：

```json
{
  "browserID": "browser-abc",
  "camera_id": 5,
  "prefer_auto_resolve": true
}
```

响应示例：

```json
{
  "sessionID": "9a2d...",
  "browserID": "browser-abc",
  "camera_id": 5,
  "camera_selection_reason": "explicit_configuration",
  "session_phase": "setup",
  "active": true
}
```

### 更新已有会话

仍使用 `POST /sessions`，带上会话 ID：

```json
{
  "browserID": "browser-abc",
  "sessionID": "9a2d...",
  "prefer_auto_resolve": false
}
```

服务端会校验浏览器归属、`uncertain/quarantine` 状态和活动任务。前端不能通过切换开关绕过恢复或租约状态。

如果当前会话存在等待用户处理的失败链，改变开关会返回：

```text
failure_chain_policy_change_forbidden
```

此时应提示用户先完成当前澄清，或新建会话；不要自动重试旧任务，也不要把它当作普通网络错误。

## 3. 刷新和会话切换时读取权威状态

页面加载、切换历史会话、创建会话完成后调用：

```http
GET /sessionState?browser_id=browser-abc
```

重点字段：

```json
{
  "sessionID": "9a2d...",
  "session_phase": "setup",
  "lease": false,
  "quarantine": false,
  "scene_id": 1,
  "scene_version": 3,
  "scene_sub_version": 0,
  "sceneDigest": "...64 hex...",
  "prefer_auto_resolve": true
}
```

UI 的开关必须由 `prefer_auto_resolve` 回填。不要依据上一会话的前端状态猜测当前值。

`GET /sessions?browser_id=browser-abc` 返回的会话列表也包含该字段，可用于历史会话列表中的状态展示。

## 4. 提交任务

`POST /startTask` 的请求仍必须携带完整场景四元组、浏览器和会话身份：

```json
{
  "command": "把最左边的苹果放到篮子旁边",
  "scene": {"...": "当前完整 Scene"},
  "scene_id": 1,
  "scene_version": 3,
  "scene_sub_version": 0,
  "sceneDigest": "...64 hex...",
  "sessionID": "9a2d...",
  "clientRequestID": "req-001",
  "browserID": "browser-abc",
  "prefer_auto_resolve": true,
  "new_task": false,
  "change_kind": "scene_edit"
}
```

`prefer_auto_resolve` 在任务请求中用于保留请求审计上下文；实际会话策略以 `/sessions` 持久化的值和 `/sessionState` 返回值为准。前端不要在每轮任务中偷偷改变会话开关。

## 5. 哪些情况会自动选择

`true` 时，Brain 仅可能自动选择：

- 多个同类对象中的非破坏性源对象／操作者；
- 有稳定整数对象 ID；
- 颜色证据不是 `unverifiable_fallback`；
- 不是删除、替换、查询集合或目标容器；
- 不是显式 ID、平台对象或缺少必要参数。

例如“把苹果移到篮子右边”中，如果存在多个苹果，源苹果可以在安全条件下确定性选择；篮子仍需唯一绑定。

以下情况不会因为开关为 `true` 而自动猜测：

- 删除或替换对象；
- 选择篮子、托盘等目标容器；
- “哪个/哪些”查询的候选集合；
- 两个同名容器无法区分；
- 颜色没有可靠证据；
- 缺少参照物、放置关系或必要参数。

## 6. 任务结果和前端展示

前端轮询 `GET /queryTaskState?taskID=...`，直到 `terminal=true`，再读取：

```http
GET /queryTaskResult?taskID=...
```

成功或计划结果中的 `metrics.selection_decisions` 可能包含：

```json
[
  {
    "entity_role": "apple",
    "chosen_ids": [17],
    "candidate_ids": [12, 17],
    "decision_key": "...",
    "policy": "auto",
    "color_evidence_status": "not_applicable",
    "color_verified": null
  }
]
```

建议在任务详情中显示“已自动选择对象 #17（候选 #12、#17）”，但不要把 `decision_key` 当作用户可编辑的绑定依据。

澄清结果应直接显示 `clarification_question`，例如“请说明要操作哪一个苹果”。澄清、拒绝和未知状态都不能显示为成功，也不能生成伪造 Commands。

机器人任务仍遵循现有边界：若有计划，`executed` 必须以实际控制端结果为准；Brain 不因自动选择开关而宣称机器人已执行。

## 7. 恢复和异常状态

二值开关不是恢复接口。遇到以下状态时，前端应停止发送新任务并显示恢复提示：

| 错误码/状态 | 前端处理 |
|---|---|
| `session_reconciliation_required` | 显示“当前会话待恢复”，进入证据核对/`resolveUncertain` 流程。 |
| `failure_chain_policy_change_forbidden` | 不切换开关，先处理当前澄清链或新建会话。 |
| `conversation_recovery_exhausted` | 显示恢复链已耗尽，要求用户发起明确的新任务。 |
| `grounding_ambiguous` | 显示澄清问题；不要重试相同请求期待随机改变。 |
| `provider_output_schema_invalid` | 显示模型输出格式错误，保留诊断编号。 |
| `task_busy` | 当前会话已有任务，等待其 `terminal=true`。 |

只有在证据确认后才允许继续会话。不要把 `new_task=true` 或新建会话当作未知事务的强制解锁。

## 8. 最小前端调用示例

```ts
async function setAmbiguityPolicy(browserID: string, sessionID: string | null, enabled: boolean) {
  const body: Record<string, unknown> = {
    browserID,
    prefer_auto_resolve: enabled,
  };
  if (sessionID) body.sessionID = sessionID;
  const response = await fetch("/sessions", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const payload = await response.json();
  if (!response.ok) throw new Error(payload?.error?.code ?? "session_update_failed");
  return payload;
}

async function refreshAmbiguityPolicy(browserID: string) {
  const response = await fetch(`/sessionState?browser_id=${encodeURIComponent(browserID)}`);
  const payload = await response.json();
  if (!response.ok) throw new Error(payload?.error?.code ?? "session_state_failed");
  return Boolean(payload.prefer_auto_resolve);
}
```

如果 Gateway 对 Brain 做了代理，前端使用 Gateway 的对应路径即可，但必须原样保留 `prefer_auto_resolve`、`clarification_question`、错误码和 `metrics.selection_decisions`。

## 9. 联调验收清单

- [ ] 新会话默认 `prefer_auto_resolve=false`，页面开关显示关闭。
- [ ] 打开开关后重新读取 `/sessionState`，显示为开启。
- [ ] 多候选源对象允许安全自动选择，并在结果中显示选择证据。
- [ ] 多候选目标、删除、替换和查询仍要求澄清。
- [ ] 颜色证据缺失时不自动猜颜色对象。
- [ ] 刷新页面/切换历史会话后开关值不串台。
- [ ] 活动任务、unknown/quarantine 和失败链策略变更得到明确提示。
- [ ] 澄清/拒绝不增加场景版本、不改变 digest、不产生伪造 Commands。
- [ ] 不把自动选择结果等同于机器人执行结果。

## 10. 当前实现边界

该字段已经在 Brain 的会话、任务和结果链路中持久化；它只控制语义候选的安全确定性选择。它不改变资产解析、相机绑定、机器人 profile、Control 执行或场景几何校验规则。前端如需“用户指定某个具体对象”，仍应通过自然语言、稳定对象 ID 或现有绑定协议表达，不能用开关代替明确指代。

