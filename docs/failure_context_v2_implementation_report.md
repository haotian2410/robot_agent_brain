# failure-context v2 实施报告

## 范围

本轮按 `docs/failure-context-v2/01_implementation_plan.md`、
`02_acceptance_cases.md` 与 `04_source_review.md` 实施。旧 context v1 未执行，FR01–FR69
没有伪造为通过；真实 Control/机器人执行仍需单独授权。

## 阶段提交

| 阶段 | 本地提交 | 内容 | 验证 |
|---|---|---|---|
| M0 | `652ba31` | failure-context.v1 严格 Wire model 与独立 Prompt | schema 导入 |
| M1 | `fa6a99f` | 外层用户轮次、失败链、效果证据持久化 | session store 回归 |
| M2 | `1c90921` | 恢复护栏与默认关闭的歧义自动选择 | recovery 单测 |
| M3 | `374a286` | 独立 Qwen `failure_context` 调用阶段 | Qwen HTTP 回归 |
| M4 | `a47ee9b` | 会话恢复/自动选择配置与协议字段 | Web protocol 回归 |
| M5 | `93d5da7` | Web 外层最终化、R 只读恢复和链状态 | Web service 回归 |
| M6 | `7aa9a3c` | 五轮上限、payload 禁止、完成步骤保护测试 | failure-context 单测 |
| M7 | 当前本地 M7 提交 | 保留当前原子规划与 OLS 集成修复；补充用户日志、恢复证据、步骤账本和受控自动选择接缝 | 全量基线分类 |

## 已验证

```text
pytest -q brain_tests/test_failure_context_v2.py
pytest -q brain_tests/test_qwen_http.py
pytest -q brain_tests/test_session_store.py
pytest -q brain_tests/test_web_protocol.py
pytest -q brain_tests/test_web_service.py
专项文件组合回归通过（failure-context、Qwen、session store、Web protocol/service）；当前组合共 66 项测试。
```

普通任务理解不会拼接 failure history；只有存在活动失败链的下一次外层用户轮次才会构造独立
`failure_context.v1` 请求。R 的结果必须再次经过 `RecoveryGuard`，不能直接改写场景、租约、ID、
平台或已完成步骤。失败链包含首个失败轮次，最多 5 个同链用户轮次；达到上限后进入
`exhausted`。

## 全量基线

全量 pytest 在当前 OLS/本地配置下仍有 10 项既有失败，主要是资产目录与历史 fixture 不一致、
双臂/机器人配置旧预期，以及本地配置缺少 geometry cache；它们不属于本轮新协议回归。完整输出
应以运行时日志为准，不将这些失败宣称为 FR 通过。

## 未覆盖/边界

- 真实 Qwen 对 R 的多轮联调、FR01–FR69 仍需在服务和浏览器稳定后逐例运行。
- unknown/partial execution/lease/recovery 的真实断线证据尚未在本轮自动注入测试中完成。
- `prefer_auto_resolve=true` 只允许稳定 ID、非破坏性且非 destination/query 选择；默认值仍为 false。
