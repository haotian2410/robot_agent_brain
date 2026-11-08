# Robot Agent Brain v0.2 发布收口记录

## 范围

本版本保留 `brain-web/2`、`task_understanding.v3.1` 和现有 Commands 输出协议；不新增 Control、IK、MuJoCo、轨迹执行或会话内机器人/夹爪/相机换装。平台只能在会话绑定前由前端选择并由 Brain 验证，绑定后的自然语言、HTTP、CLI 和内部业务入口均拒绝平台重绑定。

拒绝平台变更必须是无副作用的：Scene、四元组/digest、平台配置、ID 高水位、original、对话焦点和当前计划均不改变；只保留请求审计，并正常释放本次租约。

## 本次基线证据

| 组件 | 版本/提交 | 状态 |
|---|---|---|
| Brain | `b2e5e0a8c74bd329c0344122f28e0bb1db443167` | 当前仓库基线；工作区另有本地未提交适配和测试 |
| WebEditor/Gateway | 本地 `88a35b31dfaac1aaad36d68fd0cdc77b6171f849`；远端 master `caf1ba8c4c9bc00d7f2816d98d7b3cf26f27b91c` | 本地领先远端 1 个提交，未强制覆盖 |
| OLS | `4ab7c6b2a2d602f160e33100dfd011b16699133a` | 与远端 master 一致 |
| OLS 资源 | `AppVersion 1.0.8-5cd6db7` | 31 模型、14 机器人、7 场景；数据目录为外部运行目录 |
| Qwen/Gateway 运行实例 | 未在本轮启动/未获取启动参数 | `not_run`，不能据此宣称真实联合验收通过 |

当前 Brain 的联调配置使用 `config/webeditor_ols_latest.json`，其 OLS 根目录为 `../../ObjectLibraryServer/data`，默认场景为 `ur5_table_empty`；旧 1.0.5/1.0.7 目录未被覆盖。旧几何缓存不作为新 OLS 的静默回退来源。

## 已落地的 v0.2 保护

- `ReleasePolicy` 默认关闭 dynamic platform rebind、runtime robot setup、自然语言初始平台选择和 Control dispatch；v0.2 配置若打开这些能力会启动校验失败。
- Application、BrainSession、AgentService、浏览器场景接纳和加载入口共用策略；已有会话不能通过再次 `load_scene` 换平台，只有未初始化/协议空文档允许首次导入。
- 计划保存 scene 四元组、digest、平台签名、robot setup revision、配置指纹；成功场景提交会将旧 Commands 移入可审计的 stale 历史，不再作为当前可执行计划。
- 多区域归一化不广播首个区域到全部操作；带目录的 live understanding 必须返回 `task_understanding.v3.1`，旧 replay 仅通过显式无目录路径兼容。
- CI 安装 `.[dev,web,batch]`；集成 OLS 测试通过 `ROBOT_BRAIN_OLS_DATA_ROOT` 显式提供外部资源，个人绝对路径不再是核心测试前提。

## 验收边界

Python 全量回归在当前环境通过；真实 Qwen、真实浏览器、Gateway 和 Control 联合验收尚未在本轮执行，统一标记 `not_run`。Piper/CobotMagic 等未注册平台仍可展示/查询/编辑，但机器人任务必须返回 capability unsupported，不能生成伪 UR5e Commands。
