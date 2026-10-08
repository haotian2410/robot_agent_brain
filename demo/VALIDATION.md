# 组件 Scene v1 真实 Qwen 验收 — 2026-10-09

实际服务 `http://127.0.0.1:8080/v1`，llama.cpp 模型 ID：
`/home/cscvlab/models/qwen3.8-27b/Qwen3.8-27B-UD-Q4_K_M.gguf`。
新协议实跑 **6/6 通过**，共 8 次真实模型 HTTP 调用；无 Replay、重试或 planner 降级。
`real_qwen_tested=true`、`robot_executed=false`、vision_calls=0。
使用默认 demo 元数据，不是正式 grasp_objects + 平台资源的完整联调。

本地结果：[summary.json](results/shared-scene-v1/20261009-001313-f6f762/summary.json)。
该结果目录不提交 Git；克隆后可用 `python demo/run_demo.py` 重新生成。

| 轮次 | 实际结果 | 理解/规划 | completion tokens（理解/规划） |
|---|---|---|---|
| 机器人01 | 两苹果、一香蕉、篮子、盒子；18 命令；Scene v1 | 1/1 | 336/404 |
| 机器人02 | 抓起→右移 0.05m→放下；5 命令；Scene v1 不变 | 1/1 | 203/141 |
| 机器人03 | 苹果数量 2；Scene v1 | 1/0 | 124/— |
| 编辑01 | 四个任务对象；Bootstrap v1 + 编辑后 v2 | 1/0 | 320/— |
| 编辑02 | 两苹果世界 x+0.02m，香蕉世界 Z 旋转 30°；v3 | 1/0 | 235/— |
| 编辑03 | 苹果数量 2；Scene v3 | 1/0 | 124/— |

所有 finish_reason=stop。Scene 和 Commands 的 ID 均为整数；编辑只改变目标组件，
未改动对象/非语义组件保持。新协议没有实例 color 语义，因此新版示例不再要求改色。
机器人成功仅表示规划导出，没有 Control/Simulation/Frontend 联调，不证明抓取成功。
下面保留旧协议历史结果，不用它代替本轮验收。

# 历史：真实 Qwen Demo 验收 — 2026-10-07

服务：`http://127.0.0.1:8080/v1`，通过真实 `/models` 获取的模型：
`/home/cscvlab/models/qwen3.8-27b/Qwen3.8-27B-UD-Q4_K_M.gguf`（llama.cpp）。

`real_qwen_tested=true`，`robot_executed=false`。无Replay，无手写模型输出替换，无重试/降级。
两组各3轮，**6/6通过**，合计8次实际HTTP模型调用。

本次结果根目录：`demo/results/20261007-215414-37c21d/`。
[总索引 summary.json](results/20261007-215414-37c21d/summary.json) 包含每轮输入、调用日志、
相对产物路径、场景版本和校验状态；service_models.json保留服务探测响应。

| 样例/轮次 | 结果 | 理解/规划调用 | completion tokens（理解/规划） | HTTP总耗时 |
|---|---|---|---|---|
| 机器人01：建场景+集合搬运 | 2苹果/1香蕉/1篮子/1盒子，3操作、18命令，v0 | 1/1 | 336/400 | 19.51s |
| 机器人02：抓起→右移5cm→放下 | 3操作、5命令，distance_m=0.05，v0不变 | 1/1 | 216/141 | 10.00s |
| 机器人03：查询 | 苹果=2，v0 | 1/0 | 124/— | 3.55s |
| 编辑01：建场景+多对象新增 | 桌面+2苹果/1香蕉/1篮子，v1 | 1/0 | 320/— | 8.11s |
| 编辑02：平移+旋转+改色 | 两苹果x+0.02、香蕉z旋转30°、篮子蓝色，v2 | 1/0 | 341/— | 8.68s |
| 编辑03：查询 | 苹果=2，v2 | 1/0 | 124/— | 3.26s |

所有调用 finish_reason=stop。时间是本次HTTP调用记录求和，不是机器人执行时间。
脚本逐轮验证场景ID/版本、数量、无伪执行、模型调用数、位移/旋转/颜色和输出域隔离。
命令由正式CommandExporter做模型+公开JSON Schema校验，未绕过PlanValidator。

## 真实试跑暴露的问题与本轮小改动

保留首次试跑目录 `results/20261007-215048-41442e/`，不把失败当通过：

1. 第二Qwen用多行缩进且大量null，3操作输出到768 token被截断。
   在 skill_planning_v2.txt 要求紧凑单行JSON、省略可选null、简短intent。
   **没有扩大预算、减少动作、改schema或静默修复。** 同一复杂指令后续400 token完整输出18步。
2. 场景复合编辑的translate漏掉direction/distance_m。
   在 task_understanding_v2.txt 明确场景direction与机器人motion_direction的区别，补完整编辑示例。
   后续真实响应保留两苹果移动、香蕉旋转和篮子改色，数值验证通过。
3. 首版demo检查器把四元数字段误写为quaternion，首次检查失败报告时出现KeyError。
   已改为实际契约quaternion_xyzw，并让失败报告提前返回检查结果；未改写旧失败产物。

两处提示词更新保持原来的txt单一事实源；不新增模型调用，不改变冻结契约。
提示词专项33项通过，全量 **327项测试通过**。

## 边界

这是两个真实样例的通过记录，不是模型稳定性或任意任务正确率证明。重复运行可能失败，
此时检查本轮raw响应及traceback，不要拿旧commands当新结果。
机器人操作只是导出计划；未接Control、前端、真实机器人或MuJoCo。
场景文件是Brain JSON，不是scene.xml；无interaction_registry，不输出IK/轨迹。

本次未提交或推送GitHub。代码、说明和样例输入在demo目录；结果含原始模型响应，
默认被demo/.gitignore忽略，保留在本机。以后克隆仓库需要运行脚本重新生成结果。
