# B1—B4：限域、局部装配、ID 与首轮提交

## 修改

- `OlsRobotAssemblyAdapter` 现在按实际变化角色构造候选；相机-only、夹爪-only
  不重建机械臂的 `RobotDriver`、Transform 或未知组件。
- 同资产请求返回 `noop=true`，不增加场景子版本，不清除运行绑定。
- 换臂保留已有夹爪资产并重新核验新臂的唯一 joint/link；保留已确认的挂接
  Transform，缺失/多候选连接拒绝，不补空连接。
- 新增的夹爪/底座使用 Session 高水位；被删除的底座 ID 不复用。
- `BrainSession` 在 Agent 借助有效的本地 owner 任务上下文时允许 agent_owned
  换装；没有相同 owner 或直接 Python 调用不能借 phase 越权。
- 浏览器与 Agent 候选共用 platform scope 检查：普通物体、桌面、灯光不能通过
  candidate 自报的 `Semantic.category` 获得平台权限；底座移除和 OLS 声明的
  新夹爪/支撑部件才在受限范围内允许。
- 首轮空会话换装先在内存构造最终装配，再一次 `load_scene`，版本为 1/0，
  original/manifest 从最终候选冻结。
- ScenePlatformPort 的 `load_scene(..., change_kind=...)` 不再捕获 TypeError
  后重试为普通写入；Mock/Local 平台接口已统一。

## 结果

同一专项命令通过；Web/Session/Gateway 相关专项合计通过：

```text
conda run --no-capture-output -n robot_agent_integ \
  env PYTHONPATH=src pytest -q \
  brain_tests/test_ols_robot_assembly.py \
  brain_tests/test_platform_rebind_regressions.py \
  brain_tests/test_web_service.py \
  brain_tests/test_web_gateway.py \
  brain_tests/test_robot_config_noop.py \
  brain_tests/test_session_store.py \
  brain_tests/test_shared_scene_contract.py
```

结果：`全部通过`（本次执行 78 项专项/回归测试）。

## 剩余边界

浏览器公开请求仍使用现有 `change_kind=platform_rebind` 兼容字段；若产品要在
同一场景多个相机中选择单个目标，需要 Gateway 继续提供显式相机目标身份，不能
由 Brain 猜测。
