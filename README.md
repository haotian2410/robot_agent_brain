# robot_agent_brain

`robot_agent_brain` is the simulator-independent semantic-planning layer split
from `robot_agent_stack`. It owns user intent, dialogue semantics, scene
semantics, grounding, task decomposition, vague-motion distance resolution,
Atomic Skill ordering, and single-arm `commands.json` v2 / dual-arm v3 export.

It intentionally does **not** depend on MuJoCo, `robot_agent_control`, MJCF,
IK, robot collision checking, reachability, path/trajectory planning, gripper
simulation, runtime playback, or execution verification.

## 双臂与原始场景扩展

已支持部署 profile 驱动的单/双臂配置、双臂分阶段抓取/放置/移动规划、逐臂反馈，
以及不可变原始场景快照和 current/original 物体替换。双臂命令使用 v3：阶段间等待，
阶段内允许两臂并行，`null` 臂保持已有状态；不是两份独立的单臂命令。

- [实现范围、配置字段与验证记录](docs/dual_arm_implementation_status.md)
- [真实 Qwen 双臂 demo 与产物目录](demo/dual_arm/README.md)
- [WebEditor 首期部署、AgentService 接口和前端协作契约](docs/webeditor_integration.md)
- [WebEditor 测试与实际联调状态](demo/webeditor/README.md)（仅生成计划，不执行机器人）

双臂需要显式注册真实机器人映射；演示中的 `DEMO_ONLY` 接口不能用于 Control。
原始场景首次成功且含任务物体时保存为会话目录下的 `original_scene.json`，不随
后续编辑覆盖。恢复原始场景需要重置授权和已知空闲状态，并使旧计划失效。
倒水暂不实现，等待控制端新版 `skill.md`；Brain 规划通过不代表物理执行成功。

## 安装与自测

Python 3.11/3.12，当前 CLI 会话锁使用 Linux/POSIX 文件锁。

```bash
cd /home/cscvlab/lht/robot_agent_brain
python -m pip install -e '.[dev]'
robot-brain --help
```

这不是旧仓库的 `robot-agent run/chat`。本仓库入口是 **`robot-brain`**，
默认只生成团队组件 Scene v1 JSON 和语义命令，不打开 MuJoCo，也不执行机器人。

真实 Qwen：先由部署端启动兼容 `/v1/chat/completions` 的服务，并确认实际模型名。
下面的 `QWEN_MODEL` 应替换为服务 `/v1/models` 返回的名称，不能仅凭本地模型目录推断。

```bash
curl --noproxy '*' http://127.0.0.1:8080/v1/models
export ROBOT_BRAIN_MODEL="$QWEN_MODEL"
export ROBOT_BRAIN_BASE_URL=http://127.0.0.1:8080/v1
robot-brain run '把两个苹果放进篮子' --output-dir var/manual-tests
robot-brain chat --output-dir var/manual-tests
```

不传 `--scene` 时，首轮根据一次任务理解生成对象和初始布局，然后继续处理同一个
BrainTurn。苹果不会预先放进篮子，首轮 add 不会重复新增。已有场景则复用确认快照，
缺对象会报错，不会悄悄补造。

没有模型服务时，可以明确选择 **Replay 回放**，它只接受夹具中完全相同的输入：

```bash
robot-brain run '增加一个苹果' --provider replay \
  --replay-file examples/replay/add_apple.json --output-dir var/replay
robot-brain run '把两个苹果放进篮子' --provider replay \
  --replay-file examples/replay/manual.json --output-dir var/replay
robot-brain batch --provider replay --replay-file examples/replay/manual.json \
  --cases examples/cases/manual_cases.jsonl --output-dir var/batch
robot-brain schemas --output-dir var/schemas
```

Replay 验证工程链路，不证明真实 Qwen 理解质量。模型连接失败不会自动切换 Replay。
真实多轮 demo 的分版本记录见 [demo/VALIDATION.md](demo/VALIDATION.md)。测试、wheel 与 CI 记录见
[implementation_report](docs/implementation_report.md)。

### final_models 资产库

支持 Scene Edit 缩放与实例改色，规则和配置见 [缩放/颜色说明](docs/scene_scale_color.md)。
真实 Qwen 多轮示例：`python demo/final_models/scale_color_demo.py`。

本仓库默认检测 `config/final_models.json`，使用 `model/final_models` 下的新资产库。
该目录由 `/home/cscvlab/下载/final_models.7z` 解压得到，已加入 gitignore，不会提交模型文件。
显式场景可以直接传入：

```bash
robot-brain run '把苹果放进篮子' --config config/final_models.json \
  --scene model/final_models/scenes/3/ur5e_table_sorting.json \
  --provider qwen --planner qwen --model "$ROBOT_BRAIN_MODEL" \
  --output-dir var/final-models-demo --debug
```

新库的模型和机器人数字 ID 独立，必须通过 `MetadataRef.path + type` 区分：
`$LIBRARY_SERVER/1` with `model` 是 apple，with `robot` 是 ur5e_arm。场景中的
`RobotAttachment`、初始关节和连接关节会原样保留；Brain 不执行 URDF 正向运动学。
不传 `--scene` 时以 `scenes/1/ur5e_table_empty.json` 为平台模板增加任务对象。
多个同名资产（例如 basket）需要颜色/tag 或进一步描述，否则返回澄清。
显式场景不会补造不存在的对象：场景 2 只有苹果，没有篮子；使用上面的场景 3，
或不传 `--scene` 并输入“把苹果放进蓝色篮子”自动建场景。

首次部署/校验：

```bash
python scripts/validate_final_models.py --root model/final_models \
  --cache config/final_models_geometry_cache.json
```

该脚本检查 29 个模型、14 个机器人、5 个场景及所有资源引用；geometry cache 写在
`config/`，不会写回 `final_models`。当前 Brain 仍只导出 Scene JSON/Commands，
不替代 Control、MuJoCo 或机器人执行器。

当前原始包已发现 PR2（robots/13）的 OBJ 引用缺失的 `material.mtl`。
严格验证会输出 `valid=false` 和缺失列表、返回码 2；仍输出可用的派生 cache，
未知静态边界保持 null，不伪造。资产原文件不会修补，需资产提供方补全。
这不影响 UR5e 示例。真实 Qwen 示例见 `demo/final_models/README.md`。

## 配置与产物

真实 Qwen 的两组多轮样例（首轮建场景、机械臂操作规划、复合场景修改）及一键脚本见
[demo/README.md](demo/README.md)，本机实测结果索引见 [demo/VALIDATION.md](demo/VALIDATION.md)。

优先级：命令行 > `ROBOT_BRAIN_*` 环境变量 > `--config` JSON > 包内默认值。
模型名没有猜测默认值；真实模型必须配置。API key 仅通过 `ROBOT_BRAIN_API_KEY`
传入，不写入配置文件。`--assets` 和 `--defaults` 可覆盖资产索引和布局配置。
默认资产是标注为 demo 的尺寸/类别/属性元数据，不包含真实 mesh，也不声称完成渲染。

### 团队 Scene v1 与正式资产库

唯一运行时场景为 `scene_schema_version=1` 的组件格式：
`scene_id`、`object_id_in_scene` 是 JS-safe 非负整数，每个对象有且只有一个 Transform。
`MetadataRef.path` 是唯一资产引用；不增加 Scene `asset_id`。
`Semantic.semantic_name/category/support` 保持团队定义。Camera、Light、RobotDriver、
MeshRenderer 和未知组件往返保留，`parent=0` 表示对象 0 的子节点，不是 null。
旧 flat Scene 和旧 session checkpoint 不自动迁移，请用新会话或正式新协议快照。

本地真实库配置见 [config/local_asset_library.json](config/local_asset_library.json)。
该配置只读 `model/grasp_objects` 的 index/metadata 和外置几何缓存；运行时不扫描 OBJ。
离线生成/验证缓存：

```bash
python scripts/build_asset_geometry_cache.py --asset-root model/grasp_objects \
  --output config/brain_asset_geometry_cache.json
python scripts/validate_asset_geometry_cache.py --asset-root model/grasp_objects \
  --cache config/brain_asset_geometry_cache.json
```

原资产文件不改写、不打包、不推送。已有 Scene 的名称/类别以 Semantic 为准，
中文别名放 `config/semantic_aliases.json`。category-only 新建需要可选分类 sidecar，
未配置明确返回 `asset_category_unavailable`；多个候选不会随机选。

**正式库从零建场景尚需部署配置**：抓取资产 1–21 不包含桌子和机器人。
需要真实 `default_table_metadata_ref`、`default_robot_metadata_ref`、
`default_robot_driver`（joint_sequence/joint_limits），并由资产适配器提供对应资源及几何。
示例留空，不编造 101/2001，也不混用 demo 资源。当前本地 adapter 只解析配置库 index；
外部平台资源需要部署端实现同一 AssetLibraryPort/提供完整库，不能仅填一个不存在的 ID。
默认 demo 独立使用 `$DEMO_LIBRARY/` 和合成 demo_joint，仅用于工程示例，不是 UR5e 实参。
真实库配置的 `model` 也必须改为 `/models` 实际返回值。

公共 Pydantic 定义见 [scene.py](src/robot_agent_brain/contracts/scene.py)；
`robot-brain schemas --output-dir var/schemas` 导出 `scene_config.schema.json`、
`commands.schema.json` 和 `run_report.schema.json`。

### 可选第二次 Qwen：Atomic Skill Planner

`run/chat/batch` 都支持 `--planner recipe|qwen|auto`，默认 **recipe**：

| 模式 | 已接受的机器人任务 |
|---|---|
| recipe | 一次理解 + Python 固定 recipe，零次模型技能规划 |
| qwen | 一次理解 + 一次 Qwen 技能规划；失败明确返回，不回退 recipe |
| auto | 仅当 `RecipePlanner.supports(task)` 为 false 才用 Qwen；不是异常 fallback |

```bash
robot-brain run '把苹果放进篮子' --provider qwen --planner qwen \
  --base-url http://127.0.0.1:8080/v1 --model "$QWEN_MODEL" \
  --structured-output json_schema --planner-max-completion-tokens 1024 \
  --output-dir var/qwen-planner --debug
robot-brain chat --provider qwen --planner qwen \
  --model "$QWEN_MODEL" --output-dir var/qwen-planner --debug
```

第二阶段复用同一模型/地址/key，只收精简语义上下文（实体带整数 `scene_object_id`），
输出控制端原子方言 `{"commands":[...]}`：`approach`、`pick`、`lift_up`、`retreat`、
`move_to`、`put`、`pull`、`push` 八个技能，prompt 里放 skill.md 全文和一张由
`contracts/commands_atomic.py` 现场生成的参数表，所以规范正文与校验器不会各说一套话。
装配规则由 `planning/atomic_plan_validator.py` 校验，违反一次只多花一轮修复。
实体绑定、数量、放置目标仍由第一阶段与 Python 确定；`put` 的相对落点以任务为准，
Brain 会补上固定边距并覆盖模型自己写的 `relation`/`distance_m`，任务没要求相对落点时
一律清掉。`put` 的 `front`/`behind`/`left`/`right` 走目的地水平外侧（需要可见支撑面），
`above`/`below` 自控制端 `b24cc3f` 起沿世界 Z 轴直接给出可悬空的空间释放点，不再被
规划阶段拒绝；只有「桌子左上角」这类需要两个方向才能确定的落点仍然报错，不会带着猜测
下发。
Query、Scene Edit、会话控制、澄清都不调用第二阶段。

`--planner recipe` 走同一套校验的确定性展开，覆盖 grasp/release/pick_and_place 与
open/close（后者按 approach→pick→pull/push→retreat 抓把手推拉）；locate/move/press/search
仍返回 `atomic_capability_unsupported`，不会让 Qwen 勉强凑成六个抓放命令。
Replay 只支持理解回放；`--planner qwen` 会报 `skill_planning_provider_missing`，
而 recipe/auto 可继续回放。

`result.json.metrics` 记录逐阶段调用数和实际 planner；`--debug` 额外保存
planner_context、raw_skill_plan、normalized_skill_plan、
skill_plan_validation。失败不输出本轮 commands、不链接旧 commands、不伪造执行；
无场景首轮机器人任务在规划通过后才提交初始场景。
完整字段与限制见 [contracts](docs/contracts.md)，验收见 [报告](docs/implementation_report.md)。

每轮生成新目录：

```text
OUTPUT/SESSION/session_state.json
OUTPUT/SESSION/REQUEST/result.json
OUTPUT/SESSION/REQUEST/request_record.json
OUTPUT/SESSION/REQUEST/scene_config.json   # 本轮确认场景（若存在）
OUTPUT/SESSION/REQUEST/scene_patch.json    # 场景编辑时
OUTPUT/SESSION/REQUEST/commands.json       # 合法机器人计划时
OUTPUT/SESSION/REQUEST/query_result.json   # 查询时
```

机器人报告明确显示“尚未执行”，`executed=false`。场景和 commands 的 ID/版本匹配。
`scene_config.json` 是**团队组件 Scene v1 JSON，不是 scene.xml/MJCF**；
`commands.json` 仍是 Brain Commands v2（目标/参照已迁为整数），不是 taskStep。
不能据此声称旧 Control 已兼容；实际加载、渲染、执行接口仍需独立联调。

导入现有 Brain 原生场景使用 `--scene PATH`；原文件不被修改。恢复会话使用同一
输出根目录和 `--session SESSION_ID`。chat 支持 `/help`、`/status`、`/load PATH`、
`/exit`；`/exit` 仅退出客户端，语义 close 则关闭会话。

详细参数、错误与可复制流程见 [手动测试](docs/manual_testing.md)；协议和反馈接口见
[契约说明](docs/contracts.md)。

### 执行子进程里的感知模型

控制端在 `approach`/`pick`/`put` 里用 VLM 从相机帧上取抓取点。它自带一个写死的
DashScope base URL，密钥已不可用，因此本部署把这条感知也接到本机 Qwen：大脑把自己
配置里的 `base_url` 与 `model` 随执行子进程下发（`ROBOT_LINK_VLM_BASE_URL`、
`QWEN_MODEL`），`robot_agent_link` 在 `demo.run_demo` 导入之前替换掉控制端那个客户端
工厂。控制端仓库保持零本地改动，`DASHSCOPE_API_KEY` 不再参与执行。

换地址只是必要的一半：本地模型回答 JSON 请求时会在对象外面套 Markdown 围栏，而控制端
的解析器要求字符串第一个字符就是 `{`，一个正确的抓取点也会被判定成无效回复，所以
返回文本在进入控制端前已被裁成纯 JSON 对象。

排查只看子进程日志的第一行 `link: perception VLM -> <base_url>`；补丁打不上时它改为
`... FAILED` 并继续按控制端原端点跑，感知端点不是执行的前置条件。

### 执行失败怎么说话

`report.json` 里的错误是控制端的结构化 payload（`error_code`、`failed_stage`、
`error_message`、`details`），裸读出来是英文加一串碰撞对象，浏览器里没法看。
`robot_agent_link/link/error_descriptions.py` 因此按路径读出控制端自己的
`demo/error_messages.py`，并用 `ast` 从 `demo/run_demo.py` 里取出
`ERROR_DESCRIPTIONS`/`STAGE_DESCRIPTIONS` 两张字面量表——不 import 控制端包（它会拉起
MuJoCo/FCL），也不在 Brain 里抄一份会过期的词表——于是任务错误信息与子进程控制台打印的
那句完全一致，例如：

```text
Apple 与 WorkTable 穿透 3.142 mm，无法按指定路径运动（PATH_CONSTRAINT_INFEASIBLE）
RRT-Connect 在 5 s 规划预算内未找到无碰撞路径（PATH_NOT_FOUND）
持物相对夹爪滑移 8.40 mm（GRASP_FAILED）
```

三条兜底：报告顶层没有 error 时取第一个失败命令的 error（否则只剩一串日志尾巴）；
`runner_report_missing`、超时这些控制端来不及写的原因由桥自己造句；控制端目录读不到时
`describe_for` 返回 None，退回原始报文——措辞可以缺，失败原因不能缺。

## Architecture invariant

> Brain owns semantic intent and scene semantics.
>
> Brain may compute deterministic quantities that depend only on shared
> scene/asset metadata, including vague-motion distance resolution.
>
> Brain must not solve robot-specific physical execution problems.
>
> Control owns concrete interaction poses, IK, collision checking,
> reachability, path planning, trajectories and execution verification.
>
> The scene platform owns rendering and concrete scene realization.

中文边界：

- 大脑负责“做什么”。
- 对于只依赖公共场景/资产信息的确定性量，例如模型尺寸百分比对应的移动距离，大脑允许直接计算。
- 控制端负责“机器人具体如何做到”。
- 场景平台负责“场景如何被实际加载、修改和渲染”。

## Public flow

```text
User request -> TaskIntent -> GroundedTask -> TaskExpander -> MotionScaleResolver
             -> SkillPlannerRouter(recipe/qwen/auto) -> PlanValidator
             -> SkillPlan -> CommandExporter -> commands.json v2

SceneConfig / ScenePatch -> ScenePlatformPort
CameraRequest             -> ScenePlatformPort -> CameraFrame -> VLM
MetadataRef.path          -> AssetLibraryPort   -> BrainAssetView (geometry/resource)
```

`commands.json` contains semantic regions such as `grasp_region` and
`placement_region`; it never contains physical anchors, poses, XML paths,
runtime settings, IK parameters, or trajectories.

The complete Brain turn contract supports `robot_task`, `scene_edit`,
`scene_query`, and `session_control`. Robot tasks pass through semantic
relation grounding, concrete instance expansion, motion-scale resolution,
recipe or optional Qwen skill planning, shared validation, and command export. Scene edits produce `ScenePatch`, scene
queries read the local `SceneConfig`, and session control produces a semantic
pause/resume/close action.

For a set such as two apples, planning expands the set into concrete entities
and emits one command sequence per scene object. `CommandExporter` fails if a
set reaches it without expansion, so a command can never contain a list of
physical targets.

### Scene edits versus robot actions

`把苹果向右移动十厘米` and `把苹果旋转 30 度` are scene edits: Brain returns
`ScenePatch` and no robot commands. Translation preserves rotation/scale;
rotation changes the requested orientation. `把苹果放到香蕉右边` is a robot pick-and-place task and returns
`commands.json`. A mixed request such as `抓起苹果，右移十厘米后放下` remains
a robot chain; a request that mixes a direct scene edit with a robot chain is
rejected for clarification instead of being partially applied.

Vague motion uses model-relative distances for both domains: `small`, `medium`,
and `large` mean 10%, 50%, and 200% of the selected object's model extent on
the requested axis, including instance scale.

## Development

```bash
cd /home/cscvlab/lht/robot_agent_brain
python -m pip install -e '.[dev]'
pytest brain_tests/
```

The test suite includes a dependency-boundary check and runs without MuJoCo or
`robot_agent_control` installed.
