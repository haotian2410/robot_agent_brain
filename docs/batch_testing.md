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
每个 session 的 `turns/0001/`、`turns/0002/` 等目录。每轮目录保存 instruction、
task result、系统回复、Scene JSON、四元组身份、截图和截图元数据；Brain 产出的
Commands、scene patch、查询结果也会下载到该轮的 `artifacts/` 目录（如果有）。

机器人任务只检查规划结果，`executed` 必须为 `false`；本通道不调用 Control、IK、
MuJoCo 或真实轨迹执行器。

## 兼容旧 JSONL

旧的 `robot-brain batch --cases cases.jsonl` 仍然可用。旧格式每行一个 case，按
`session_group` 共享会话；新的服务模式使用上面的 `sessions` JSON，避免用户填写
task ID 或预期字段。
