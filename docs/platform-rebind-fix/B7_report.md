# B7：分层回归、wheel 与发布门槛

## Python 3.12

```text
conda run --no-capture-output -n robot_agent_integ \
  env PYTHONPATH=src pytest -q
```

收集 `923` 项。首次运行发现本地派生缓存的 `asset_tree_sha256` 与当前 OLS
1.0.8 目录不一致，按设计拒绝使用过期缓存；这属于派生缓存过期，不是业务
逻辑失败。旧缓存已备份到 `/tmp/brain-cache-backup-20261108/`，随后使用当前
OLS 只读元数据重新生成 `var/webeditor/geometry_cache.json` 与
`var/webeditor/joint_inventory.json`，未修改 OLS 资产目录。重新运行结果为：
`923 passed`，无失败。

本轮未修改 OLS，也没有放宽缓存校验；若 OLS 目录再次变化，必须重新生成派生
缓存后再启动，不能静默使用旧缓存。

## Python 3.11

本机有 `/home/cscvlab/.local/bin/python3.11`，但没有 pytest（命令直接返回
`No module named pytest`），因此 Python 3.11 全量为 `not_run`，不是通过。

## wheel

`python -m pip wheel --no-deps ...` 构建成功，wheel SHA256：
`1f742c11caaf6976e93732281dcaa3ff699609fc68d25412bb2e3165eb4ff3a8`。

源码目录外的独立 wheel smoke 未完成：离线环境没有可供新 venv 安装的
`httpx/pydantic/jsonschema` 依赖，故标记 `not_run`，不以 editable install
替代。

## 真实联调

Qwen/OLS/Gateway/浏览器本轮未启动，所有 LIVE01—LIVE06 为 `not_run`。
