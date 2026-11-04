# brain-web 语义重构验收记录（2026-11-05）

> 当前续验的源代码基线：`d381080`；远端同步基线为 `c64f57a`（本轮按要求未自动推送；
> 前文若出现旧提交号，仅作历史证据标记）。

## 已验证

- 官方规范导入：20 个 feature row、115 条完整表达、27 条回归不变量。
- 官方 v2 编译：schema v2；生成与已知场景两种 kind 均可编译 115 个 session。
- 目录注入：当前 OLS 1.0.7 本地目录读取 34 个 model、13 个 robot、7 个 scene；模型和机器人命名空间不混用。
- 每轮任务理解请求携带完整 `asset_catalog`、`workspace` 和 `scene_context`；请求体与 system prompt 使用同一 catalog revision。
- v3.1 场景编辑的 `asset_choices` 现在额外校验：实体存在、规范名称与 key 一致、模型允许新增、不得有多余选择。
- OLS 本地只读目录变化可在每个理解 turn 前原子重载；别名文件和 OLS revision
  一起进入 catalog snapshot，旧 Scene 快照不会被重写。
- mug-only 目录可将 `杯子/cup/马克杯` 作为当前目录的 alias 数据提供给 Qwen；
  如果后续 OLS 发布 canonical `cup`，该 token 会从 mug aliases 中移除，避免
  把两个真实资产合并。
- 2026-11-04 的真实 Qwen 一轮“增加一个苹果”已成功生成场景更新；该证据只代表单轮冒烟，不代表全量矩阵通过。
- 本轮新增 C4 回归：对象相对新增缺少 `reference`（例如“在苹果右侧增加香蕉”）时返回澄清，
  不再猜测为桌面；`center` 放置使用桌面几何中心，若该中心超出 workspace 则拒绝，不取裁剪后的中点。

## 本轮自动测试

```text
conda run --no-capture-output -n robot_agent_integ pytest -q
```

结果：全量通过（退出码 0）。另有官方 `validate_spec.py` 通过，编译输出 schema v2 / 115 sessions。

## 仍未宣称通过的项目

- 最新 fixed campaign 已重新展开部分父子流程，但 T02/T08/T11/T15 仍有真实失败或
  预期安全拒绝，T09/T10/T13/T14/T16–T20 缺少隔离 fixture；C7 全量真实验收仍为
  `unverified`。证据见 `docs/semantic-refactor/09_acceptance_report_20261105.md`。
- 远端 OLS HTTP 发生变化而本地联调目录未同步时，服务会报告目录不匹配并拒绝静默使用旧缓存；不会自动下载或修改 OLS 原始资产。
- `cup`/`mug` 的旧兼容别名仍保留给历史 replay/旧协议；v3.1 在线路径要求 Qwen 从当前 catalog 选择精确 `asset_key`。目录同时存在 `cup` 与 `mug` 时不会把 `cup` 追加为 `mug` 别名。
- 真实机器人执行、Control、IK、MuJoCo 和双臂规划不在本期范围。
- 修改代码后需重启运行中的 Brain 进程；现有进程不会热加载本轮变更。

## 证据与限制

- Wheel smoke 仍受当前环境缺少 `hatchling.build` 阻塞；这不是代码测试失败。
- 不同 seed 不保证一定抽到不同资产；manifest 必须记录 seed、catalog revision、实际 asset key 和父快照 digest。
- 生产 OLS、原始 OBJ/MTL/PNG/URDF 未修改；本记录只描述 Brain 代码和派生校验缓存。
