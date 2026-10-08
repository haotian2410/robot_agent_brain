# 机械臂操作规划样例

```bash
python demo/run_demo.py --case robot_operation
```

在仓库根目录运行。自然语言输入和检查条件在 `instructions.json`。

1. 无场景首轮：两个苹果放进篮子，再把香蕉放进盒子。
2. 复用确认场景：抓起香蕉，向右移动5厘米，然后放下。
3. 查询苹果数量。

真实实测：首轮3个展开操作/18条commands，第二轮3个操作/5条commands，第三轮回答2。
前两轮各2次Qwen，查询1次。物体数量、Commands Schema、0.05米距离和场景不被伪执行均检查。

最近实测文件：

- [首轮场景](../results/shared-scene-v1/20261009-001313-f6f762/robot_operation/robot_operation/81f945371b534c88bcb196aa50685c9d/scene_config.json)
- [首轮 commands](../results/shared-scene-v1/20261009-001313-f6f762/robot_operation/robot_operation/81f945371b534c88bcb196aa50685c9d/commands.json)
- [第二轮 commands](../results/shared-scene-v1/20261009-001313-f6f762/robot_operation/robot_operation/4776ffde756b41649b00a3ca1258f645/commands.json)

这些链接指向本机保留、git忽略的真实产物。完整记录见 `../VALIDATION.md`。
本例只生成规划，**没有执行机械臂**；第二轮不声称已经处于上一份commands执行后的场景。
