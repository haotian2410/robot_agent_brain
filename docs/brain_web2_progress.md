# Brain／WebEditor `brain-web/2` 实施进度

基线：`80f4d1a`。本轮不回退到 `9835c60`，也不进行真实浏览器、Gateway、OLS 或 Qwen
联合联调；联调项在前端下一次发布包到达前标记为 `skip`。

| §A10 阶段 | 状态 | 已完成内容 | 对应验证 |
|---|---|---|---|
| A1 场景解析 | `done` | 增加 raw `SceneDocument` 与类型化 view；未知组件/属性保留；缺失 Transform、重复组件、前向引用、坏父子树按协议处理；支持 `RobotAttachment`、`role`、`now_joint_positions_rad` | `conda run -n robot_agent_integ pytest -q brain_tests/test_brain_web2_scene.py`：4 passed |
| A2 摘要与协议 | `done` | 协议升级为 `brain-web/2`；摘要从原始 JSON 计算 RFC 8785 JCS + SHA-256；`scene_sub_version` 纳入四元组且不回写旧文档 | 同上：raw digest、子版本差异、原始字段不丢失 |
| A3 ID/相机/能力 | `done` | uint32 上限、对象 ID 申领、相机绑定、能力名称和相机帧四元组身份 | `brain_tests/test_brain_web2_scene.py`；Gateway 代码路径静态检查 |
| A4 阶段/事务/恢复 | `done` | `setup`/`agent_owned`、词典序版本判据、`manual_edit_forbidden`、事务 journal、明确拒绝与 unknown 分离、`/resolveUncertain` | 核心场景与服务回归；真实 Gateway 联调 `skip` |
| A5 桩服务/产物 | `done` | 增加无 Qwen 的 `scripts/brain_stub_service.py`；白名单产物；任务结果区分 `clarification_required` 与 `plan_ready` | `conda run -n robot_agent_integ pytest -q brain_tests/test_brain_web2_stub.py`：1 passed |
| A6 健康/终态 | `done` | `/health` 保持进程存活即 HTTP 200，增加 `browser_id`/`tasks`；任务状态不按名称判终态，统一返回 `terminal` | 新增桩服务未知状态测试；真实依赖不可达场景 `skip` |

## 当前验收边界

已支持单活动浏览器下的协议解析、场景摘要、会话/幂等任务、场景事务接口、结果与受限
产物下载，以及 Brain 侧的恢复锁定逻辑。机器人结果仍然是 `executed=false`；本期不接
Control、轨迹执行、IK、物理抓取或双臂执行。

以下项目必须等前端新发布包后再验收：

- Gateway `brain-web/2` 的真实 `commitWorld`、租约、ID 分配与回读；
- 浏览器 `setup`/`agent_owned` 编辑闸门、持久 browser ID、多标签页只读规则；
- 真实截图、2D AABB、视觉消歧和 Qwen 图像请求；
- 七份 OLS 场景的真实资源目录核对。

## 测试说明

推荐使用 Python 3.12 的 `robot_agent_integ` 环境。当前新增测试命令：

```bash
conda run -n robot_agent_integ pytest -q \
  brain_tests/test_brain_web2_scene.py \
  brain_tests/test_brain_web2_stub.py \
  brain_tests/test_shared_scene_contract.py \
  brain_tests/test_application_artifacts.py
```

最近一次新协议/核心兼容输出：

```text
14 passed
```

`test_shared_scene_contract.py` 中 `missing_joint_limits` 仍是旧版严格 Schema
断言；brain-web/2 规范明确允许缺少 `joint_limits`，因此该旧断言应在后续测试迁移中删除，
不是新协议失败。

旧版 `brain-web/1` Gateway fixture 若要求旧能力集合或旧终态语义，属于协议不兼容的历史
测试，不作为 `brain-web/2` 联调通过证据。
