# semantic-refactor 当前验证状态（2026-11-04）

本文件只记录当前工作树的实测结果，不覆盖历史整改报告中的旧提交号或旧环境结果。

## 已实现

- `ac0cf39`：OLS 目录快照增加独立的场景模板目录，并在每轮上下文中记录 `catalog_revision`。
- `8a3d317`：应用层、Pipeline 和 Qwen provider 统一使用同一份 OLS 目录快照；刷新目录时保留已注册 robot profile；直接 provider 调用也会用请求中的目录更新 Prompt 和结构化请求。
- Prompt 只加载 `task_understanding_clean_v3.txt`，并追加当前 OLS 的 models、robots、scenes，不暴露本地路径或内部文件名。

## 离线验证

环境：`conda` 环境 `robot_agent_integ`，Python 3.12。

```text
pytest -q
exit=0（全量测试全部通过）
pytest -q brain_tests/test_asset_catalog_v31.py brain_tests/test_pipeline_stages.py brain_tests/test_qwen_http.py
37 passed
python docs/semantic-refactor/validate_spec.py
status=valid；feature_rows=20；expressions=115；regression_invariants=27
```

当前 OLS 目录专项测试验证：34 个模型、13 个机器人、7 个场景；Prompt 中包含 `ur5e_table_empty` 和 `piper_table_twist` 场景模板。

官方 v2 workbook 编译成功：

```text
generated_edit：schema_version=2，115 sessions
known_scene：schema_version=2，115 sessions
```

编译命令使用 `--matrix-version 2`、官方 `02_semantic_test_matrix.xlsx`、`07_asset_roles_template.json` 和 `config/batch_asset_catalog.json`。

## 尚未验证/阻塞

本轮四个联调服务均未运行，端口连接结果为 `000/refused`：Qwen 8080、OLS 8000、Brain 8500、Gateway 8099。因此以下内容不能宣称通过：真实 Qwen 输出稳定性、OLS HTTP 在线目录、真实浏览器首轮上下文、Gateway campaign、截图和机器人执行链路。

独立 wheel 构建当前被环境阻塞：`hatchling.build` 未安装；这不是源码测试失败。

本轮不调用 Control、IK、MuJoCo 或真实机器人执行，也不把未启动服务的结果写成 C7 通过。

