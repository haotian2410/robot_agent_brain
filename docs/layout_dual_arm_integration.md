# Scene Layout 与双臂逻辑 DAG

本版本把“摆放/排列/布置”和普通 `scene_edit`、`robot_task` 分开：

1. Qwen 只产生 `ArrangementSpec`，不产生世界坐标、实例 ID 或碰撞结论。
2. `layout_planner.py` 将固定 pattern 转成 `normalized_region_2d` 的 `LayoutPlan`。
3. `LayoutResolver` 在事务边界绑定场景实例；支撑、几何和最终提交仍由 SceneEditor/Gateway 负责。
4. 混合任务按场景阶段和机器人阶段建立 `CompositeTurnRecord`，阶段失败时不重放已提交步骤。

## 双臂4.1序列协议

本节按双模式时序重构方案更新，取代旧4.0共享调度约束。
RobotProfile.commands_version必须为4.1，可信ControlSkillContract必须显式声明支持4.1。
旧3.0/4.0不能静默升级或flatten；旧v3模型仅供历史读取，planner/dispatch已退役。

Brain生成每臂技能序列，同臂相邻命令结构串接；跨臂依赖只转换Operation.depends_on，
从前置操作末条连接后置操作首条。不因同目的地、同物体或持物状态生成跨臂依赖。
输出没有execution_policy、resource_groups、hold_constraints、sync_groups。
Control负责感知、运行时等待、持物、IK、碰撞、轨迹和执行。

分臂按operation分配，显式arm优先；可信当前画面的实例身份可供模型分配未指定操作。
不以画面左右猜测机械臂标签；缺证据时沿用已配置且可审计的默认/均衡规则。
所有操作必须完整覆盖，模型不能修改对象、显式arm和输入顺序。

单臂/双臂技能prompt读取同一Control skill.md来源，使用各自输出包装。
双臂草稿只含operation_id和steps；Python生成命令ID、场景绑定和序列。
skill注册、参数schema、对象角色绑定、版本和合同revision仍校验。

首轮接受后RobotModeLock锁定mode/profile，保存恢复保持；双臂本轮仅左臂动作仍输出4.1。
后续不同mode返回robot_mode_locked，不同profile返回robot_setup_change_after_first_turn_unsupported。
布局复合按layout提交→新场景grounding→模式对应规划，机器人失败保留已提交布局。

目前真实Control 4.1下发适配尚未完成，mark_dispatched拒绝此版本；
规划和离线测试通过不代表真实双臂执行通过。

## Prompt 与 Schema

- `models/prompt_templates/layout_planning_v1.txt`
- `models/prompt_templates/arm_assignment_v1.txt`
- `models/prompt_templates/atomic_multi_arm_rules_v1.txt`
- `schemas/arrangement_spec.schema.json`
- `schemas/commands_dag_v4.schema.json`

布局协议的 compact U 字段为 `at`，其嵌套字段复用版本化字段注册表；full 协议仍可回放。非法字段不会被删除或改写。
当前Compact机器人操作必须显式输出`dp`，无依赖为`[]`；该字段不能省略。
Full Python模型仍允许其默认空数组。历史Compact原始响应若缺dp不能直接作为当前
实时响应解析；历史Full/canonical内容可通过encode按声明默认值转换为当前Compact。
这项语法收紧不补语义依赖，模型遗漏明确“完成后再”的两操作依赖时仍拒绝。

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
# Historical same-arm constraints (retired)

`same_arm_group` and Compact `sg` are retired from current task protocols.
Brain does not propagate same-object or held-object locks across operations.
Current assignment uses explicit arm selection and registered deployment context;
only same-arm sequence and user-explicit dependencies affect 4.1 ordering.
Old documents describing shared locks are historical-only.

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
# 应用层规划合同接入（2026-11-27整改）

可信调用方可向 `BrainApplication` 或 `AgentService` 注入 `control_skill_contract`，
或由运维配置 `control_skill_contract_path` 加载合同快照。模型输出、skill.md存在、
RobotProfile或测试fixture不能作为Control授权。合同必须包含真实注册技能、参数、
对象角色和revision；双臂规划还要求可信operation_semantics明确技能语义。
配置文件revision变化使旧计划失效；相同revision不同内容拒绝。

4.1规划与执行独立：health/brainCapabilities分别返回planning_protocols、
execution_protocols、dual_planning_ready、dual_execution_ready和合同revision。
当前4.1只规划，mark_dispatched保持关闭，不能交给2.0 adapter。
候选部署不等于模式锁；布局/查询/编辑不锁模式。只有显式setup接受或机器人计划
成功接受才决定模式。详见 `brain_4_1_followup_acceptance.md`。
