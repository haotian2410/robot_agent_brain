# robot_agent_brain

`robot_agent_brain` is the simulator-independent semantic-planning layer split
from `robot_agent_stack`. It owns user intent, dialogue semantics, scene
semantics, grounding, task decomposition, vague-motion distance resolution,
Atomic Skill ordering, and `commands.json` v2 export.

It intentionally does **not** depend on MuJoCo, `robot_agent_control`, MJCF,
IK, robot collision checking, reachability, path/trajectory planning, gripper
simulation, runtime playback, or execution verification.

## 安装与自测

Python 3.11/3.12，当前 CLI 会话锁使用 Linux/POSIX 文件锁。

```bash
cd /home/cscvlab/lht/robot_agent_brain
python -m pip install -e '.[dev]'
robot-brain --help
```

这不是旧仓库的 `robot-agent run/chat`。本仓库入口是 **`robot-brain`**，
默认只生成 Brain 原生场景 JSON 和语义命令，不打开 MuJoCo，也不执行机器人。

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
2026-10-07 本机 `8080` 服务连接失败，真实 Qwen 验收未运行；测试与 wheel 验收记录见
[implementation_report](docs/implementation_report.md)。

## 配置与产物

优先级：命令行 > `ROBOT_BRAIN_*` 环境变量 > `--config` JSON > 包内默认值。
模型名没有猜测默认值；真实模型必须配置。API key 仅通过 `ROBOT_BRAIN_API_KEY`
传入，不写入配置文件。`--assets` 和 `--defaults` 可覆盖资产索引和布局配置。
默认资产是标注为 demo 的尺寸/类别/属性元数据，不包含真实 mesh，也不声称完成渲染。

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
`scene_config.json` 是 **Brain JSON，不是 scene.xml/MJCF**；不能直接交给旧 Control
就声称接口已经兼容。团队 components/taskStep 格式尚未冻结，需要独立适配与联调。

导入现有 Brain 原生场景使用 `--scene PATH`；原文件不被修改。恢复会话使用同一
输出根目录和 `--session SESSION_ID`。chat 支持 `/help`、`/status`、`/load PATH`、
`/exit`；`/exit` 仅退出客户端，语义 close 则关闭会话。

详细参数、错误与可复制流程见 [手动测试](docs/manual_testing.md)；协议和反馈接口见
[契约说明](docs/contracts.md)。

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
User request -> TaskIntent -> GroundedTask -> MotionScaleResolver
             -> SkillPlan -> CommandExporter -> commands.json v2

SceneConfig / ScenePatch -> ScenePlatformPort
CameraRequest             -> ScenePlatformPort -> CameraFrame -> VLM
asset_id                  -> AssetCatalogPort   -> ModelProperty
```

`commands.json` contains semantic regions such as `grasp_region` and
`placement_region`; it never contains physical anchors, poses, XML paths,
runtime settings, IK parameters, or trajectories.

The complete Brain turn contract supports `robot_task`, `scene_edit`,
`scene_query`, and `session_control`. Robot tasks pass through semantic
relation grounding, concrete instance expansion, motion-scale resolution,
recipe planning, and command export. Scene edits produce `ScenePatch`, scene
queries read the local `SceneConfig`, and session control produces a semantic
pause/resume/close action.

For a set such as two apples, planning expands the set into concrete entities
and emits one command sequence per scene object. `CommandExporter` fails if a
set reaches it without expansion, so a command can never contain a list of
physical targets.

### Scene edits versus robot actions

`把苹果向右移动十厘米` and `把苹果旋转 30 度` are scene edits: Brain returns
`ScenePatch` and no robot commands, preserving the object's quaternion and
scale. `把苹果放到香蕉右边` is a robot pick-and-place task and returns
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
