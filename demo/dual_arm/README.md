# 双臂真实 Qwen 规划 demo

此 demo 调用真实 Qwen，读取 final_models 的 CobotMagic 场景，但**只验证 Brain 规划**。
`brain_only_demo` profile 中 `DEMO_ONLY_*` 是演示接口占位，不是 Control 的实际注册。
不调用 Control、MuJoCo 或机器人；`executed=false`。不能把输出直接当作部署配置。
倒水尚未注册，等待新版 `skill.md`。

在仓库根目录及已安装本项目的 Python 环境中运行：

```bash
export ROBOT_BRAIN_MODEL='/home/cscvlab/models/qwen3.8-27b/Qwen3.8-27B-UD-Q4_K_M.gguf'
env -u ALL_PROXY -u all_proxy -u HTTP_PROXY -u http_proxy -u HTTPS_PROXY -u https_proxy \
  python demo/dual_arm/run_qwen_demo.py --model "$ROBOT_BRAIN_MODEL"
```

模型名称必须以本机 `/v1/models` 返回值为准。`--base-url` 默认 `http://127.0.0.1:8080/v1`；
`--output-dir` 默认 `var/dual-arm-qwen-demo`；`--case 1` 或 `--case 2` 可单独运行。

两个独立会话分别测试：

1. 左臂抓苹果，同时右臂抓香蕉。
2. 左臂把苹果放入蓝色篮子，同时右臂把香蕉右移十厘米。

每个会话正常情况下调用一次任务理解和一次技能规划。任一步失败不重试模型、不降级
recipe、不加载失败候选；错误及原始响应照常保留。

输出目录：

```text
var/dual-arm-qwen-demo/
  summary-<run>.json
  dual-<run>-<case>/
    session_state.json
    original_scene.json                 首轮成功后才存在
    original_scene_manifest.json
    <request>/
      result.json
      request_record.json
      scene_config.json                 成功生成场景
      commands.json                     成功规划的 Commands v3
      debug/                            解析结果、原始响应、模型调用、规划校验
```

部署到 Control 前必须替换 profile 的 planning_group/end_effector/gripper，确认 v3
消费能力、barrier/null 保持/失败停止及逐臂反馈。初始空闲状态在此 demo 是显式测试声明，
不是 Control 传感器证据。通过符号验证不等于可达、无碰撞或真正同时执行。
