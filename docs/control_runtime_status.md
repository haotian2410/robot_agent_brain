# 控制端运行时状态

## 当前正式控制端

当前 WebEditor 联调使用：

```text
/home/cscvlab/lht/robot_agent_control
远端：Leon-J1n/Auto_Robot_demo
当前基线：414195b
```

Brain 通过 `robot_agent_link` 建立兼容桥接，控制端负责 IK、碰撞、路径、轨迹和执行反馈。
Brain 只负责任务理解、对象绑定、步骤顺序和单臂 Atomic Skill 命令生成。

## 已废弃的旧整合方案

```text
/home/cscvlab/lht/robot_agent_stack
```

该目录保留用于历史测试和迁移参考，不作为 8500 Brain 的运行时控制端，不参与当前
WebEditor 联调。不要同时启动其中的控制包，否则容易造成技能 Prompt、命令协议和执行
结果来源分叉。

## 当前联调边界

- 本轮只验证 `single_arm`。
- 双臂任务不调用控制端，统一标记为 `control_dual_arm_not_ready`。
- 控制端失败必须原样记录，Brain 不伪造执行成功或机器人位姿回写。
- OLS 原始资产不由 Brain 或控制端修改。
