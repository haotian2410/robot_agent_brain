# B01–B06 协议修订（2026-10-26）
适用：brain-web/2 的 Brain 与 Gateway 配套部署。未接 Control；plan_ready 始终 executed=false。

## 提交、租约和恢复
- Agent 持租约提交：同 ID 版本 +1；新 ID（original 或 bootstrap）版本 1；sub-version=0。expected 四元组仍完整 CAS。
- 事务幂等键同时约束 session、browser、expected 和完整目标文档。不同请求复用事务返回冲突。
- 可归属、未派发写入的确定性拒绝持久化 rejected；prepared 对外仍是 unknown，不能因超时推断失败。Brain 仅在完整拒绝回执且实时读回未改变时维持 synchronized。
- 租约错误只在响应含匹配 sessionID/browserID/taskID 和 lease_status=not_granted 时证明未授予；单独 HTTP 503 不构成证据。
- 浏览器 POST /api/agent/recover 提交当前 sessionID/browserID，由 Brain /resolveUncertain 查本会话最新终态任务，再向 Gateway 提交 taskID、transactionID、expected_digest。
- Gateway 回读 Brain 任务结果与所属会话、检查租约/事务；无回执时必须有权威 write_attempted=false。先持久化任务 fence 和旧 token，再读取现场四元组。旧任务不能再次 acquire，旧 token 不能 commit。
- 不依赖调用者 late_write_excluded=true。写入未知、历史回执缺失且无未写证明、现场不一致继续 kept_locked。prepared 不改写成 rejected。
- 后台任务提交只更新本会话快照，不覆盖当前显示的其他会话。
- UI 分离“服务可达”和“会话待恢复”；恢复失败保留原因，不通过新建会话或重启强制解锁。

## 查询与反馈
SceneQueryIntent 新增 neighbors / relation / selection：
- neighbors.target 是参照物；排除平台、自身、承载/内部/投影重叠。query_near_distance_m 默认 0.2，按水平 AABB 边界间距，答案标范围。
- relation 明确 target/reference/predicate，分别唯一绑定后返回是/否。缺证据不返回否。
- selection 的 relations 必须含显式筛选条件；最近/最远按水平中心距离，保留所有并列对象、稳定 ID、距离。
- Qwen 把完整 selection 关系放到根层时，仅移动其容器位置；仍严格验证，绝不补缺失参照。机器人空间关系协议不放松。
- imported 宽泛类别和新添加精细类别的同名实体合并为候选，避免漏计旧对象。
- evidence_source=image 时要求真实帧和视觉核对；未取得证据返回澄清，不声称看过图。
- 盒子不猜映射；歧义列候选，缩放拒绝保留具体限制。详细模型校验保留本机诊断，不作为页面答案。

## 产物和相机
HTTP artifacts 统一数组：`[{"name":"commands","url":"/tasks/21/artifacts/commands"}]`。
内部路径不公开；旧任务也通过同一出口转换；Gateway 白名单代理不允许任意路径。

Brain 自动相机按明确 overhead_camera_d435i/overhead_camera/top_camera 语义选择，UR5e 为 5；只有一个 Camera 时可选唯一相机。多相机无明确顶视则不猜，非视觉任务不受阻。
每次 original 派生及恢复在当前已确认场景重验相机，不能用上一派生实例 ID 映射冻结原件。返回 camera_selection_reason；不是逐任务可见性评分，不计算附件 FK。

## 验证边界
自动测试、真实 Qwen、真实浏览器分别记录；未跑的断线竞态和旧会话恢复不得记为通过。原资产、冻结 original、旧故障历史不修改；缺证据不补造回执。详见本轮 var/bugfix-b01-b06-20261026 报告。
