# 复合场景修改样例

```bash
python demo/run_demo.py --case scene_edit
```

在仓库根目录运行。自然语言输入和检查条件在 `instructions.json`。

1. 无场景首轮：增加两个苹果、一个香蕉和一个篮子，自动建立桌面/机器人元数据，场景v2。
2. 两个苹果各向右2厘米；香蕉绕世界Z轴转30度，原子提交为v3。
3. 查询确认仍有两个苹果，保持v3。

每轮1次真实Qwen理解，零次skill planner。返回scene_patch和scene_config，不返回commands。
不仅检查成功状态，还比较两个苹果的世界位移与高度、香蕉四元数/位置、组件保留和版本增量。

最近实测文件：

- [首轮创建的场景v2](../results/shared-scene-v1/20261009-001313-f6f762/scene_edit/scene_edit/cdb3c34345174399a6409747347eccb0/scene_config.json)
- [复合修改的 ScenePatch](../results/shared-scene-v1/20261009-001313-f6f762/scene_edit/scene_edit/916c427e50734bf2b9803165e4261c3a/scene_patch.json)
- [修改后的完整场景v3](../results/shared-scene-v1/20261009-001313-f6f762/scene_edit/scene_edit/916c427e50734bf2b9803165e4261c3a/scene_config.json)

这些链接指向本机保留、git忽略的真实产物。完整记录见 `../VALIDATION.md`。
这是Brain场景元数据修改，不是MuJoCo物理仿真。
