# 可选阶段性能诊断

本地启用 `ROBOT_BRAIN_PERF_TRACE=1`，可用 `PERF_TRACE_OUTPUT_DIR` 指定独立输出目录。默认关闭。Web `/startTask` 创建trace，跨队列传递到worker；失败也记录，诊断写入失败不改变业务结果。不记录完整Prompt、Scene或凭证。

`src/robot_agent_brain/perf_trace.py` 提供 `trace_scope`、`span` 和 `timed`。直接Python入口需要显式建立trace_scope；本次未给所有CLI命令自动建立根trace。

```bash
PYTHONPATH=src python scripts/analyze_perf_trace.py /absolute/path/spans.jsonl --out var/perf/analysis
```

输出summary.json、timeline.txt、timeline.json、timeline_seconds.csv。inclusive父span与子span不可相加；wall_time_partition_ms是同一进程观察到的不重叠区间，不是CPU使用时间。并发叶子区间保留组合标签。submit_to_execute_end_ms只是execute结束代理；终态持久化/用户绘制不可据此宣称精确测量。

测试工具：

- `prepare_perf_runtime.py`：创建独立配置，固定planner=qwen并关闭执行。
- `run_perf_cases.py`：已绑定浏览器下的真实服务用例，每例独立会话；不会重启共享Qwen。
- `perf_preflight.py`：只读Provider初始化与OLS核验，不调用模型/Control。
- `perf_mock_cases.py`：Mock三步骤、20对交替开关插桩开销检查。
- `report_perf_run.py`、`finalize_perf_evidence.py`：汇总已采集证据；后者需对应隔离Brain仍在线。

每个脚本先查看`--help`。需安装项目Web依赖。不要把已有会话重置成性能fixture，不要把Mock当真实模型，不要关闭事务或安全校验。Control模拟需另行确认环境和授权。

2026-11-19实测报告：`var/perf/runtime-20261119-01/summary.md`，含comparison.md、recommendations.md、test_results.md及每轮逐秒证据。真实模型冷启动和P09未测；不得将首轮已有模型缓存的请求称为冷启动。实际性能服务使用第一版打点；后续补充的step_index/hash字节计数由Mock/preflight验证，不能倒填早期trace。
