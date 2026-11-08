# v0.2 验收状态（本地收口）

| 阶段 | 状态 | 证据/说明 |
|---|---|---|
| V0 基线与版本 | done | `release_manifest.json`；Brain `b2e5e0a`、OLS `4ab7c6b`、OLS `AppVersion 1.0.8-5cd6db7`、前端本地/远端 SHA 已记录 |
| V1 发布能力封锁 | done | `ReleasePolicy` 默认关闭换装、运行时 setup、自然语言初始平台选择、Control dispatch；Application/Session/AgentService/加载入口均有保护 |
| V2 初始导入与会话锁定 | done | 初始 Scene 在绑定前接纳；已初始化 session 二次 `load_scene` 返回 `capability_unsupported`；同一 CLI 请求中的禁用换装不会先写入 Scene |
| V3 计划绑定与失效 | done | request/publication 记录包含 Scene 四元组、digest、平台签名、setup revision 和配置指纹；成功 Scene 提交后旧 Commands 进入 `stale_commands`，仍保留历史文件但不再可 dispatch |
| V4 语义与 live 协议 | done | 多区域字段不广播；live catalog 要求 `task_understanding.v3.1`；无 catalog 仅限显式 replay/test compatibility |
| V5 前端/Gateway/OLS 兼容 | partial | OLS 1.0.8 catalog/assembly tests 在显式 `ROBOT_BRAIN_OLS_DATA_ROOT` 下通过；真实 Gateway/浏览器本轮未启动，标记 `not_run` |
| V6 CI/依赖/路径 | done | CI 使用 `.[dev,web,batch]`；集成测试不依赖个人绝对路径；wheel 构建及独立安装 smoke 通过；联网/无索引安装仍受环境依赖缓存限制，未伪造通过 |
| V7 真实联合展示 | not_run | Qwen、Gateway、真实浏览器、Control/IK/MuJoCo 未在本轮启动；按计划保留 `not_run` |

## 自动测试

Python 3.12 环境：`919 passed, 17 skipped`（`pytest -ra`）。17 个 skip 是需要显式外部 OLS 数据根的集成 fixture；使用：

```bash
ROBOT_BRAIN_OLS_DATA_ROOT=/home/cscvlab/lht/ObjectLibraryServer/data \
conda run --no-capture-output -n robot_agent_integ env PYTHONPATH=src \
pytest -q brain_tests/test_ols_latest_source.py \
  brain_tests/test_ols_robot_assembly.py \
  brain_tests/test_platform_rebind_regressions.py
```

上述外部 OLS 集成测试在当前 1.0.8 数据目录下通过（17 passed）。`git diff --check`、Python `compileall` 和 wheel 构建也通过。

独立 wheel smoke（Python 3.12、临时 venv、从 checkout 外运行、无 `PYTHONPATH`）通过：

```text
{"wheel_smoke": "passed", "provider": "replay",
 "real_qwen_tested": false, "web_import_and_routes_tested": true}
```

Python 3.11 本机解释器存在但缺少项目依赖，因此本地 3.11 全量回归标记为 `not_run`；CI 矩阵负责 3.11 验证。

## 未宣称的内容

没有把 OLS 目录存在、前端 checkout 或 mock provider 的结果写成真实联合验收。Qwen/Gateway 的实时可达性、截图、前端展示、真实 Commands 下载和 Control 执行仍需在冻结版本上另行执行；机器人结果继续要求 `executed=false`。

## 分层证据边界

| 环境 | 状态 | 结果 |
|---|---|---|
| Python 3.11 本地 | `not_run` | 本机解释器无项目依赖；不以失败环境冒充回归，交由 CI 3.11 矩阵验证 |
| Python 3.12 源码/Mock | `pass` | `919 passed, 17 skipped`；skip 仅为未注入外部 OLS 数据的集成 fixture |
| Python 3.12 + OLS 1.0.8 数据目录 | `pass` | OLS latest/assembly/rebind 专项 `17 passed` |
| 独立 wheel（checkout 外、无 `PYTHONPATH`） | `pass` | 临时 Python 3.12 venv；`wheel_smoke=passed`，Web 路由导入通过 |
| 真实 Qwen + Gateway + 浏览器 | `not_run` | 本轮服务未启动；没有截图、真实 HTTP 结果或浏览器展示通过声明 |
| Control/IK/MuJoCo/真实轨迹 | `not_run` | 明确不在 v0.2 范围 |

## 禁用能力的代码级证据

`ReleasePolicy(version="v0.2")` 默认关闭动态平台重绑定、运行时 RobotSetup、自然语言初始平台选择和 Control dispatch。Application、BrainSession、AgentService、初始导入/加载入口及浏览器 `platform_rebind` 路径共用该策略；对应拒绝发生在 ScenePlatform 写入、任务租约和计划发布之前。已有计划在成功普通 Scene 提交后转入 `stale_commands` 审计历史，查询、澄清和安全拒绝不主动清除当前计划。

## 发布结论

- 代码收口：`implemented_unverified`（本地源码和专项回归已通过，但当前工作树尚未形成冻结 release commit）。
- 可部署性：`pass`（Python 3.12、外部 OLS 1.0.8 专项、独立 wheel smoke）。
- 真实联合验收：`not_run`。
- 周四展示候选：仅限经过冻结版本复核的静态场景/语义与计划导出；平台动态换装、真实浏览器链路和 Control 执行不得作为已通过演示。
