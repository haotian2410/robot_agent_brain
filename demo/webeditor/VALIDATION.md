# WebEditor 首期实际验证记录

日期：2026-10-19。代码基线 `9835c60c28fdcfb4b4a9acb710600fa3be042f54`。
本次修改未提交、未推送；此处基线不是本次改动的提交 SHA。

## 自动检查

| 检查 | 实际结果 |
|---|---|
| Python 3.12.14 全量 pytest | 669 passed，9.59s |
| Python 3.11.14 全量 pytest | 669 passed，9.14s |
| 新增 Web 相关测试 | 38 项，包含实际外部七场景往返；本机未跳过资源测试 |
| 独立 wheel / Python3.12 | 仓库外、清除 PYTHONPATH，核心 CLI 与 web 导入/路由 smoke 通过 |
| 独立 wheel / Python3.11 | 同上，通过 |
| wheel 内容检查 | 无模型/纹理/URDF/数据库/压缩包/用户 .idea 和 robot_agent.md |
| Git diff whitespace 检查 | 通过 |
| GitHub Actions | 矩阵已改为安装 dev,web；本次未推送，因此未运行远端 CI |

wheel：`var/webeditor/wheelhouse/robot_agent_brain-0.1.0-py3-none-any.whl`，
SHA256 `daf34ffd7e0e09d081941b81bfb261269ea13e7ee7fcef188797c99728120532`。
独立环境 `/tmp/brain-web-wheel-Ligr3y/env`、`/tmp/brain-web-wheel-Ligr3y/py311`。
smoke 输出 `/tmp/brain-wheel-smoke-p9rjlixc`、`/tmp/brain-wheel-smoke-pazq9dvx`。
这些是本机临时产物，不进入仓库。

覆盖包括：空颜色/当前关节/固定挂载关节、uint32、幂等和持久重启、单服务文件锁、
版本冲突、错误浏览器/cache/播放中拒绝、单次全量提交、部分拒绝、超时不重发、
readonly restore、unknown/pending 禁止覆盖、受限下载、无上下文/跨站请求拒绝、
完整 PNG/尺寸/身份/不可见框、连续两次 original 相机重映射、空平台首轮前冻结原件。
未知状态不提供强制清除或自动写回旧场景。

## 固定资产与真实服务探测

外部资源根：`../webeditor_runtime/ObjectLibraryServer-1.0.4-rel/data`。
离线清单验证通过，34 models / 14 robots / 7 scenes；七个 Scene 完整 JSON 往返一致。
真实 OLS `/list`、所有 model/robot/scene 元数据与同目录 JSON 比对一致。
派生 geometry/joint cache 在 `var/webeditor/`，未写回资源根。
整棵 data 树哈希在验证前后、demo 后均为：

`47e56e21a46b202a6f51af0148f7bdb94f95c62660d0906834dbd225f4e1eb99`

真实 AgentService 在 127.0.0.1:8500 完成健康探测：service=ready、qwen=ready、
assets.matched=true；未绑定真实浏览器。原 WebEditor 发布包在8099探测为
`gateway_protocol_upgrade_required`。这不是“前端已对接”。
本次诊断启动的 OLS8000/Gateway8099/Agent8500 已关闭；原 Qwen8080 保持运行、不改配置。

## 真实 Qwen + 浏览器替身 demo

模型：现有 Qwen3.8-27B GGUF 服务（8080/v1），未重启。
OLS 真实；AgentService HTTP、SQLite 队列与 BrainApplication 真实；
**Gateway/浏览器为明确标注的进程内测试替身，没有渲染/相机/Control**。

最终报告：`var/webeditor/backend-demo-final/demo_report.json`。
会话：`6cb39137cfb3490d8036894f8ebe7128`。

| 轮次 | 输入 | 结果 | 场景版本 |
|---|---|---|---|
| 1 | 增加一个苹果和一个蓝色篮子 | scene_updated | 3→4 |
| 2 | 把苹果改成蓝色 | scene_updated | 4→5 |
| 3 | 查询蓝色苹果的数量 | answered，1个 | 5不变 |
| 4 | 把蓝色篮子放大一点 | scene_updated | 5→6 |
| 5 | 把苹果放大一点 | failed，scene_scale_forbidden（预期拒绝） | 6不变 |
| 6 | 把蓝色苹果放进篮子 | plan_ready，executed=false | 6不变 |

第6轮两次真实模型调用：task_understanding + skill_planning；Commands v2 顺序：
locate → move → grasp → locate → move → release。
命令在：

`var/webeditor/backend-demo-final/6cb39137cfb3490d8036894f8ebe7128/64ebad22253b47edb401a034b44747ff/commands.json`

保存每轮 Scene、编辑 patch、query_result、commands（仅机器人任务）、原始模型响应、
解析结果、模型调用 metrics、完整提交回执。最终逐文件检查确认：
查询、缩放拒绝、机器人规划均未改变场景；original 与首次导入空 UR5e 场景完全同摘要。

过程中保留了失败诊断目录 backend-demo、backend-demo-v2、backend-demo-v3，不将其当作最终通过：
早期侧向桌外摆放被拒绝；查询可选 payload 遗漏已通过显式 wire schema + TXT 示例修正；
空平台 original 原先冻结过晚，现已增加网页导入专用冻结逻辑和回归测试。
旧 CLI 跳过空模板的行为保留。

## 尚未通过、必须与前端同事联合完成

- 真实浏览器中的 commitWorld/事务恢复/单活动浏览器/编辑锁。
- 网页手动拖动、增删、关节编辑后的连续多轮，以及真实浏览器 original 恢复。
- 真实 captureScene RGB/深度及 get2DAABB 身份与现场一致性。
- 至少一个真实截图实际触发 Qwen 视觉消歧的用例。
- 前端任务结果、澄清、计划摘要、模型调用、产物下载的 UI 展示。

原因：提供的 dist 发布包没有新契约接口；没有源码，不修改压缩 JS，也不伪造现场证据。
相机适配器和故障测试已实现，但替身图像测试不是实际视觉联调通过。
请将 `docs/webeditor_integration.md` 和 `scripts/export_webeditor_contract.py` 的输出交给同事。
