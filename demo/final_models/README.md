# final_models / 本地 Qwen

## 缩放与颜色多轮 demo

```bash
env -u ALL_PROXY -u all_proxy -u HTTP_PROXY -u http_proxy \
  -u HTTPS_PROXY -u https_proxy NO_PROXY=127.0.0.1,localhost \
  python demo/final_models/scale_color_demo.py --model Qwen3.8-27B
```

结果在 `var/scale-color-demo/scale_color_summary.json`，逐轮记录 Scene、patch、模型调用、
commands（仅机器人任务）和失败原因。脚本会核对预期拒绝时场景没有改变。
包含篮子模糊/绝对缩放、苹果禁止缩放、改蓝后查询、机器人规划、混合编辑与回滚。

这是 Brain 协议与语义验证，不是物理或渲染验证。当前资产包的参考渲染器仍可能把
颜色与原纹理相乘，且没有完整处理 alpha；不保证视觉纯色，也不修改该外部脚本。

## 资产接入 demo

在仓库根目录、安装好 Brain 的 Python 3.11/3.12 环境运行：

```bash
env -u ALL_PROXY -u all_proxy -u HTTP_PROXY -u http_proxy \
  -u HTTPS_PROXY -u https_proxy NO_PROXY=127.0.0.1,localhost \
  python demo/final_models/run_demo.py --model Qwen3.8-27B
```

每例独立会话。结果在 `var/final-models-demo/demo_summary.json`，其中 `artifacts`
列出该轮 `scene_config.json`、成功时的 `commands.json` 和原始模型调用记录。
这不是 MuJoCo 执行测试；`executed` 必须为 false。

- automatic：保留空模板的 7 个平台对象，增加苹果与蓝色篮子并规划。
- sorting：直接读取场景 3，对现有香蕉/篮子规划。
- edit：加载空模板增加香蕉，验证新增对象有正确的 MetadataRef.type。
- cabinet：加载场景 4，查询柜子数量，应为 1；不声称 Brain 能计算柜门关节路径。
- drawer：新库有 3 种同名抽屉，未给款式应请求澄清，不应任意选第一种。

柜子/抽屉的关节执行、附件世界位姿由外部平台提供；资产可加载不代表所有机器人
技能已经具备执行能力。demo 如实保留 blocked/failed，不会把它们改写为成功。
