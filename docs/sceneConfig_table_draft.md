# sceneConfig 表格填充草稿

来源表格：`公共变量与接口_v0.2.lxtable` 的 `sceneConfig` 页。  
状态：仅供检查，尚未写回有道云表格。

## “生成来源”字段的建议枚举

第三列建议填写“来源类型 + 具体依据文件”，而不是只写文件路径。推荐使用以下值：

| 来源枚举 | 含义 | 当前依据 |
|---|---|---|
| `globalDefaultSetting` | 系统/部署默认配置，不由本次用户输入产生 | `config/final_models.json`、`config/webeditor.json` |
| `protocolDefault` | 协议或解析器规定的缺省值 | `src/robot_agent_brain/contracts/scene.py`、`src/robot_agent_brain/web/protocol.py` |
| `sceneTemplate` | 载入的模板场景中已有的实例值 | `model/final_models/scenes/1/ur5e_table_empty.json` |
| `assetLibrary` | 资产库元数据、索引或 URDF 提供的值 | `model/final_models/models/*`、`model/final_models/robots/*` |
| `userProvided` | 用户在任务或编辑器中明确给出的值 | 用户请求、WebEditor 编辑请求 |
| `browserGenerated` | 浏览器/Gateway 在 setup 或提交阶段生成的值 | `src/robot_agent_brain/web/gateway.py`、前端提交的 Scene |
| `agentDerived` | Brain 根据任务、场景编辑规则计算出的值 | `src/robot_agent_brain/scene/editor.py`、`src/robot_agent_brain/scene/scale_policy.py` |
| `gatewayAssigned` | Gateway 分配的场景版本、对象 ID 或事务字段 | `src/robot_agent_brain/web/service.py`、`config/webeditor.json` |
| `modelOutput` | Qwen 等模型输出、经协议校验后的语义结果 | `src/robot_agent_brain/models/prompt_templates/`、任务运行记录 |

因此，例如默认 UR5e 应填写：`globalDefaultSetting（config/final_models.json；$LIBRARY_SERVER/1）`；用户说“换成 Piper”才填写：`userProvided（用户请求）`，随后解析出的具体资产再标记为 `assetLibrary（model/final_models/robots/...）`。

## 默认值口径

表中的“默认值”分两类：协议字段默认值来自 Brain 的协议/解析代码；部署示例默认值来自当前 `final_models` 配置和模板场景。当前默认机械臂是 **UR5e**，不是泛化的“robot”。

- 默认配置：`config/final_models.json`；WebEditor 联调配置：`config/webeditor.json`。
- 默认场景：`model/final_models/scenes/1/ur5e_table_empty.json`（配置中的 `default_scene`）。该文件当前 `scene_id=1`、`scene_version=3`、`scene_name=ur5e_table_empty`。
- 默认机械臂：`robot=ur5e`，`MetadataRef.path=$LIBRARY_SERVER/1`、`type=robot`；具体资产文件为 `model/final_models/robots/1/ur5e_arm.json`，索引见 `model/final_models/robots/robot_index.json`。
- 默认桌子：`MetadataRef.path=$LIBRARY_SERVER/29`、`type=model`；具体资产文件为 `model/final_models/models/29/table.json`，索引见 `model/final_models/models/model_index.json`。
- 默认场景中的夹爪是对象 `3`、引用 `$LIBRARY_SERVER/2`（`model/final_models/robots/2/robotiq_2f85.json`）；相机是两个独立实例：腕部相机对象 `4`、顶视相机对象 `5`，均引用 `$LIBRARY_SERVER/3`（`model/final_models/robots/3/d435i.json`）。服务默认绑定相机 ID 为 `5` 的代码来源是 `src/robot_agent_brain/web/service.py`；实际会话绑定以 `POST /sessions` 的 `camera_id` 为准。
- 默认机器人关节初值和连接关节来自 `config/final_models.json` 的 `default_robot_driver`，模板场景中的同名 `RobotDriver` 也完整保存。

## 顶层字段

| 索引名 | 内容（如数值） | 生成来源（来源枚举 + 具体文件） |
|---|---|---|
| `scene_schema_version` | `1` | `src/robot_agent_brain/contracts/scene.py`；样例值见 `model/final_models/scenes/1/ur5e_table_empty.json` |
| `scene_id` | `uint32`；当前默认模板为 `1` | 模板：`model/final_models/scenes/1/ur5e_table_empty.json`；WebEditor 上限与配置：`config/webeditor.json`（`scene_id_bits=32`） |
| `scene_version` | `uint32`；默认模板当前为 `3`，Agent 原子写回后递增 | `model/final_models/scenes/1/ur5e_table_empty.json`；写回规则：`src/robot_agent_brain/web/service.py` |
| `scene_sub_version` | `uint32`，缺省 `0`；setup 阶段浏览器增删物体时递增 | 协议：`src/robot_agent_brain/web/protocol.py`；流程：`docs/docs/执行包/gateway与Agent新通信流程.md` |
| `scene_name` | 默认 `ur5e_table_empty`；其他场景例如 `ur5e_table_sorting` | `model/final_models/scenes/1/ur5e_table_empty.json`；场景索引：`model/final_models/scenes/scene_index.json` |
| `objects` | `SceneObject[]`，完整场景对象数组；默认模板含 7 个对象 | `model/final_models/scenes/1/ur5e_table_empty.json` |

## `SceneObject`

| 索引名 | 内容（如数值） | 生成来源（来源枚举 + 具体文件） |
|---|---|---|
| `objects[].object_id_in_scene` | `uint32`，同一场景内唯一；删除后不得复用 | 对象值：`model/final_models/scenes/1/ur5e_table_empty.json`；分配规则：`src/robot_agent_brain/web/service.py`、`config/webeditor.json` |
| `objects[].object_name_in_scene` | 场景内显示名称，例如 `work_table`、`ur5e_arm`、`overhead_camera_d435i` | `model/final_models/scenes/1/ur5e_table_empty.json` |
| `objects[].components` | `SceneComponent[]` | `src/robot_agent_brain/contracts/scene.py`；实例值：`model/final_models/scenes/1/ur5e_table_empty.json` |
| `components[].component_type` | 已知类型或未知扩展类型字符串 | 协议类型：`src/robot_agent_brain/contracts/scene.py`；原始样例：`model/final_models/scenes/1/ur5e_table_empty.json` |
| `components[].properties` | 对应该组件的属性对象；未知字段必须保留 | 场景原文：`model/final_models/scenes/1/ur5e_table_empty.json`；宽容解析约定：`docs/docs/执行包/场景文件描述.md` |

## 已知组件属性

| 索引名 | 内容（如数值） | 生成来源（来源枚举 + 具体文件） |
|---|---|---|
| `Transform.position` | `[x,y,z]` 局部坐标；缺省 `[0,0,0]`。模板桌子为 `[0.525,0,0]` | `model/final_models/scenes/1/ur5e_table_empty.json`；缺省规则：`src/robot_agent_brain/contracts/scene.py` |
| `Transform.quaternion_xyzw` | `[x,y,z,w]`；缺省 `[0,0,0,1]` | `model/final_models/scenes/1/ur5e_table_empty.json`；`src/robot_agent_brain/contracts/scene.py` |
| `Transform.scale` | `[sx,sy,sz]`；新建对象默认 `[1,1,1]` | `src/robot_agent_brain/scene/editor.py`、`src/robot_agent_brain/scene/scale_policy.py`；模板实例：`model/final_models/scenes/1/ur5e_table_empty.json` |
| `Transform.parent` | 父对象 `uint32` 或 `null`；夹爪 parent 为 `2`，腕部相机 parent 为 `3` | `model/final_models/scenes/1/ur5e_table_empty.json` |
| `MetadataRef.path` | 默认机械臂 `$LIBRARY_SERVER/1`，桌子 `$LIBRARY_SERVER/29` | `config/final_models.json`；资产索引：`model/final_models/robots/robot_index.json`、`model/final_models/models/model_index.json` |
| `MetadataRef.type` | `model` 或 `robot`；同一数字 ID 必须靠 type 区分 | `src/robot_agent_brain/contracts/scene.py`；具体实例：`model/final_models/scenes/1/ur5e_table_empty.json` |
| `Semantic.semantic_name` | 默认平台对象：`work_table`、`ur5e_arm`、`robotiq_2f85`、`overhead_camera_d435i` | `model/final_models/scenes/1/ur5e_table_empty.json` |
| `Semantic.category` | 例如 `surface`、`robot`、`end_effector`、`sensor` | `model/final_models/scenes/1/ur5e_table_empty.json` |
| `Semantic.support` | 支撑对象 `uint32` 或 `null` | `model/final_models/scenes/1/ur5e_table_empty.json`；编辑逻辑：`src/robot_agent_brain/scene/editor.py` |
| `MeshRenderer.forceOverrideColor` | `#RRGGBB` 或 `#RRGGBBAA`；模板平台对象实际为 `#FFFFFF` | `model/final_models/scenes/1/ur5e_table_empty.json`；解析/颜色规则：`src/robot_agent_brain/scene/colors.py` |
| `Light.type` | 默认模板为 `Ambient` | `model/final_models/scenes/1/ur5e_table_empty.json` |
| `Light.intensity` | 默认模板为 `0.7` | `model/final_models/scenes/1/ur5e_table_empty.json` |
| `Light.color` | 默认模板为 `#FFFFFF` | `model/final_models/scenes/1/ur5e_table_empty.json` |
| `Camera.type` | 默认模板相机为 `rgbd` | `model/final_models/scenes/1/ur5e_table_empty.json` |
| `Camera.fov` | 默认 `60` | `model/final_models/scenes/1/ur5e_table_empty.json` |
| `Camera.near` | 默认 `0.01` | `model/final_models/scenes/1/ur5e_table_empty.json` |
| `Camera.far` | 默认 `10` | `model/final_models/scenes/1/ur5e_table_empty.json` |
| `Camera.resolution` | 默认 `[640,480]` | `model/final_models/scenes/1/ur5e_table_empty.json` |
| `RobotDriver.joint_sequence` | UR5e 六轴：`shoulder_pan_joint`、`shoulder_lift_joint`、`elbow_joint`、`wrist_1_joint`、`wrist_2_joint`、`wrist_3_joint` | `config/final_models.json`；模板实例：`model/final_models/scenes/1/ur5e_table_empty.json` |
| `RobotDriver.joint_limits` | UR5e 各关节弧度上下限 | `config/final_models.json`；资产 URDF：`model/final_models/robots/1/ur5e_arm.urdf` |
| `RobotDriver.initial_joint_positions_rad` | 按上述关节顺序为 `[0,-2.094395,1.570796,-1.5707963,-1.5707963,0]` | `config/final_models.json`；模板实例：`model/final_models/scenes/1/ur5e_table_empty.json` |
| `RobotDriver.now_joint_positions_rad` | 当前显示姿态；没有固定默认值，可缺省 | 协议字段：`src/robot_agent_brain/contracts/scene.py`；浏览器更新接口：`src/robot_agent_brain/web/service.py` |
| `RobotDriver.available_connect_joints` | 默认 UR5e 为 `[wrist_3_joint]` | `config/final_models.json`；模板实例：`model/final_models/scenes/1/ur5e_table_empty.json` |
| `RobotDriver.role` | `arm` 或 `passive`；当前 UR5e 模板未写该字段时按协议读取层处理 | `docs/docs/执行包/场景文件描述.md`；解析：`src/robot_agent_brain/contracts/scene.py` |
| `RobotAttachment.parent_object_id` | 默认夹爪挂到 UR5e 对象 `2` | `model/final_models/scenes/1/ur5e_table_empty.json` |
| `RobotAttachment.parent_joint` | `wrist_3_joint` | `model/final_models/scenes/1/ur5e_table_empty.json`；URDF：`model/final_models/robots/1/ur5e_arm.urdf` |
| `RobotAttachment.parent_link` | `wrist_3_link` | `model/final_models/scenes/1/ur5e_table_empty.json`；URDF：`model/final_models/robots/1/ur5e_arm.urdf` |
| `RobotAttachment.child_link` | `robotiq_base_link` | `model/final_models/scenes/1/ur5e_table_empty.json`；URDF：`model/final_models/robots/2/robotiq_2f85.urdf` |
| `RobotAttachment.connection_type` | `fixed` | `model/final_models/scenes/1/ur5e_table_empty.json` |
| `RobotAttachment.transform` | 模板夹爪挂载位姿：含 `position`、`quaternion_xyzw`、`reference_frame=parent_link` | `model/final_models/scenes/1/ur5e_table_empty.json` |

## 当前可直接放入表格的示例值

| 索引名 | 内容（如数值） | 生成来源（来源枚举 + 具体文件） |
|---|---|---|
| `robot` | `ur5e`（UR5e 机械臂，MetadataRef `$LIBRARY_SERVER/1`） | `config/final_models.json`、`config/webeditor.json`、`model/final_models/robots/1/ur5e_arm.json` |
| `table` | `work_table`（桌子，MetadataRef `$LIBRARY_SERVER/29`） | `config/final_models.json`、`model/final_models/models/29/table.json`、`model/final_models/scenes/1/ur5e_table_empty.json` |
| `gripper` | `robotiq_2f85`（MetadataRef `$LIBRARY_SERVER/2`） | `model/final_models/scenes/1/ur5e_table_empty.json`、`model/final_models/robots/2/robotiq_2f85.json` |
| `camera` | `wrist_camera_d435i`（对象 `4`）或 `overhead_camera_d435i`（对象 `5`），均为 `rgbd 640×480` | `model/final_models/scenes/1/ur5e_table_empty.json`、`src/robot_agent_brain/web/service.py` |
| `scene` | `ur5e_table_empty`（`scene_id=1, scene_version=3`） | `config/final_models.json`、`model/final_models/scenes/1/ur5e_table_empty.json` |

## 备注

1. 该表描述 Scene 配置，不是 MuJoCo XML，也不是 `commands.json`。
2. 协议默认值与某个模板场景的实例值必须区分；例如新对象的 `Transform.scale` 默认 `[1,1,1]`，但已有模板对象仍以场景文件中的值为准。
3. 未知组件和未知属性按 `docs/docs/执行包/场景文件描述.md` 约定原样保留。
4. `sceneDigest` 对收到的完整原始 JSON 做 JCS + SHA-256；`scene_sub_version` 是否缺失本身会影响摘要。
5. 机器人任务只从当前 SceneConfig 生成计划和 `commands.json`，本表不代表 Control 已执行。
