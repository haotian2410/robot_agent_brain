# OLS 资产 Tags 同义词更新 v1

## 背景

Brain 使用 `tag_overlap_score()` 将用户指令中提取的标签与 OLS 资产 tags 做交集匹配。
别名表 (`webeditor_aliases.json`) 中存在同义词映射（如"杯子"→mug），但 OLS 资产 tags 中
只有"马克杯"/"杯具"而没有"杯子"，导致精确匹配失败。

**解决方式**：将别名表中的中文同义词追加到对应资产的 `semantic_properties.tag` 字段。

## 修改规则

- 只修改 `semantic_properties.tag` 的字符串值
- 保留原有 tags 顺序，在末尾追加新 token
- 使用半角逗号 `,` 分隔（不用全角 `，`）
- 不修改 `object_name`、`object_id`、`object_name_Chinese` 或其他任何字段

## 变更表

| ID | 文件路径 | 旧 tag | 新 tag | 追加同义词 | 来源 |
|----|----------|--------|--------|-----------|------|
| 8 | `models/8/gum_bottle.json` | `口香糖,容器,整盒装` | `口香糖,容器,整盒装,胶瓶` | 胶瓶 | alias "胶瓶"→gum_bottle |
| 9 | `models/9/cream.json` | `护发霜,洗护用品,长方体盒` | `护发霜,洗护用品,长方体盒,护肤霜` | 护肤霜 | alias "护肤霜"→cream |
| 10 | `models/10/marker.json` | `记号笔,文具,圆柱,粗笔划` | `记号笔,文具,圆柱,粗笔划,马克笔` | 马克笔 | alias "马克笔"→marker |
| 14 | `models/14/mug.json` | `马克杯,杯具,带把手,高杯,花纹` | `马克杯,杯具,带把手,高杯,花纹,杯子` | 杯子 | alias "杯子"→mug |
| 20 | `models/20/test_tube_rack.json` | `试管架,实验器材,高款，带提手,三排,金属` | `试管架,实验器材,高款,带提手,三排,金属` | (修复全角逗号) | 数据修正 |
| 22 | `models/22/toy_panda.json` | `熊猫玩偶,玩具,方形` | `熊猫玩偶,玩具,方形,玩偶,熊猫` | 玩偶,熊猫 | alias "玩偶"/"熊猫"→toy_panda |
| 23 | `models/23/mug.json` | `马克杯,杯具,带把手,浮雕纹,胖圆形` | `马克杯,杯具,带把手,浮雕纹,胖圆形,杯子` | 杯子 | alias "杯子"→mug |
| 24 | `models/24/mug.json` | `马克杯,杯具,带把手,矮宽` | `马克杯,杯具,带把手,矮宽,杯子` | 杯子 | alias "杯子"→mug |
| 25 | `models/25/drawer.json` | `抽屉柜,家具,双层抽屉,木制,方形矮款` | `抽屉柜,家具,双层抽屉,木制,方形矮款,抽屉` | 抽屉 | alias "抽屉"→drawer |
| 26 | `models/26/can.json` | `易拉罐,容器,金属圆柱` | `易拉罐,容器,金属圆柱,罐子` | 罐子 | alias "罐子"→can |
| 28 | `models/28/cabinet.json` | `储物柜,家具,单门,红木,矮款` | `储物柜,家具,单门,红木,矮款,柜子` | 柜子 | alias "柜子"→cabinet |
| 29 | `models/29/table.json` | `桌子,家具,长方形,四条腿,红木` | `桌子,家具,长方形,四条腿,红木,桌面` | 桌面 | alias "桌面"→table |
| 30 | `models/30/bottle.json` | `塑料瓶,矿泉水,容器,半透明` | `塑料瓶,矿泉水,容器,半透明,瓶子,水瓶` | 瓶子, 水瓶 | alias "瓶子"→bottle；"水瓶" 为用户补充的口语说法 |

## 未修改的资产

以下资产的 tags 已包含别名表中的同义词，无需追加：

- ID 1 apple: "苹果" ✓ (alias "苹果"→apple)
- ID 2 banana: "香蕉" ✓
- ID 3 baseball: "棒球" ✓
- ID 4/12 basket: "篮子" ✓
- ID 5 pen: "笔" ✓
- ID 6 pen: "钢笔,笔" ✓
- ID 7/13 screwdriver: "螺丝刀" ✓
- ID 11 test_tube_rack: "试管架" ✓
- ID 15 rubiks_cube: "魔方" ✓
- ID 16 school_bell: "铃铛" ✓
- ID 17 tray: "托盘" ✓
- ID 18 coffee_table: "茶几" ✓ (no_display)
- ID 19 sugar_box: "糖盒" ✓
- ID 21 test_tube: "试管" ✓
- ID 27 button: "按钮" ✓
- ID 31 microwave: "微波炉" ✓

## 适用范围

- **适用**: OLS 1.0.8-rel 及后续版本（中文 tags）
- **不适用**: OLS 1.0.5-rel / 1.0.7-dev（英文 tags，如 "red_patterned"）

## 部署说明

1. 修改 OLS 源仓库 `ObjectLibraryServer/data/models/<id>/<name>.json`
2. 发布新版 OLS 包
3. 更新 runtime 部署目录

## 后续可选项

- ID 9 的 `object_name_Chinese` 从"护发霜"改为"护肤霜"（与别名表一致，但不影响匹配）

## Brain 侧配套改动（不在 OLS 包内）

- `config/webeditor_aliases.json` 新增 `"水瓶":"bottle"`。该表由 Brain 持有，不随 OLS 发布。ID 30 追加的 `水瓶` tag 不依赖这条别名即可命中；别名只额外让 name 兜底路径和目录的 `aliases=` 列也认"水瓶"。
- 英文别名 token（"cup"/"coffee_cup"/"work_table"等）暂未加入 tags
