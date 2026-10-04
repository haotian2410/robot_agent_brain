# robot_agent_brain

`robot_agent_brain` is the simulator-independent semantic-planning layer split
from `robot_agent_stack`. It owns user intent, dialogue semantics, scene
semantics, grounding, task decomposition, vague-motion distance resolution,
Atomic Skill ordering, and `commands.json` v2 export.

It intentionally does **not** depend on MuJoCo, `robot_agent_control`, MJCF,
IK, collision checking, reachability, path/trajectory planning, gripper
simulation, runtime playback, or execution verification.

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
