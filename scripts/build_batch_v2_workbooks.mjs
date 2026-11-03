import fs from "node:fs/promises";
import path from "node:path";
import { FileBlob, SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const root = path.resolve(new URL("..", import.meta.url).pathname);
const outDir = path.join(root, "examples", "matrices");
const catalogPath = path.join(root, "config", "batch_asset_catalog.json");

const generatedHeaders = [
  "enabled","test_id","flow_id","parent_test_id","parent_flow_id","difficulty","stage","round_index","category","sample_count","branch_policy",
  "role_a","role_b","placement_1","placement_2","asset_a_key","asset_b_key","placement_1_key","placement_2_key","surface_1_key",
  "instruction_template","variants","scene_basis","coverage_tag","requires_visual","expected_outcome","expected_error_codes","expected_scene_change","assertion_profile","notes"
];
const knownHeaders = [
  "enabled","test_id","scene_name","difficulty","category","sample_count","instruction_template","variants","role_a","role_b","round_index",
  "scene_basis","coverage_tag","requires_visual","expected_outcome","expected_error_codes","expected_scene_change","assertion_profile","notes"
];

function row(headers, values) { return headers.map((h) => values[h] ?? ""); }

async function createWorkbook(filename, headers, rows, title, note) {
  const wb = Workbook.create();
  const ws = wb.worksheets.add("matrix");
  ws.showGridLines = false;
  ws.getRangeByIndexes(0, 0, 1, headers.length).values = [headers];
  ws.getRangeByIndexes(1, 0, rows.length, headers.length).values = rows;
  ws.freezePanes.freezeRows(1);
  const header = ws.getRangeByIndexes(0, 0, 1, headers.length);
  header.format = { fill: "#1F4E78", font: { bold: true, color: "#FFFFFF" }, wrapText: true, verticalAlignment: "center" };
  ws.getRangeByIndexes(1, 0, rows.length, headers.length).format = { wrapText: true, verticalAlignment: "center" };
  const readme = wb.worksheets.add("README");
  readme.getRange("A1:B3").values = [["矩阵", title], ["维护说明", note], ["规则", "variants 只改变表达；parent_test_id 继承前置场景；桌面是唯一操作空间。"]];
  readme.getRange("A1:A3").format = { fill: "#1F4E78", font: { bold: true, color: "#FFFFFF" } };
  readme.getUsedRange().format.autofitColumns();
  ws.getUsedRange().format.autofitColumns();
  ws.getUsedRange().format.autofitRows();
  await wb.recalculate();
  const inspection = await wb.inspect({ kind: "region", sheetId: "matrix", range: "A1:F12", maxChars: 5000 });
  console.log(`${filename} inspect`, inspection.ndjson ?? inspection);
  const preview = await wb.render({ sheetName: "matrix", autoCrop: "all", scale: 1, format: "png" });
  await fs.writeFile(path.join(outDir, filename.replace(/\.xlsx$/, ".png")), new Uint8Array(await preview.arrayBuffer()));
  const blob = await SpreadsheetFile.exportXlsx(wb);
  await blob.save(path.join(outDir, filename));
}

const catalog = JSON.parse(await fs.readFile(catalogPath, "utf8"));
const regular = catalog.assets.filter((x) => !x.passive_or_platform && !["table", "coffee_table"].includes(x.semantic_name));
const surfaces = catalog.assets.filter((x) => ["table", "coffee_table"].includes(x.semantic_name));
const table = surfaces.find((x) => x.semantic_name === "table") ?? surfaces[0];
const basket = catalog.assets.find((x) => x.semantic_name === "basket");
const tray = catalog.assets.find((x) => x.semantic_name === "tray");

const generated = [];
for (const [i, asset] of regular.entries()) {
  generated.push({ enabled: 1, test_id: `GEN-ADD-${String(i + 1).padStart(3, "0")}`, flow_id: `GEN-ADD-${String(i + 1).padStart(3, "0")}`, difficulty: "L1", stage: "generate", round_index: 1, category: "add_single", sample_count: 4, branch_policy: "seed_parent", asset_a_key: asset.asset_key, surface_1_key: table?.asset_key, instruction_template: "增加一个{object_a}", variants: `增加一个{object_a}|在桌子上增加一个{object_a}|生成一个{object_a}`, scene_basis: "empty_bootstrap", coverage_tag: `asset:${asset.asset_key}`, expected_outcome: "success", expected_scene_change: "changed", assertion_profile: "scene_added_once", notes: "每个普通模型至少覆盖一次；角色由 asset_a_key 固定。" });
}
for (const surface of surfaces.filter((x) => x.semantic_name === "coffee_table")) {
  generated.push({ enabled: 1, test_id: "GEN-SURFACE-COFFEE-TABLE", flow_id: "GEN-SURFACE-COFFEE-TABLE", difficulty: "L1", stage: "generate", round_index: 1, category: "surface_add", sample_count: 1, branch_policy: "seed_parent", asset_a_key: "apple_red", surface_1_key: surface.asset_key, instruction_template: "在{surface_1}上增加一个{object_a}", variants: "在茶几上增加一个苹果|在茶几中间放一个苹果", scene_basis: "empty_bootstrap", coverage_tag: `surface:${surface.asset_key}`, expected_outcome: "success", expected_scene_change: "changed", assertion_profile: "scene_added_once", notes: "支撑面模型覆盖。" });
}
const extra = [
  { id: "GEN-REGION-001", cat: "add_region", parent: "GEN-ADD-001", variants: "在桌子右上角生成一个{object_a}|在左下角放置一个{object_a}|在桌子中间加一个{object_a}|在东南角加一个{object_a}", expected: "success", assertion: "region_placement" },
  { id: "EDIT-ROT-001", cat: "rotate", parent: "GEN-ADD-001", variants: "把{object_a}旋转九十度|让{object_a}顺时针转90度|把{object_a}绕Z轴旋转四分之一圈", expected: "success", assertion: "transform_updated" },
  { id: "EDIT-COLOR-001", cat: "color", parent: "GEN-REGION-001", variants: "把{object_a}改成蓝色|把{object_a}换成蓝色|把{object_a}渲染成蓝色|把{object_a}设置为#0000FF", expected: "success", assertion: "color_override_applied" },
  { id: "EDIT-MOVE-001", cat: "move_direction", parent: "EDIT-COLOR-001", variants: "把{object_a}向右移动五厘米|把{object_a}往东移五厘米|将{object_a}向右挪动5厘米", expected: "success", assertion: "transform_updated" },
  { id: "REL-NEAR-001", cat: "relative_near", parent: "GEN-ADD-001", asset_b_key: basket?.asset_key, variants: "把{object_a}移到篮子旁边|在篮子旁边增加一个{object_a}", expected: "success", assertion: "relative_placement" },
  { id: "REL-ON-001", cat: "relative_on", parent: "GEN-ADD-001", placement_1_key: tray?.asset_key, variants: "把{object_a}放到托盘上|将{object_a}放在托盘上面", expected: "success", assertion: "relative_placement" },
  { id: "REL-INSIDE-001", cat: "relative_inside", parent: "GEN-ADD-001", placement_1_key: basket?.asset_key, variants: "把{object_a}放进篮子|在篮子里增加一个{object_a}", expected: "clarification_required", expectedCodes: "scene_edit_inside_geometry_missing", assertion: "scene_unchanged" },
  { id: "SAFE-CENTER-001", cat: "center_collision", parent: "GEN-ADD-001", placement_1_key: table?.asset_key, variants: "把两个托盘都放到桌子中间", expected: "safe_rejection", expectedCodes: "scene_edit_layout_collision", assertion: "scene_unchanged" }
];
for (const item of extra) {
  generated.push({ enabled: 1, test_id: item.id, flow_id: item.id, parent_test_id: item.parent, difficulty: item.cat.startsWith("SAFE") ? "L4" : "L2", stage: "edit", round_index: 2, category: item.cat, sample_count: 3, branch_policy: "seed_parent", role_a: "object_a", role_b: "object_b", placement_1: "placement_1", asset_b_key: item.asset_b_key ?? "", placement_1_key: item.placement_1_key ?? "", surface_1_key: table?.asset_key, instruction_template: "增加一个{object_a}", variants: item.variants, scene_basis: "current", coverage_tag: `feature:${item.cat}`, expected_outcome: item.expected, expected_error_codes: item.expectedCodes ?? "", expected_scene_change: item.expected === "success" ? "changed" : "unchanged", assertion_profile: item.assertion, notes: "语义变体行；通过 parent_test_id 继承前置场景。" });
}

const known = [];
const scenes = ["ur5e_table_empty", "ur5e_table_apple", "ur5e_table_sorting", "ur5e_table_cabinet", "ur5e_table_push_pull", "piper_table_twist", "cobotmagic_table_grasp"];
const queryVariants = [
  ["L1", "existence", "有没有苹果？|有几个苹果？", "query_answered", "query_only", "query_no_version"],
  ["L2", "relation", "苹果在篮子左边吗？|篮子旁边有什么？|哪个苹果离篮子最近？", "query_answered", "query_only", "query_no_version"],
  ["L3", "original", "在原始场景中增加一个苹果|查询当前场景有几个物体", "success", "changed", "original_unchanged"],
  ["L4", "capability", "让机械臂执行当前场景任务|打开柜门后放入苹果", "capability_unsupported", "unchanged", "robot_plan_not_executed"]
];
for (const scene of scenes) for (const [difficulty, category, variants, outcome, change, assertion] of queryVariants) {
  known.push({ enabled: 1, test_id: `KNOWN-${scene}-${difficulty}-${category}`, scene_name: scene, difficulty, category, sample_count: 2, instruction_template: "有几个{object_a}", variants, role_a: "object_a", role_b: "object_b", round_index: 1, scene_basis: "preset", coverage_tag: `scene:${scene}:${category}`, requires_visual: category === "relation", expected_outcome: ((scene.includes("piper") || scene.includes("cobot")) && category === "capability") ? "capability_unsupported" : outcome, expected_scene_change: change, assertion_profile: assertion, notes: "预设场景能力边界与查询覆盖。" });
}

await fs.mkdir(outDir, { recursive: true });
await createWorkbook("generated_edit_matrix_v2.xlsx", generatedHeaders, generated.map((r) => row(generatedHeaders, r)), "Brain 场景编辑批量矩阵 v2", "每行代表一个语义类别；variants 只改变表达，parent_test_id 继承前置场景。桌面是唯一操作空间。",);
await createWorkbook("known_scene_matrix_v2.xlsx", knownHeaders, known.map((r) => row(knownHeaders, r)), "Brain 已知场景批量矩阵 v2", "按 OLS 场景和 L1-L4 能力覆盖查询、编辑、原始场景与能力边界。",);
