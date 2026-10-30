# 批量多会话测试

批量测试文件只需要描述 session、首轮场景和按顺序执行的指令：

```json
{
  "sessions": [
    {"name": "empty", "scene": null, "instructions": ["增加一个苹果", "有几个苹果"]},
    {"name": "sorting", "scene": "../../webeditor_runtime/ObjectLibraryServer-1.0.5-rel/data/scenes/3/ur5e_table_sorting.json", "instructions": ["有几个苹果"]}
  ]
}
```

`scene: null` 表示测试通道会在该 session 开始时向活动浏览器提交合法空场景；路径相对于批量文件解析。每个
session 只在第一轮加载场景，后续指令复用同一会话和当前世界。session ID、task ID、
幂等键、场景摘要、截图元数据和断言均由批处理器生成。

## 服务模式

服务模式通过真实 AgentService 和 WebEditor Gateway 执行，要求 Qwen、OLS、Brain、
Gateway 和一个已绑定浏览器都已启动：

```bash
robot-brain batch \
  --cases examples/batch_sessions.json \
  --transport service \
  --agent-url http://127.0.0.1:8500 \
  --gateway-url http://127.0.0.1:8099 \
  --output-dir var/batch-runs
```

只有一个活动浏览器时会自动使用它；多个浏览器时增加 `--browser-id`。每轮完成后
读取 Gateway 当前 Scene，并调用绑定相机的 `captureScene` 保存 PNG。浏览器断开、
摘要过期、相机不可用或截图校验失败会标记为 `blocked`，不会使用旧图片冒充当前现场。

## 输出

每次运行生成 `var/batch-runs/batch-*/`，其中包含 `summary.json`、`summary.md`，以及
每个 session 的 `session.json`、`original_scene.json`、`session_summary.json` 和
`turns/0001/`、`turns/0002/` 等目录。批处理器会先通过 `/sessions` 激活目标 session，
再把首轮场景写入浏览器，避免加载下一个 session 时覆盖上一个 session 的快照。每轮目录保存 instruction、
task result、系统回复、Scene JSON、四元组身份、截图和截图元数据；Brain 产出的
Commands、scene patch、查询结果也会下载到该轮的 `artifacts/` 目录（如果有）。

截图元数据会校验浏览器返回的 camera id、场景四元组、digest、PNG 编码和尺寸；校验失败
会记录为 `blocked`，绝不会把旧图片当作当前场景。即使某一轮失败导致后续轮次跳过，
跳过轮也会保存场景和截图证据（若浏览器仍可访问）。

机器人任务只检查规划结果，`executed` 必须为 `false`；本通道不调用 Control、IK、
MuJoCo 或真实轨迹执行器。

## 兼容旧 JSONL

旧的 `robot-brain batch --cases cases.jsonl` 仍然可用。旧格式每行一个 case，按
`session_group` 共享会话；新的服务模式使用上面的 `sessions` JSON，避免用户填写
task ID 或预期字段。

## 批量测试前置协议检查（brain-web/2）

正式批量矩阵必须在以下前置检查通过后运行：

1. **机器人任务统一为 v3**：实时 Qwen 输出顶层 `entities` 使用
   `entity_id/semantic_name/category`，顶层 `operations` 使用 `operation`。
   旧的 `id/name/type` 只在回放兼容边界归一化，不进入 live JSON Schema。缺少
   必需字段记为 `qwen_json_incomplete`；字段齐全但违反任务约束记为
   `semantic_protocol_error`。
2. **路由按意图而非单个动词**：直接改变场景陈设且没有机器人行为主体使用
   `scene_edit`；明确“机器人/机械臂抓取、搬运、释放、按压、推拉、开关”才使用
   `robot_task`。例如“在桌面上放置篮子、苹果和香蕉”是 scene edit，
   “把苹果放进篮子”才是 robot task；行为主体不清时必须澄清。
3. **环境引用统一解析**：本轮实体引用、已有场景对象引用和注册环境引用（如
   `table/桌面`）都由 `SceneReferenceResolver` 处理。未知引用不由 Prompt 猜测，
   最终分类为 `scene_reference_unresolved`；不会静默创建桌子。
4. **空场景边界**：`scene_id=0` 且无对象仅允许尚未初始化的 session 用于 Brain
   bootstrap。已有场景的 session 收到该快照必须返回场景身份错误，不能覆盖当前
   场景或原始快照。
5. **错误和证据**：每轮报告同时保存原始模型响应、Pydantic 错误位置、诊断编号和
   场景四元组。报告中区分 `qwen_json_incomplete`、`semantic_protocol_error`、
   `scene_reference_unresolved`、`default_surface_missing` 与
   `geometry/layout_failure`。下层 traceback 只写日志，不直接作为用户回复。

前置验收至少包括：canonical robot task 的 schema/解析、桌面环境引用查询、未知
引用拒绝、空场景首轮三对象新增、已初始化 session 的空场景拒绝，以及同一 session
连续编辑后的 original 快照不变。全部通过后才执行正式的空场景和预设场景批量矩阵。

## 当前正式批量矩阵文件

- `examples/batch_sessions_empty.json`：空场景，L1-L4 每级 10 个 session，共 40 个。
- `examples/batch_sessions_presets.json`：OLS 1.0.5 的 7 个预设场景，每场景每级 3 个
  session，共 84 个；场景路径相对该 JSON 文件解析。

真实联调结果的 Excel 至少包含“用户指令”“真实浏览器场景截图”“系统返回的任务结果”
三列，并保留四元组、错误码、执行状态和证据目录；当前批量报告会同时写入
`var/batch-runs/batch-audit-*/report.md`、`report.json` 和 `batch_test_results.xlsx`。
