# B0：真实仓库类失败回归

基线：`041516434bb34272c3d3b364cb001af2568ef7a4`。本阶段新增
`brain_tests/test_platform_rebind_regressions.py`，直接调用生产的
`OlsRobotAssemblyAdapter`、`BrainSession`、`SceneConfig` 和平台端口，不抽取
方法体，也不使用 `model_construct()` 绕过契约。

初始结果（修复前）：4 项失败：相机/夹爪单独切换会重写机械臂；同资产请求
不是 no-op；platform_rebind 可以夹带桌面 Transform 修改。随后补充了换臂附件、
租约 owner、退役 ID 和首轮单次提交回归。

命令：

```text
conda run --no-capture-output -n robot_agent_integ \
  env PYTHONPATH=src pytest -q \
  brain_tests/test_ols_robot_assembly.py \
  brain_tests/test_platform_rebind_regressions.py
```

结果：`12 passed`。外部 OLS 目录仅作为测试资产读取，不被测试修改。
