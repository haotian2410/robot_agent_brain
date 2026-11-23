# 失败上下文与二值歧义策略——实施验收报告模板

状态：待填写。不得将模板中的预期写成实际结果。

## 1. 版本与环境

- baseline SHA：
- tested SHA / working tree clean：
- Python、Qwen模型/版本/参数：
- OLS/Gateway/Frontend/Control版本：
- execution_enabled：
- execution_environment（真实/隔离仿真/未知）：
- memory/auto policy配置：

## 2. 修改范围

按 M0～M7 列文件与实现接口；说明未改动的旧协议和被复用的模块。

## 3. 测试结果

| 层级 | 命令/证据路径 | 通过/失败/跳过 | 状态 |
|---|---|---|---|
| Python 3.11 | | | not_run |
| Python 3.12 | | | not_run |
| FR01～FR69 | | | not_run |
| Mock Qwen/Gateway/Control | | | not_run |
| wheel独立安装 | | | not_run |
| 真实 Qwen | | | not_run |
| 独立仿真Control | | | not_run |
| 物理Control（需另行授权） | | | not_run |

## 4. 核心证据

- 正常请求前后Prompt/schema/payload比较与R调用数。
- 两苹果一托盘：询问模式／自动模式各一条完整证据。
- 首失败根ID不变与第五轮终止。
- 成功前缀不会重放的Scene差分和step ledger。
- 有副作用但反馈未知时零重复派发。
- 颜色/标签未知不得随机、计划与执行事实分开。
- HTTP幂等、checkpoint重启与late feedback修订。

## 5. 成本统计

区分用户轮数、R/U/decomposition/planner/vision模型调用数、各阶段token、Control attempts。
不要把内部attempt混入“五轮失败”指标。

## 6. 未完成项与风险

逐项记录，不以mock替代真实联调，不以本地绿灯替代干净CI。
