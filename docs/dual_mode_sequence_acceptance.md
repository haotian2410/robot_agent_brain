# 双模式序列重构最终验收

日期：2026-11-27。依据附件v2.0，基线9c0e3da。未提交、推送或重启生产服务。

## 附件第12节逐项核对

| 要求 | 实现与测试 | 结论 |
|---|---|---|
| 无resource/hold/sync共享字段 | commands_sequence_v41封闭模型及协议测试 | 通过 |
| 不按同对象、目的地、持物或并行推导跨臂等待 | dual_arm_sequence、TaskExpander、assignment边界测试 | 通过 |
| 显式operation依赖转换command边 | 前置末命令到后置首命令；test_dual_arm_sequence | 通过 |
| staged v3不可用于新任务 | 旧planner退役，新结果及dispatch拒绝3.0 | 通过，历史恢复隔离保留 |
| 首轮setup、后续模式锁定 | RobotModeLock、SessionState、scene mode resolution测试 | 通过 |
| 双臂仅动单手仍走双臂协议 | dual_session_pipeline、web_mode_state | 通过 |
| 单臂继续Control skill.md atomic | 原单臂路径及全量回归 | 通过 |
| 双臂同技能源、独立wrapper | test_dual_atomic_prompt_source | 通过 |
| 布局先提交、新身份规划 | test_dual_layout_composite_sequence | 通过 |
| 机器人失败保留布局、不复用旧Commands | composite事务测试 | 通过 |
| 双环境、wheel、HTTP、协议回归 | 下表 | 通过 |
| 不虚称真实双臂执行完成 | 实际4.1 dispatch明确报告adapter不可用 | Control联调未完成，已注明 |

兼容单臂无物理RobotProfile时，首轮成功也保存default_single逻辑模式锁。
该名称不是物理profile或Control能力声明，不虚构关节和planning_group。
失败初始化可重试；保存恢复、original派生、受控平台变更保持修订一致。

## 最终验证

| 检查 | 结果 | 证据 |
|---|---|---|
| Python3.12全量 | 2037 passed / 31 skipped，39.71s | mode-final-312.xml |
| Python3.11全量 | 2037 passed / 31 skipped，33.61s | mode-final-311.xml |
| wheel构建及schema | 通过 | /tmp/brain-mode-final/dist/robot_agent_brain-0.1.0-py3-none-any.whl |
| 两版本独立安装smoke与理解smoke | 仓库外全部通过 | smoke-311.log、smoke-312.log |
| 两版本安装包隔离HTTP health | HTTP200，外部服务未配置如实显示不可用 | health-311.json、health-312.json |
| HTTP双臂规划 | fixture下plan_ready/executed=false，4.1、新digest、无pending | test_web_mode_state.py |

相对证据位于var/dual-sequence-refactor/。
wheel SHA256：5d3c2cc17b35c1ed1745c5e05f1d1a0cdc44777184cbbe3e4d9ff466b38ca60f。
31项跳过不算通过，更不表示真实Control或浏览器执行通过。

## 真实Qwen与保留失败

real-u-explicit-order-01至04曾遗漏显式依赖，失败原始证据保留。
Compact robot operation Schema改为明确输出operation和depends_on，不自动补语义依赖。
05、06各首次3/3，共6/6、无重试；real-u-mode-selection-01首次2/2，保留single/dual及指定fixture profile。
这些仅证明对应理解调用，fixture名称不代表Control真实注册。

## 发布边界

本轮完成Brain语义、分臂、4.1规划、模式锁和复合事务重构。
真实双臂Control 4.1联调未完成，未执行真实双臂动作，未提供本轮浏览器运动截图。
4.1下发适配不可用时明确拒绝，不退回v3、不补共享调度字段。
桥接与Control源码未发现旧协议导入，不等于已经支持4.1消费。
生产服务仍运行原版本，本轮未自动部署、提交或推送。
