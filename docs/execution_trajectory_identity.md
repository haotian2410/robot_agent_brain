# 执行轨迹的场景身份绑定

## 控制端碰撞表示与状态输出

部署可显式设置 `execution_collision_model: precise`，经桥接层传入控制端
`--collision-model precise`。这是控制端支持的完整精确碰撞表示，不是关闭碰撞检测；
不改变安全距离、允许碰撞对、路径检查，也不修改输入 Scene 或 OLS 资产。
未配置时保留控制端默认值。代理模板校验失败不自动切换模式，不能只因 AABB 相同放行。
控制端 `output/summary.json` 记录实际选择的 `collision_model`。

最终回放帧取自生成最终状态快照的同一次采样；当前关节恢复不通过物理步进凑合到位。
只有未显式保存的依赖关节按已注册 MuJoCo equality 恢复，显式实测关节值始终优先。

## 轨迹发布

Brain 在任务终态保存后发送 `POST /updateTraj`。轨迹只用于显示，不修改权威 Scene，也不是执行成功证据。

Brain 请求携带查询参数：

- `count`：multipart 中 `trajs` 文件数。
- `sourceRequestID`：本次规划/执行请求 ID。
- `sessionID`：轨迹所属会话。
- `expected`：JSON 编码的 `scene_id`、`scene_version`、`scene_sub_version`、`sceneDigest`。

`expected` 来自已保存的最终任务结果，而不是发送时重新读取的最新会话；否则迟到的旧轨迹会被错误贴上新场景身份。Commands 内的版本仍是规划输入版本，不能拿它代替执行后结果版本。

Gateway 校验会话和完整四元组，不一致返回 HTTP 409 `trajectory_scene_mismatch`，不发给浏览器。通过后将身份传给浏览器，浏览器在二进制真正到达时再次比较本地会话和三项版本，避免发送期间发生场景切换。完整 digest 由 Gateway 校验，浏览器不自行重算。

远端批次默认显示最后一段末帧，用户点击 Play 才从首帧重播。手动加载轨迹保留原语义；不带 `expected` 的旧版通用接口仍兼容，但不具备这项任务身份保护。

安全边界：

- 播放失败不能撤销已经确认的执行或场景提交。
- 部分执行失败的轨迹可供诊断，不等于任务成功或会话已恢复。
- 本规则拒绝场景/会话不匹配；`sourceRequestID` 目前用于关联和审计，不是签名或授权凭据，也尚未实现同一场景身份下旧任务序号的独立淘汰机制。
- 不允许为了播放而解除 uncertain/quarantine。
