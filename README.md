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

## Development

```bash
cd /home/cscvlab/lht/robot_agent_brain
python -m pip install -e '.[dev]'
pytest brain_tests/
```

The test suite includes a dependency-boundary check and runs without MuJoCo or
`robot_agent_control` installed.

