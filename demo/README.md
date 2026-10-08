# 真实 Qwen 两类多轮 Demo

这两个样例均从**没有场景**开始，由真实 Qwen 理解首轮任务，Python 创建 Brain 原生场景。
不使用 Replay/fake，不调用 MuJoCo，不控制真实机械臂。

- `robot_operation/instructions.json`：集合搬运 + 多目标顺序 + 抓取/位移/释放 + 查询。
- `scene_edit/instructions.json`：多对象新增 + 集合平移 + 世界轴旋转 + 查询。
- `run_demo.py`：探测服务模型，按样例运行，保存每轮文件并做语义/数值检查。
- `results/时间-随机ID/`：本机实测产物，每次新目录，失败保留原始响应，不覆盖上次结果。

## 一键运行

```bash
cd /home/cscvlab/lht/robot_agent_brain
conda activate robot_agent_integ
python demo/run_demo.py
```

如尚未安装此仓库：`python -m pip install -e .`。
脚本默认直连 `http://127.0.0.1:8080/v1`，不继承 HTTP 代理。
`/models` 只有一个模型时自动采用其真实 ID；多个模型时必须传 `--model`，不会猜名字。

```bash
python demo/run_demo.py --case robot_operation
python demo/run_demo.py --case scene_edit
python demo/run_demo.py --base-url http://127.0.0.1:8080/v1 --model '服务返回的模型ID' --timeout 180
```

API key 如需配置，使用 `ROBOT_BRAIN_API_KEY`，不要写入样例。其他选项：
`--case all|robot_operation|scene_edit`（默认 all）；`--output-dir PATH`（默认 demo/results）。
两例都显式设 `planner=qwen`、JSON Schema、debug=true、seed=0。
场景采用团队组件 Scene v1，默认 $DEMO_LIBRARY 元数据；demo_joint 不是 UR5e 的真实关节配置。
当前共享协议没有实例 color 语义，故不再用旧版“改色”作为本样例步骤。
每例独立会话，例内后续轮次复用同一确认场景。前一轮失败则跳过依赖轮次，但不影响另一例。
终端最后输出 summary.json 路径；全部检查通过退出0，否则退出1。

## 样例 A：机械臂操作规划

1. `用机械臂先把两个苹果放进篮子，再把一个香蕉放进盒子。`
   初始创建桌子、两个苹果、一个香蕉、篮子、盒子；集合展开后是三个放置操作。
   首轮建场景与规划使用同一次任务理解；不把苹果预先放进篮子。
2. `用机械臂抓起香蕉，向右移动五厘米，然后放下香蕉。`
   验证 grasp → move → release 链和0.05米位移；Python 管持物状态/距离，第二Qwen组合技能。
3. `有几个苹果？` 验证现有场景仍为两个苹果，查询不调用第二模型。

前两轮正常各调用一次理解、一次技能规划；查询一次理解。
**这里“成功”只代表 commands 导出成功，executed=false。** 第二轮基于初始确认场景，
不是上一份 commands 执行后的世界。需要实际执行，必须由 Control 消费场景和命令，
完成 dispatch/feedback；没有执行反馈，不会伪造香蕉已经在盒子中。

## 样例 B：场景修改

1. `直接修改场景：增加两个苹果、一个香蕉和一个篮子。`
   首轮创建桌面并新增四个对象，产出 ScenePatch 与 scene_config.json。
2. `直接修改场景：把两个苹果都向右移动两厘米，把香蕉绕世界Z轴旋转三十度。`
   一个复合编辑：两个苹果各x+0.02米，香蕉旋转30度；原子提交一次场景版本。
3. `有几个苹果？` 再次查询两个苹果。

每轮只调用一次理解，skill_planning_calls=0，不输出 commands。
脚本检查世界坐标差、未变的高度、四元数、数量、其他组件保留和场景版本，而非只看“成功”文字。

## 文件在哪里

先打开本次 `results/<run>/summary.json`，里面每项 artifacts 使用**相对于该run目录**的路径。
每轮底层目录为：

```text
results/<run>/robot_operation/robot_operation/<request-id>/
results/<run>/scene_edit/scene_edit/<request-id>/
  result.json                     # 执行标记固定 false、调用记录、交付状态
  request_record.json             # 输入、非秘密配置、指纹
  scene_config.json               # 本轮完整 Brain 场景快照（不是 XML/MJCF）
  commands.json                   # 仅成功的 robot_task
  scene_patch.json                # 仅成功的 scene_edit
  query_result.json               # 仅查询
  debug/
    brain_turn.json               # 第一次模型的规范化结果
    task_intent.json               # 机器人任务语义
    planner_context.json          # 第二次输入，不包含物理场景快照
    planner_skill_catalog.txt      # 原子技能目录
    raw_skill_plan.json            # 第二次原始输出
    normalized_skill_plan.json     # Python绑定后的技能计划
    skill_plan_validation.json     # 语义校验
    model_calls.json               # 实际阶段、token、耗时与失败记录
    traceback.txt                  # 失败时
```

未进入的阶段不会伪造文件；每例下还有 session_state.json。
Scene Edit 后应对照两轮 scene_config；机器人任务交付应读取**同轮** scene_config+commands，
不能取旧命令补本轮失败。没有 interaction_registry 或 scene.xml；这些属于未接入的执行平台适配。

结果目录含原始用户文本和模型响应，默认不纳入 git；可在本机直接检查。
本轮真实运行情况见 `VALIDATION.md`。可重复运行，但真实模型输出不保证每次完全相同。
