# Scene / 只读资产迁移进度

## 2026-10-09 最新状态（取代下方阶段记录）

运行链路与全部旧测试已迁移至唯一组件协议；上一轮全量 418 passed。
已补充直接 SceneManager 非法历史编号回归，最终数量以 implementation_report 为准。
仓库外 wheel smoke 已通过，真实 Qwen 新协议 demo 6/6 通过。
21 个资产离线复核后 SHA256 仍为下方原始值，原包零修改。
README/contracts/manual_testing/demo 文档已同步，不再将旧 flat/颜色字段称为现行协议。
正在完成最终打包与远程 CI；当前正式平台资源仍待部署方提供，未进行 Control/渲染联调。
最终证据以 docs/implementation_report.md 为准。

## 以下是保留的早期迁移记录，不代表当前状态

目标文件：robot_agent_brain_scene_asset_migration_plan_v3_exact_protocol.md。
用户实际提供的 fixture：`/home/cscvlab/下载/scene_example (2).json`。
本文件不是最终交付报告。迁移尚未闭环，当前工作区不是可交付版本。

## 已实现并专项验证

- `contracts/scene.py` 已替换为团队组件协议；暂存 `shared_scene.py` 已移除。
  顶层、对象、已知组件严格校验；未知组件 JSON-safe 原样保存。
  Codec 仅接受新协议，不做 flat runtime 自动转换，也不为结构往返解析样例占位资源。
- `SceneIndex`、`SceneGraph` 支持完整仿射父链、world/local 逆变换，
  parent=0 忠实保留。无法表示为局部 TRS 的剪切编辑明确拒绝。
- component-aware Patch/SceneManager 原子提交；保持其他组件，
  实际 Transform 变化清除 support，相同 Transform 不误删 support。
  失败不增加版本、不消耗编号；删除再增加同编号被拒绝。
- Grounding/Selection/Query 改为 Scene Semantic 事实和世界坐标；
  ResolvedSelectionRelation 将 concrete reference 与 semantic string 分离。
  on 使用 Semantic.support，inside 缺少协议证据明确报错；
  不从显示名、MeshRenderer 猜颜色，不恢复实例 alias/color 旧属性。
- GroundedTask、Commands、Feedback、Camera 实例框、查询结果、Dialogue 的 concrete IDs
  已迁到整数；CommandPlacementTarget 独立验证 concrete reference。
  Commands.robot 从应用 BrainConfig.robot 经 Pipeline 注入，不从 Scene 名称推测。
- SessionState 保存 seen_scene_object_ids / next_scene_object_id；平台确认成功才提交历史。
  保存恢复后仍禁止复用删除编号；修复 holding/focus ID=0 的真假值判断。
  对话 marker 只包含 semantic name，“另一个”的 concrete exclusion 在 Python 绑定，
  不再由 Qwen 输出场景编号。
- AssetLibraryPort / LocalAssetLibraryAdapter 只读 index/metadata/cache/可选 category sidecar；
  library ref 只在 Adapter 解析；无 category sidecar 时 category-only 明确失败。
- 离线 build/validate 脚本扫描 OBJ 完整 local min/max，输出到资产树外。
  config 中保存 21 个真实资产的实测 cache、分类和语义 alias。
- Geometry / SpatialFactResolver 改为完整 local AABB + world affine matrix，
  不使用 center-origin 假设。MotionScaleResolver 经 MetadataRef resolve 读取模型长度。
  已用真实实测 cache 中 apple(1)、底部原点模型(4)、XY 偏心工具(16) 验证支撑和世界 bounds。

最新专项测试命令：

```bash
python -m pytest -q \
  brain_tests/test_shared_scene_contract.py \
  brain_tests/test_asset_library.py \
  brain_tests/test_component_runtime.py \
  brain_tests/test_component_session.py \
  brain_tests/test_component_geometry.py
```

2026-10-08 当前结果：上述 65 项、test_library_config.py 的 6 项、
test_component_bootstrap.py 的 9 项、test_component_editor.py 的 7 项、
test_component_demo_application.py 的 3 项，共 90 项专项通过。
原 test_recipe_state / test_skill_planning_context / test_skill_planning_qwen /
test_skill_planner_router 已迁移数值编号，65 项通过，没有改变第二次模型的语义边界。
最新 full pytest 实测：406 passed、12 failed、0 errors（2026-10-09）。
已继续迁移 pipeline、pipeline_stages、pairwise_collections、motion_and_commands、
scene_domain、edit_prospective_layout、scene_contracts；集合前瞻几何检查与
腾空位置复用、单次理解调用、距离证据优先级、场景/命令边界均保留。
已完成原 query_scene_continuity、same_turn_understanding、scene_edit_contract、
layout_and_numeric_edges、configuration_geometry 的迁移。支撑只用 Semantic.support，
颜色缺证据失败，默认桌面仅在明确提供 defaults 时启用且仍验证几何。
父链/旋转/完整 AABB/支撑容差/多轮焦点/同轮 add→move 原验收语义保留。
test_scene_bootstrap、test_bootstrap_scene_edits、test_config_assets、test_query_focus
已迁移到组件/数值 ID；移除测试对旧 color 属性的依赖，新增颜色证据缺失应报错而非
返回零匹配的验证。component_fixtures.py 只构造新协议，不做旧格式运行时兼容。
已迁移原 scene_file_codec、catalog_alias_selection、session_lifecycle、session_store、
scene_atomicity、application_artifacts、artifact_writer、export_roundtrip、plan_validator
测试，保留原失败原子性/生命周期/命令参数验证，并按新协议更新不再成立的
“加载强制解析资源”和“实例 aliases 属性”预期。
正式库配置已接入 BrainConfig.load_assets 和 Application；新增相对配置示例
config/local_asset_library.json。恢复 Scene 不再依赖旧 asset_id，也不为语义查询强行
解析 MetadataRef。新场景 ID 入口改用 JS-safe 53 位整数。
git diff --check 通过。
专项覆盖不等于 full pytest，更不等于真实 Qwen / Control 联调。

## 资产只读证据

资产树生成和复核前后 SHA256：
`7dc29ed669cbb94c2a3ff8a3c128bf37bc8ee2f6ed0250528b5fdfaf28866e01`。
builder/validator 报告 21 个有效资产，runtime 不扫描 OBJ。
`model/grasp_objects/` 已加入 gitignore，保留本机原文件，不打包/推送原资产。
用户的压缩包也不得顺带提交。

## 当前仍未闭环的工作

1. demo assets adapter 与 Editor 全局 aliases 注入已完成。
   resources/assets.json 保留为 metadata-only demo，并显式加入稳定 demo library IDs
   和完整 AABB；不再靠 center-origin 推导。DemoAssetLibrary 只接受
   $DEMO_LIBRARY/ 引用，正式库配置不继承 demo 平台。demo_platform.json 中
   demo_joint 明确是测试元数据，不是真实 UR5e 参数。
   应用级回放测试已验证 bootstrap→commands artifact→add→restart→query。
   没有运行机器人或真实 Qwen。
   正式库 config/application、Bootstrap aliases 注入已完成。
   Bootstrap 要求桌子/机器人 MetadataRef 可 resolve，且 RobotDriver 配置完整；
   示例配置保留 null，不编造库引用。当前抓取资产库不包含这些平台资源，
   正式资源的提供/适配仍需完成，不能拿测试 fixture 冒充正式资源。
2. Bootstrap/Layout 已迁移：组件输出、整数编号、偏心 AABB 落桌/间距、独立
   ResolvedSelectionRelation、可重复数量布局。已通过显式测试资源和真实工具
   实测 cache 验证；这不是实际平台资源联调。
   Editor 已重写为组件补丁，接入 Session allocator；新增/删除/世界移动/
   局部轴移动/旋转/相对布局均不写旧 flat 字段。新增落桌用完整 AABB；
   Transform 写回调用 local_from_world，支撑只写 Semantic.support。
   新增测试验证父链、未知组件保留、用户 fixture 的 Camera/Light/Driver 精确保留、
   历史编号、同轮 add→move、后续失败原子性和成组移动。
   旧任意 properties 更新明确拒绝，不偷偷扩共享协议。
   仍需迁移原有编辑测试并扩充旋转/相对新增/应用端多轮回归，不能以专项替代全量验收。
3. 应用入口生成 numeric scene_id、上传检查、持久化配置指纹、artifact/schema 导出。
4. 清查其他 concrete-ID 注解、假值判断和旧资产 API 残留，补 Session/平台全链路验收。
5. 迁移旧测试、Replay、demo 和 wheel smoke；不保留永久旧 flat runtime 分支。
   当前 full pytest 实际运行未通过：大量旧夹具仍构造 flat Scene，且未迁移的入口不兼容。
   不删除、不批量 skip 原测试以伪造通过。
6. 更新 README/contracts/manual_testing/acceptance_matrix/implementation_report，
   最终 full pytest、独立 wheel smoke、Python 3.11/3.12 GitHub CI 都需实际验证。
7. 新协议真实 Qwen 尚未测试，Simulation/Frontend/Control 尚未联调；
   最终提交 SHA、CI 链接和剩余限制必须在完成后据实报告。

## 用户待提供的信息（不阻止其余迁移）

已异步询问桌子与 UR5e 的正式 MetadataRef.path、相关几何元数据和 joint 配置位置。
共享抓取库没有桌子/机器人；fixture 中 `<id>` 只能往返保留，不能执行 resolve。
回复前不编造库编号，不改原资产库。

## 保留的既有改动

进入迁移时 README、两个 prompt 和 demo/ 是上一轮真实 Qwen 样例的未提交改动，均已保留。
本轮尚未提交/推送；不会将未完成迁移推送为可用版本。目标仍 active。
