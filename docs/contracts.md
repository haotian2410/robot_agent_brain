# Brain 原生协议与迁移

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
