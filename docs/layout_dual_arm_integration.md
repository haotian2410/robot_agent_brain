# Scene Layout 与双臂逻辑 DAG

本版本把“摆放/排列/布置”和普通 `scene_edit`、`robot_task` 分开：

1. Qwen 只产生 `ArrangementSpec`，不产生世界坐标、实例 ID 或碰撞结论。
2. `layout_planner.py` 将固定 pattern 转成 `normalized_region_2d` 的 `LayoutPlan`。
3. `LayoutResolver` 在事务边界绑定场景实例；支撑、几何和最终提交仍由 SceneEditor/Gateway 负责。
4. 混合任务按场景阶段和机器人阶段建立 `CompositeTurnRecord`，阶段失败时不重放已提交步骤。

`CommandsFileV4` 是双臂逻辑依赖 DAG。Brain 校验 command/operation ID、依赖环、同臂顺序、资源、同步和持物事件引用；IK、碰撞、感知、轨迹和执行全部交给控制端。现有单臂 Atomic v2 和显式双臂 v3 兼容路径不变，生产双臂能力仍由发布策略控制。

## v4 规划与持物事件契约

显式 `RobotProfile.commands_version="4.0"` 可进入 v4 规划器；必须由可信适配器提供
`ControlSkillContract`，且包含 `supported_protocols=["4.0"]`。模型不能自行声明控制能力。

合同在进入Recipe/Qwen技能规划之前校验：只支持v3的合同立即返回
`unsupported_protocol_version`，不先调用技能模型再拒绝。合同内所有注册技能必须
与顶层`expansion_level`一致（包括本次未使用的技能）；同步、资源、保持能力标志
必须是JSON布尔值，不能以字符串或0/1隐式启用。协议列表不允许空值或重复条目。
当前代码允许规划和导出，不代表现有 Control 已支持 v4 下发或执行结果回写。

v4 存在未锁定操作时，且 provider 提供 `assign_arms`，可进入视觉分臂阶段。
仅在当前画面包含两个机械臂和操作源对象的可信实例框时调用模型；机械臂左右身份由
当前 profile 的对象 ID 映射提供，不按画面左右猜测。过期场景 ID/version/sub-version、
未知实例或重复框身份会被拒绝。全部操作已显式锁定或已由持物状态锁定时跳过拍照和分臂模型。

分臂结果必须覆盖所有操作并保留锁定臂、同对象连续性、双臂要求和已有操作顺序。
非法输出不触发静默 fallback。模型明确 `insufficient_evidence` 或缺少可用视觉身份时，
沿用可审计的配置默认臂/双臂均衡规则；没有可用规则则澄清。规划 trace 区分
`explicit_arm`、`held_object`、`visual_assignment`、`configured_default_arm` 和
`deterministic_balanced_fallback`。视觉分配不是 IK 或可达性保证。

每个注册技能提供参数 Schema、`expansion_level` 和 `object_parameters`。后者说明参数对应
已绑定 source/destination/reference 的哪种角色，禁止模型更换实例。持物任务还要求注册
`holding_effect`，不能按名称猜测自定义技能的效果：

```json
{
  "object_parameters": {"object": "source_object_id"},
  "holding_effect": {"action": "acquire", "object_parameter": "object"}
}
```

`action=preserve/release` 不带 `object_parameter`。缺少效果声明时，持物链明确拒绝。
这些声明用于验证计划语义；计划里的预测持物状态绝不会写成运行时的实测状态。

输出 `hold_constraints` 中：

- `after_command_id` 指建立持物状态或完成持有方里程碑的命令；为空时依据已验证的输入持物状态。
- `until_command_id` 指另一只臂完成目标操作的最后一条命令。
- `region_object_id/region` 成对保留显式区域约束，实际空间判定由 Control 负责。

Python 在被约束操作开始前加入建立持物状态的依赖，在持有臂后续动作前加入结束事件依赖。
不生成 `wait/null` 技能，不删除用户原有依赖以消除环。`supports_hold=false`、缺少持物证据、
跨臂重复抓取同一持物对象、事件环等情况均停止导出。

## Prompt 与 Schema

- `models/prompt_templates/layout_planning_v1.txt`
- `models/prompt_templates/arm_assignment_v1.txt`
- `models/prompt_templates/atomic_multi_arm_rules_v1.txt`
- `schemas/arrangement_spec.schema.json`
- `schemas/commands_dag_v4.schema.json`

布局协议的 compact U 字段为 `at`，其嵌套字段复用版本化字段注册表；full 协议仍可回放。非法字段不会被删除或改写。

## 测试

```bash
PYTHONPATH=. conda run -n robot_agent_integ pytest -q
```

布局 pattern、计数、归一化 slot、DAG 环和未知依赖均有独立契约测试。
# Authorized automatic spacing

For line/grid/checker/alternating layouts, `spacing.mode=auto` together with
`spacing.auto=true` enables deterministic bounded spacing search. The first
candidate uses the largest rotated/scaled footprint extent plus requested
clearance; subsequent candidates increase this spacing by 10%, up to 48 trials.
Each trial starts from the unchanged input Scene and runs the existing support,
region, footprint and collision checks. Capacity/support/identity/asset errors
stop the search; only a collision permits another trial. This is a bounded
search, not proof that every mathematically possible layout was explored.

The search preserves exact object count, ordering, arrangement center, asset
scale and requested region. It never publishes intermediate trials. Successful
results record `layout_spacing_m`, `layout_spacing_search_attempts` and
`layout_spacing_search=authorized_auto`. Fixed center/edge spacing does not
adapt. Circle/ring/arc radii and free-path/scatter coordinates are not silently
changed by this search. Those patterns retain their existing validation.
# Relative layout regions

`region.kind=relative` requires `surface_ref`, `anchor_ref` and one of
`left_half/right_half/front_half/back_half`. Unlike `surface_region`, these
directions clip the support surface at the anchor's world AABB boundary plus
minimum clearance, rather than at the table midpoint. This accounts for the
anchor's world transform and scale. Every generated object's full footprint
must remain inside this clipped region and on the support. Requested width/depth
must fit; insufficient capacity refuses the entire candidate. `center`/`any`
with `relative` is an incomplete direction and fails validation.

This defines world-tabletop X/Y directions, not image-relative directions or
coordinates in the anchor's local frame. `around`/`near` retain their separate
anchor-centered behavior. It does not imply containment inside the anchor.
# Same-arm constraints across objects

Robot operations may carry `same_arm_group` (Compact U key `sg`). The field is
optional and defaults to absent/null, preserving old recorded tasks. Group labels
are semantic identifiers, not arm IDs or scheduler/resource names. Operations
sharing a label must use the same arm; repeated actors connect groups transitively.
Explicit arm and verified held-object locks propagate through the whole component.
Contradictory ownership fails before model planning (`arm_assignment_same_arm_conflict`).

The assignment request includes these components in `same_arm_groups`; a model
cannot split them. Configured or balanced fallback also locks whole components,
and the audit marks inherited locks as `same_arm_constraint`. The task expander
preserves the label on expanded instances. Once resolved, normal same-arm DAG
serialization applies; no fake barrier/skill is emitted. `both_required` remains
an independent constraint and is rejected when both requirements cannot be met.
# Free-path placement bounds

For custom/text/scatter slots, normalized coordinates map to the common safe
object-origin rectangle, not the raw support rectangle. The resolver subtracts
user margins and the union of rotated/scaled member footprints. Asymmetric OLS
local bounds produce asymmetric insets; no mesh origin is assumed to be centered.
Mixed assets share the same map, preserving the slot pattern rather than moving
individual points independently. An empty available rectangle is a capacity
failure and does not shrink assets or reduce count.

For follow-pattern orientation, a conservative yaw-independent footprint bound
is established before computing the tangent yaw in the fitted rectangle. Actual
world bounds, support and collision checks still run afterwards. The conservative
fit can reject some tightly packed feasible layouts; it never relaxes validation.
# Live layout understanding smoke

Run `python scripts/smoke_layout_understanding.py --config config/webeditor.json
--output-dir var/layout-dual-audit/<new-directory>` in the Brain environment.
This loads the configured OLS snapshot and uses production Compact U routing,
but never submits a Scene, creates a browser session or calls Control. Evidence
includes raw and canonical payloads, actual request/schema and all call timings.
The automatic oracle checks route, pattern kind and count only; inspect the
remaining parameters before claiming full semantic or geometry acceptance.

Compact layout output requires explicit items/spacing modes. Center/edge spacing
requires a non-null positive value; automatic spacing requires `auto=true`;
sequence items require a non-empty sequence. Mode defaults are not omitted by
the encoder. Validation happens before lossless field expansion; the codec does
not select an arbitrary union branch or infer a missing mode. Full historical
parsing continues to use its existing defaults and validation.
# Pattern-specific layout parameters

## Deployment-registered fonts

Text layout requires the optional `layout` dependency (`pip install -e '.[layout]'`)
and an explicitly registered, licensed font. Brain does not download fonts or
bundle a system font implicitly. On Ubuntu, an administrator may install the
distribution package `fonts-dejavu-core` and register its Latin font in the
deployment JSON:

```json
{
  "layout_fonts": {
    "default": "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
  }
}
```

Merge this field into the existing configuration; do not replace the entire
configuration with this fragment. Relative font paths are resolved against the
configuration file's directory. Model output names a registry key such as
`default`, never a filesystem path. DejaVu is an example for Latin acceptance
tests, not a promise of Chinese glyph coverage. Register a separately licensed
font with appropriate coverage for other scripts; missing glyphs are rejected,
not silently substituted. Preserve the font's license with deployment assets.

An empty registry produces `scene_layout_font_unregistered`; a missing/unreadable
file produces `scene_layout_font_unavailable`; an invalid font header produces
`scene_layout_font_invalid`; unsupported glyphs produce
`scene_layout_font_glyph_missing`. These are not successful layouts. No layout
Scene is committed on these failures. Fonts are read into a per-request snapshot;
the SHA256 in `font-outline-v1:<hash>` identifies the exact bytes sampled, even
when the registered file is concurrently replaced. Record this revision with
the layout evidence when upgrading fonts.

Sampling produces normalized outline slots, not world coordinates or an
arbitrary letter-shaped point list from Qwen. Exact requested quantity is
preserved; dense outlines may still fail actual geometry checks. Do not shrink
objects or reduce quantity to make text fit without explicit authorization.
Text slots map isotropically into the largest square inside the footprint-safe
origin region. Rectangular surfaces do not stretch glyphs; custom paths and
scatter retain their region-relative mapping. A former layout that fit only
because its glyph was stretched may now correctly fail collision checks.

Run `python -m pytest -q brain_tests/test_text_layout.py` after registration.
These tests cover planner/resolver behavior; a real browser letter-layout test
is still required separately and must not be inferred from unit-test success.

## Field policy

`PATTERN_FIELDS` and `PATTERN_REQUIRED` in `contracts/arrangement.py` define one
parameter policy for canonical validation and Compact grammar generation.
Line/alternating use axis; grid/checker use rows/cols/order/axis; circle uses
radius/order; ring uses inner/outer radii/order; arc uses radius/span/order;
text uses text/font/path; custom uses a path or description. Description is
allowed for all patterns as user intent evidence.

Grid may omit both rows and cols when a total count is supplied. Python chooses
cols=ceil(sqrt(count)), rows=ceil(count/cols), emits only the requested number of
slots, and does not instantiate objects in unused cells. Supplying only one
dimension derives the other; supplying both retains exact-count conflict checks.
Layout counts and dimensions require integer values, not booleans/strings or
coerced floating-point numbers. Automatic-count authorization is a strict boolean.
For `count_mode=at_least`, an explicit grid/checker rows×cols is the resolved
count if it meets the requested lower bound (maximum 1000). Single-asset or
cyclic checker assignments expand deterministically; inconsistent explicit
per-asset totals are rejected rather than guessing which asset to add. Candidate
assumptions record requested and resolved counts. This is explicit-dimension
resolution, not automatic geometric capacity search; `exact` remains unchanged.
Without explicit grid dimensions, `at_least` also preserves a fully specified
per-asset total or non-cycling sequence when its length meets the lower bound.
It never invents an extra asset to reach that bound; totals remain limited to
1000. The resolved-count reason is recorded as `explicit_assets_at_least`.

Automatic quantity requests can carry `items.min_count`/`items.max_count`
(Compact `ql`/`qu`). Both must be supplied together as strict integers in
1–1000, must contain `requested_count`, and require `count_mode=auto` plus
`auto_count=true`. Bounds are authorization, not a claim that any count fits.
Missing historical bounds are readable but do not authorize an invented range.
For create/append, bounded single-asset or cycling checker/alternating requests
now try counts by distance from the preferred count (smaller first on ties).
Only collision/capacity/workspace rejection advances to another count. Fixed
per-asset totals, literal sequences, rearrange and replace are not resized.
All trials stay private; reserve the full upper-bound ID range once, publish
only a successful candidate, and record the preferred/actual count and attempts.
An exhausted range preserves the original geometry error and commits no Scene.

Compact branches are closed objects: an irrelevant field is forbidden even when
null. Canonical Python rejects irrelevant nondefault values, while retaining
neutral defaults needed to round-trip complete serialized models. No invalid
model fields are removed after generation. Recorded pre-fix invalid patterns are
rejection fixtures, not silently accepted compatibility inputs.
# Replaying real U output against OLS geometry

`python scripts/audit_layout_candidates.py --config config/webeditor.json
--evidence-dir var/layout-dual-audit/<u-run> --output-dir var/layout-dual-audit/<new-run>`
loads the configured default Scene and replays each saved accepted layout into a
separate private candidate. It verifies the captured catalog revision, exact
creation count, one version increment and unchanged input. It saves before Scene,
candidate Scene, patch, digests and diagnostics without contacting Gateway or
Control. No browser publication or execution success is implied.

Diagnostics report the parameter actually used: `layout_spacing_m` for regular
line/grid patterns, `layout_radius_m` for circle/ring/arc, and
`layout_origin_bounds_xy_m` for free paths. A computed but unused spacing value
must not be presented as the physical inter-object distance on a circle/path.
# 应用层规划合同接入（2026-11-27）

已确认的控制适配器可以通过
`BrainApplication(config, provider=provider, control_skill_contract=advertised_contract)`
传入 `ControlSkillContract` 或同结构字典。应用在加载资产/创建模型前校验合同，
并深拷贝协议列表及嵌套技能Schema，避免调用方修改原字典影响已经创建的应用。
省略参数时保持原行为，不猜测任何v4支持。

应用任务入口在明确合同支持4.0时允许双臂**规划**，继续经过正常Session/Profile、
grounding和状态校验；没有合同仍返回`control_dual_arm_not_ready`，仅支持旧协议的
合同返回`unsupported_protocol_version`。`handle()`导出的Commands与保存Scene
必须具有相同digest，`executed=false`，不得因此改变持物状态或发送控制请求。

此入口仅提供**规划合同快照**，不等于执行协议协商成功，不改变 `/health` 声明，
也不解除 `mark_dispatched()` 对v4的拒绝。当前桥接实际消费端仍为2.0；
Web启动路径没有真实v4合同发现端点。集成方必须先提供实际注册技能、粒度和revision，
不能使用测试fixture作为生产声明。合同变更需创建新应用快照；正式动态协商及执行前
revision复核仍属于后续Control适配工作，不以该注入入口宣称已完成。
