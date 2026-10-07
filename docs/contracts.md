# Brain 原生协议与迁移

## Optional Atomic Skill Planner（本轮新增）

冻结的 Query、SceneEditPlan、CommandsFile 2.0 wire 不变。第二阶段仅组合原子技能，
不是第二次任务理解，也不执行物理仿真。完整路径为 Grounding → TaskExpander →
MotionScaleResolver → SkillPlannerRouter → PlanValidator → CommandExporter。
Exporter 保留同一 PlanValidator 门禁。

`recipe` 默认；`qwen` 对合法 robot_task 调用第二模型；`auto` 只在 supports=false 时调用。
RecipePlanner.supports 检查所有操作属于 locate/move/grasp/release/pick_and_place/press/
open/close。Search 虽属于 TaskType，但不属于 SkillName/Registry，提前 capability_unsupported，
没有新增 Search wire、generic/other TaskType 或异常 fallback。

### 第二次输入：SkillPlanningRequest / PlannerContext

| 字段 | 唯一允许的数据 |
|---|---|
| instruction | 原始用户任务文本，不拼接物理场景快照 |
| semantic_summary | Python 按操作顺序确定性生成的语义摘要 |
| operations[] | id、type、semantic_intent、role_bindings、valid_roles、depends_on、placement_target、motion_direction |
| role_bindings | source/destination/target/reference → 第一阶段语义 entity ID 或 null |
| entities[] | id、name、category（仅相关语义实体） |
| goals[] | goal relation 的 relation、subject、reference |
| initial_state | held_entity（语义 ID 或 null）、gripper_occupied |
| skill_catalog | 当前 Registry 的可见技能摘要；HTTP 中键名为 skills |

所有上下文模型 extra=forbid；不 dump GroundedTask，不发送 scene_object_id、asset_id、
Transform、XYZ、quaternion、scale、bbox、mesh、distance_m、关节、IK、碰撞、路径或轨迹。
集合先展开为语义 a__01/a__02 等，不用实例 ID 替代语义 ID。夹爪持有任务外对象时
held_entity=null 且 gripper_occupied=true；null 不是空夹爪证明。
原始 instruction 可能包含用户主动写入的距离文字，但无 Python 解析后的物理字段。

### 第二次输出：SkillPlanLLMOutput

```json
{"operations":[{"id":"op-1","intent":"将 source 放到 destination","steps":[
  {"skill":"locate","target_role":"source"},
  {"skill":"move","target_role":"source","region":"grasp_region"},
  {"skill":"grasp","target_role":"source"},
  {"skill":"locate","target_role":"destination"},
  {"skill":"move","target_role":"destination","reference_role":"source","region":"placement_region"},
  {"skill":"release","target_role":"source","reference_role":"destination","region":"placement_region"}
]}]}
```

顶层只允许 operations。每项只允许 id、intent（1–300 字符）、steps（至少一个）。
每步只允许 skill（SkillName 枚举）、target_role/reference_role（四种角色或 null）、region。
所有层级拒绝额外字段；operation ID 唯一，ID 列表和顺序必须与输入完全相同。
enrich_skill_plan 再检查当前 operation 的 valid_roles、必需 target、注册且可见的 skill、
allowed_regions，严格映射回 TaskEntity 并生成 step-1、step-2…，不静默修复 role。
模型不生成 entity/object、step_id/command_id、XYZ、distance_m、依赖或物理动作参数。

Registry 的七项：locate、move、grasp、release、press、pull、push；每项有 signature、
description、requires_target、allowed_regions、preconditions、effects、planner_visible。
move 可用 grasp_region/placement_region/button_surface；release 可用 placement_region；
其他 skill 不接受 region。目录只描述技能，不内嵌高层 recipe，不依赖 Control 源码。

### HTTP、校验和失败边界

第二次仍 POST 同一 `/chat/completions`，model/key/timeout 共用；temperature=0。
默认 response_format={type:json_schema,json_schema:{name:skill_planning,strict:true,schema:…}}。
user message 是 context 各字段加 skills 的 JSON，system message 来自包内 skill_planning_v2.txt。
max_completion_tokens=min(配置上限,384+128×max(operation_count,1))，默认上限1024，范围128–4096。
显式 structured_output=off 仅关闭服务端 Schema 请求，本地仍严格校验。记录 stage、usage、
finish_reason、耗时、原始文本与 JSON；失败不 retry/fallback 为另一个 planner。

PlanValidator 从固定步数/Counter 改为状态与效果：located、当前 reached、held、
pressed/pulled/pushed/directional_move/placement_release。保留 operation 覆盖/顺序/依赖、
step ID 唯一、真实实例/场景版本、当前角色、接近/接触、握持、放置及最终状态检查。
重复 locate 和合法 approach 可通过；重复 displacement 会重复实际距离，仍拒绝。
初始已持有 source 的放置允许省略抓取前缀；持有其他对象不能抓新对象。
语义校验通过不等于物理可执行或抓取成功。

失败不发布 commands、不链接上一轮 commands、不改已有场景、不猜执行后持物状态。
无场景首轮 robot_task 先对候选场景规划，通过后才调用平台加载初始场景；失败不加载。
平台已确认加载后的磁盘失败仍如实报告 committed，不能假装撤销外部提交。
Query/SceneEdit 原有提交协议保持不变。executed 始终 false。

报告 metrics 增加 skill_planning_calls、planner_requested、planner_used；保留
understanding_calls、vision_calls、model_calls。计数包含失败尝试；缺 provider 是零次。
Replay 不实现 plan，qwen 模式明确 provider_missing；MockTransport 只用于工程验收。
配置指纹包含 planner、token 上限、skill prompt 和 catalog 的 SHA256（统一 JSON 编码后散列）。
debug 保存 context/catalog/raw/normalized/validation 与调用日志；未完成阶段不伪造 normalized。

## 边界

本版输出 Brain 原生 SceneConfig、ScenePatch、CommandsFile，不是 MJCF/XML。
团队草案的 components 场景和 taskStep 文件还没有完成适配；文件名相似不表示兼容。
SceneFileCodec 是未来转换边界，当前拒绝未知版本、损坏 JSON 和 components 格式。
LocalScenePlatform 只维护元数据并确认版本，不渲染；capture 明确不支持。

## ID、单位和版本

- SceneConfig 的 `scene_id` 标识场景；`scene_version` 是确认的非负版本。
- `scene_object_id` 是稳定实例 ID；`asset_id` 对应资产元数据，不是可随意虚构的 mesh。
- 删除后的 ID 进入 retired_object_ids，不能复活。语义实体 ID 不等于场景实例 ID。
- Transform 位置单位米，四元数顺序 xyzw，scale 为正比例；编辑旋转角度为度。
- 世界坐标约定 x 右、y 前、z 上；桌面“左上”使用 x-/y+，不是 z+。
- 机器人计划采用模型轴尺寸与实例 scale 将 small/medium/large 转换成 10%/50%/200%。
- 用户精确距离优先；没有数值也没有幅度依据则澄清，不信任模型猜出的米数。

一次正式编辑 Patch 只增加一个版本。初始场景不实现机器人目标；scene_query 和
commands 导出不改变版本/位姿。执行后必须有外部确认快照才能恢复几何可信状态。

## SceneQueryIntent：单一查询契约

Query 唯一输入为 `query_type + entities + relations + target`。`query_type` 为
count/existence/position/state，entities 至少一个，target 必须引用实体 ID；relations
仅允许 selection，subject/reference 必须引用已有实体。例：

```json
{"query_type":"count","entities":[{"entity_id":"apple","semantic_name":"apple","category":"fruit","color":"red"}],"relations":[],"target":"apple"}
```

REMOVED（不提供兼容转换）：查询顶层 semantic_name、category、referent_scene_object_id。
旧 JSON 明确报 extra_forbidden，不会静默转换。TaskEntity 内的名称/类别字段继续存在。
QueryResult 也不再携带冗余 semantic_name；结果以 object_ids 为准。
Query、Robot Grounding、Scene Edit 复用 SemanticEntitySelector 的名称、别名、类别别名、
颜色、排除、绑定和 selection relation 规则。count/existence 可返回 0/N；机器人唯一性
和集合数量仍在 Grounder 校验；candidate_pool 在关系筛选前检查数量。

其中 AssetCatalog.aliases 是全局名称映射（例如 苹果→apple），请求名称和场景名称均先
canonicalize；SceneObject.properties.aliases 则是实例级附加名称。无需在上传场景中复制
资产别名，导入和查询不会为此改写场景。未声明的名称不会仅因同类别而匹配。

REMOVED：dialogue_scene_object_id marker 和 Provider 单对象 referent 注入。
`[dialogue_ref=apple]` 只提供语义名；`[dialogue_ref_set=apple]` 必须对应
dialogue_ref_set=true、quantity_mode=all、all_available=true。实际实例集合由 Python
DialogueState.bindings 注入。集合后的单数“它”返回 dialogue_reference_ambiguous。

## Scene Edit：只接受 SceneEditPlan

BrainTurn.scene_edit 和 TaskParseOutput.scene_edit 现在都只有 `SceneEditPlan | None`。
一次新增也必须采用 entities/relations/operations，不再接受直接的 SceneEditIntent payload：

```json
{"entities":[{"entity_id":"banana","semantic_name":"banana","category":"fruit"}],"relations":[],"operations":[{"operation":"add","target":"banana"}]}
```

SceneEditIntent 类名保留，但它只表示 operations 数组内的一条操作；target 必填，
target/reference 必须引用本计划实体。REMOVED：操作中的 semantic_name/category/count。
数量、颜色、别名和指代放在 TaskEntity 中。旧格式明确拒绝，无兼容转换。
SceneEditor.edit/edit_result 只接收计划；目标与参照统一经过 SceneObjectSelector →
SceneGrounder → SemanticEntitySelector。删除 `_matches_name` 和 Bootstrapper 的旧编辑适配。
新增资产仍由 AssetResolver 选择；同轮新增对象的稳定绑定、集合数量和单版本原子提交保留。

## 布局高度与支撑事实

left_of/right_of/front_of/behind 保留已有对象 Z；新增对象先确定可验证支撑面，
按自身几何底部计算高度，再设置 XY。支撑未知时只允许显式 defaults 桌面回退，
否则 scene_edit_support_unknown。free_space 不再是 above 的别名。

SpatialFactResolver 使用 AABB（优先）或明确 center_origin_assets 元数据，考虑 scale
和 xyzw 四元数；只推导 category=surface 的水平、朝上的支撑面，允许任意 yaw。
这是包围盒语义事实，不是物理接触检测。倾斜面、未知原点不推断支撑。
布局配置 support_contact_tolerance_m 默认为 0.001 米，可配置，不作为补偿位移。

UPDATE_TRANSFORM 先清除 support/support_relation/container_membership/support_evaluated，
Editor 在 prospective scene 中校验后追加 UPDATE_PROPERTY，整个 patch 只提交一个版本。
`support_evaluated=true` 表示本轮完成受支持几何范围内的支撑检查；无可证明支撑时
on 查询不匹配，但不写入伪造的 support。缺少可检查几何仍保留 unknown 行为。
没有容器内部几何，永不自动重建 container_membership。

## CommandsFile 2.0 wire

顶层包含 schema_version、request_id、scene_id、scene_version、robot、operations、commands。
每条 command 通过 operation_id 引用高层目标，通过 source_skill_step_id 引用技能步骤。
目标与参照都是具体实例，不能输出集合、XYZ、IK 或轨迹。

MOVE 有互斥的两种 wire 形式：region 模式，或 motion_direction + distance_m 模式。
canonical_commands 排除 null 字段，再执行模型和公开 JSON Schema 校验。
最终文件必须通过 Schema；Python 对象通过不等于任意序列化都合法。
PlanValidator 另查操作覆盖、依赖、角色和单夹爪握持前置条件，不替代物理可执行性验证。

```bash
robot-brain schemas --output-dir var/schemas
```

Schema 导出不需要模型服务。当前包含 commands、scene_config、run_report。

## Export、dispatch 与 feedback

`BrainSession.run_task` / `process_turn` 导出计划，只更新 last_exported_request，不设置 pending。
这是对旧行为的明确迁移：过去依赖自动 pending 的客户端必须显式发送并标记。
Application 的 `mark_dispatched` 要求本会话导出的、与已发布文件完全一致、版本匹配的命令。
重复 request、已有 pending、暂停/关闭/unknown 状态都会拒绝。

ExecutionFeedback 保持 request_id、status、commands 和 holding_object 结构。
status 为 success/failed/partial；command_id 必须属于当前 pending 且不重复；成功要求
完整的成功集合。unknown/stale feedback 不会修改状态。

```python
from robot_agent_brain.contracts.commands import CommandsFile, ExecutionFeedback
from robot_agent_brain.contracts.scene import SceneConfig

# app 已配置；以下变量来自执行层，不是根据 Brain 的计划伪造。
commands = CommandsFile.model_validate(commands_payload)
app.mark_dispatched(session_id, commands)
feedback = ExecutionFeedback.model_validate(feedback_payload)
confirmed = SceneConfig.model_validate(executor_scene_payload)
app.apply_execution_feedback(session_id, feedback,
    confirmed_scene=confirmed, feedback_source="external")
```

confirmed_scene 必须同一 scene_id、更新的版本，holding 对象必须存在。
未提供快照时，即使 failed/partial 也标为 unknown，不假设“失败所以没移动”。
模拟夹具必须显式使用 simulated。Session 内存 API 仍可用于直接集成，但若需要自动
持久化和本地锁，应调用 Application 包装接口。

## 状态与产物

BrainTurn.status 是 accepted/clarification_required/unsupported_task，表示语义状态。
BrainRunReport.run_status 是 success/blocked/failed，表示本轮交付状态，不能混用。
`executed` 固定 false；scene_commit_status 区分 unchanged/committed/unknown。
scene_source 区分 generated/uploaded/session/none。

会话保存严格 JSON，不 pickle provider/动态对象/API key。恢复保留版本、焦点、
pause/close、sync 和真实 pending。配置指纹也会保存；恢复时配置变化写入
report.assumptions，不自动重建场景。配置改变或未完成执行的恢复仍需部署方注意。
每轮目录暂存后发布，不覆盖旧请求，不修改用户原始场景。
平台确认和磁盘不是同一事务；写盘失败不能声称回滚平台，也不能保证磁盘恢复。
