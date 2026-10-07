# 手动测试：Brain 原生规划应用

## 环境与模型

在仓库安装 `python -m pip install -e '.[dev]'`。只需要 Python 3.11/3.12、
Pydantic、httpx、jsonschema；不要为了此应用安装 MuJoCo/Control。
本地持久化锁目前针对 Linux/POSIX，不宣称支持分布式文件系统。

Qwen 服务必须由部署端先启动。本仓库不负责模型权重下载或服务启动。
用 `curl --noproxy '*' http://127.0.0.1:8080/v1/models` 确认服务和模型名。
若 Connection refused，先修复服务，不是更换 prompt 或使用 fake。

```bash
export ROBOT_BRAIN_MODEL='服务实际返回的模型名'
export ROBOT_BRAIN_BASE_URL=http://127.0.0.1:8080/v1
robot-brain run '把两个苹果放进篮子' --provider qwen \
  --structured-output json_schema --output-dir var/qwen-manual --json
```

如果代理会截获 localhost，请按自己的部署配置设置 `NO_PROXY=127.0.0.1,localhost`
或在该命令前清除代理变量。服务不支持 JSON Schema 时可以显式选择
`--structured-output off`，返回内容仍必须通过契约校验；不会自动降级。

## 常用参数

| 参数 | 含义与可选值 |
|---|---|
| `--config PATH` | 配置 JSON；资产/defaults/replay 相对路径以配置文件目录为基准 |
| `--scene PATH` | run/chat 可选的 Brain 原生场景；不传则生成或恢复，不能传 MJCF |
| `--assets PATH` | `AssetDocument` JSON；省略使用演示元数据 |
| `--defaults PATH` | 桌面、工作区、布局次数、默认初始数量配置 |
| `--provider qwen/replay` | 默认 qwen；Replay 不是任意自然语言解析器 |
| `--planner recipe/qwen/auto` | 默认 recipe；qwen 仅对机器人任务进行第二次模型调用；auto 只根据 supports 路由 |
| `--planner-max-completion-tokens N` | 默认 1024，范围 128–4096；实际第二次预算 min(N, 384 + 128 × max(展开后操作数, 1)) |
| `--replay-file PATH` | Replay 必填，内容是原始输入和已解析 BrainTurn 列表 |
| `--base-url URL` | 兼容接口根地址，默认 `http://127.0.0.1:8080/v1` |
| `--model NAME` | Qwen 服务的模型 ID，必须配置 |
| `--structured-output json_schema/off` | 默认 json_schema；off 仍校验响应 |
| `--timeout SECONDS` | 正数，默认 120 秒 |
| `--output-dir PATH` | 默认 `var/manual-tests`，持久化会话也位于此目录 |
| `--session ID` | run/chat 恢复同一输出根目录下的会话；只允许安全字母数字、`_`、`-` |
| `--seed INTEGER` | 初始布局随机种子，默认 0 |
| `--json` | run 输出一个 JSON；chat 每轮一行 JSON，提示在 stderr |
| `--debug` | 保存脱敏的本轮原始响应、语义、绑定、技能计划、调用记录及失败 traceback |
| `batch --cases PATH` | JSONL 用例文件，组内共享会话，独立组互不污染 |
| `schemas --output-dir PATH` | 不访问模型；输出公开协议 Schema |

同名配置字段可使用 `ROBOT_BRAIN_` 大写环境变量，例如 `ROBOT_BRAIN_TIMEOUT`。
机器人型号当前通过配置 `robot` 或 `ROBOT_BRAIN_ROBOT` 设置，默认 ur5e；
CLI 不接收旧系统的 `--viewer-mode`、`--interaction-registry`；本版 `--planner` 定义见上表。
`vision` 默认 false。LocalScenePlatform 没有图像；将 `ROBOT_BRAIN_VISION=true`
用于本地 CLI 会明确拒绝，不会给 VLM 传假图片。真实视觉需通过 Python 注入渲染平台。

## 不依赖模型服务的完整回放

以下输入必须保持与夹具一致：

```bash
robot-brain run '把两个苹果放进篮子' --provider replay \
  --replay-file examples/replay/manual.json --session demo01 \
  --output-dir var/demo --json

robot-brain run '有几个苹果' --provider replay \
  --replay-file examples/replay/manual.json --session demo01 \
  --output-dir var/demo --json

robot-brain chat --provider replay --replay-file examples/replay/manual.json \
  --session demo01 --output-dir var/demo
```

首轮应为 `generated`，含两个苹果和一个篮子，输出 commands，但没有真实执行。
第二轮应为 `session`，回答两个苹果，场景版本不变。chat 可以输入 `/status`、
`有几个苹果`、`/exit`。已经导出两份计划不会产生假 pending。

需要新场景时使用新的 session ID，或 chat 的 `/load PATH` 显式替换场景。
真实 pending 时禁止替换。`--scene` 不能隐式覆盖一个已经恢复的会话。

批处理：

```bash
robot-brain batch --cases examples/cases/manual_cases.jsonl \
  --provider replay --replay-file examples/replay/manual.json --output-dir var/batch --json
```

每行包含 `case_id`、`session_group`、`instruction`、可选 `scene` 和 `expected`。
scene 相对路径以 JSONL 文件目录为基准。expected 支持 turn_kind、run_status、
artifacts、absent_artifacts 和报告字段的点分路径 assertions。组内失败后后续默认
skipped，`continue_after_failure=true` 才继续；独立组继续。summary 标记 provider，
不会把回放结果称为真实模型测试。

## 查询与场景连续性专项

Scene Edit 已统一为 SceneEditPlan；自定义 Replay 或模型输出中即便只“增加一个香蕉”，
也需要 entities + relations + operations。名称/数量只放 entities，操作通过 target 引用。
旧的直接 scene_edit.operation/semantic_name/category/count 不再接受，示例见 contracts.md
和 examples/replay/add_apple.json。自然语言 CLI 用法不变。

已存在的同一会话可运行（先按上文配置真实 Qwen 的 model）：

```bash
robot-brain run '红色苹果有几个' --provider qwen --session demo01 --output-dir var/demo --debug
robot-brain chat --provider qwen --session query-continuity --output-dir var/qwen --debug
```

新 chat 中依次输入：

```text
把两个苹果放进篮子
它们有几个？
把它们向右移动五厘米
桌上的苹果有几个？
把它们向上移动十厘米
桌上的苹果有几个？
```

首轮仅导出机器人计划，不表示苹果已进入篮子。第二轮应返回 2，焦点保留两个实例。
水平编辑仍贴桌时 on 查询应为 2；抬离桌面后为 0，不恢复旧 support。
若要检验集合后的单数歧义，在第二轮后另输入“它在哪里？”，应澄清而非选择第一个。
“把苹果移到香蕉右边”为直接编辑；“把苹果放到香蕉右边”为机器人规划。
编辑测试先确保场景有香蕉、目标唯一；不要把无参照物自动补造当成验收通过。

Query 与 Robot 共用 semantic entity selection。查看 debug/brain_turn.json：
scene_query 只能有 query_type/entities/relations/target，不能有旧顶层名称或 referent ID。
复数实体应为 dialogue_ref_set=true、quantity_mode=all、all_available=true。
查看 query_result.json.object_ids 和编辑后的 scene_config.json，而非只看成功提示。
真实服务恢复后的专项还需记录中文别名、颜色、rightmost、TaskEntity、relations、
模型调用次数及最终 Query/Commands Schema。本轮未运行真实模型，详见交付报告。

默认支撑接触容差在 defaults JSON 的 support_contact_tolerance_m 设置（米，默认 .001）。
这是几何判定容差，不是给位姿加固定补偿；只推断水平表面，不推断容器内部。
缺少可验证支撑面的相对新增会返回 scene_edit_support_unknown。

Replay 的 manual.json 也包含“它们有几个？”；夹具内部带语义 marker，CLI 用户只输原句。
批处理现有 4 条用例，包括集合查询，不调用真实 Qwen。

## 查看本轮产物

查看本轮 `result.json` 的 turn_kind、run_status、reply、artifacts。
request_record.json 含非秘密配置摘要与指纹；debug 目录含 brain_turn.json、
task_intent.json、grounded_task.json、skill_plan.json（仅对应阶段完成时）、
model_calls.json、raw_model_response.txt（本轮实际模型调用时）以及失败 traceback.txt。
默认不保存原始模型响应；调试文件仍可能含用户任务内容，请按内部数据保管。
机器人交付需要同目录的 scene_config.json + commands.json；不是取最近一个旧文件。
scene_query 的回复来自确认快照，导出计划本身不会移动对象。编辑提交成功但保存失败
会返回 artifact_write_failed，并保留真实 scene_commit_status，不要盲目重复编辑。

常见错误：`scene_required`（无可查询/删除场景），`grounding_missing`（已有场景缺对象），
`asset_missing/asset_ambiguous`，`bootstrap_quantity_unspecified`（所有对象初始数量未知），
`bootstrap_layout_failed`（放不下），`motion_distance_evidence_missing`（未说距离/幅度），
`holding_conflict`，`execution_pending`，`scene_sync_unknown`，`provider_error`，
`artifact_write_failed`。不能把模型连接失败归因于用户任务不受支持。

run 退出码：0=交付成功，2=澄清/缺事实/能力阻止，3=不支持任务，4=运行失败。
chat 单轮失败继续交互；EOF、`/exit` 正常退出，Ctrl-C 返回 130。
batch 返回 4（失败）、2（仅跳过）、0（全部通过）。

## 测试与反馈

`python -m pytest -q brain_tests` 运行单元/回放/CLI/HTTP 注入测试，不要求本地 Qwen。
`scripts/wheel_smoke.py` 必须用安装 wheel 的新 venv 从仓库外执行；不设置源码 PYTHONPATH。

真实执行集成先调用 `BrainApplication.mark_dispatched(session_id, commands)`，再调用
`apply_execution_feedback(session_id, feedback, confirmed_scene=..., feedback_source="external")`。
演示反馈必须显式改为 `feedback_source="simulated"`；提供外部确认的新版本快照，不由
Brain 从计划猜执行后位姿。详见 contracts.md。CLI 本身没有仿真执行命令。

## 第二次 Qwen 专项

配置也可用 `ROBOT_BRAIN_PLANNER`、`ROBOT_BRAIN_PLANNER_MAX_COMPLETION_TOKENS`；
优先级仍是 CLI > 环境 > JSON > 默认。第一和第二次共用 base-url/model/key/timeout/
structured-output。首版默认保持 recipe，不会因模型失败自动切换其他 planner。

服务可用后，用不同的输出目录对照：

```bash
robot-brain run '把苹果放进篮子' --provider qwen --planner recipe \
  --model "$ROBOT_BRAIN_MODEL" --output-dir var/recipe-check --debug --json
robot-brain run '把苹果放进篮子' --provider qwen --planner qwen \
  --model "$ROBOT_BRAIN_MODEL" --planner-max-completion-tokens 1024 \
  --output-dir var/qwen-check --debug --json
```

检查本轮 result.json：无视觉回退时，recipe 是 understanding_calls=1、
skill_planning_calls=0；qwen 是 1、1。`vision_calls` 单独计数，不能笼统把所有
流程都称为“两次调用”。scene_edit/query/control/clarification 的 skill_planning_calls=0。

debug 文件：

- `planner_context.json`：实例展开后的语义角色、顺序、依赖、目标与初始持物状态。
- `planner_skill_catalog.txt`：本次实际发送的 7 个原子技能摘要，不是 Control 完整 SKILL.md。
- `raw_skill_plan.json`：原始第二次 JSON；无法解析则保留 text；连接失败则 available=false。
- `normalized_skill_plan.json`：Python 绑定角色并产生 step-N 后的计划（若成功走到此阶段）。
- `skill_plan_validation.json`：valid 及失败原因。
- `model_calls.json`、`traceback.txt`：调用记录与失败堆栈；不把失败当执行成功。

合法的重复 locate/区域 approach 可以通过；缺少抓取接近、未持有就 release、放置角色
交换、多抓一次、重复位移等仍拒绝。Planner 不能补救第一阶段误解的对象或数量。
失败错误阶段为 skill_planning，常见 code：skill_planning_provider_missing、
planner_operation_order_mismatch、planner_role_invalid、planner_region_invalid、
planner_unknown_skill、skill_plan_output_invalid、holding_conflict、plan_precondition_failed。

真实验收逐项记录 instruction、operation_count、recipe_steps、qwen_steps、qwen_valid、
semantic_validation、prompt_tokens、completion_tokens、latency、commands_count。
应覆盖抓住苹果、放进篮子、按按钮、开/关门、开门→放入→关门、抓起→移动五厘米→放下、
先开门→两个苹果放入→关门。按钮/柜子/把手等需真实资产元数据与合法场景，不能用 demo
资产假装支持。当前既有 domain policy 将“把苹果向右移动五厘米”判为直接 scene_edit，
所以它是“零次第二规划”的对照项；要测机器人 MOVE 请说“抓起苹果，向右移动五厘米后放下”。

本轮服务 8080 不可达，以上是真实验收流程，不是真实模型通过记录。
