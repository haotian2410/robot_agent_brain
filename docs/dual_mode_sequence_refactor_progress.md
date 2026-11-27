# 双臂时序与模式锁重构进度

依据：`robot_agent_brain_dual_mode_sequence_refactor_plan.md` v2.0。
本计划取代旧布局/双臂方案中共享资源、hold、sync及隐式对象依赖要求。

## 最终状态

最终结果以 `dual_mode_sequence_acceptance.md` 为准：附件第12节本轮代码验收完成。
Python3.11/3.12均2037通过、31跳过；wheel、独立安装smoke、隔离HTTP health通过。
真实双臂Control 4.1联调未完成，未重启生产服务，未提交或推送。
下文为历史检查点，“尚未完成”和失败数量描述当时状态；失败证据保留。

## P0 基线（2026-11-27）

- 实际基线：`9c0e3da08fd7606b4e07e6f269c3f9d0ce66252b`。
  附件长SHA末尾为`52d`，实际已推送提交末尾为`52b`，使用真实提交。
- 基线Python3.12：1941 passed / 31 skipped，40.14s；
  Python3.11：1941 passed / 31 skipped，34.44s。
- 独立安装wheel smoke和understanding smoke通过；隔离HTTP启动/health为200。
- 基线真实布局/复合事务与v4模拟合同证据见旧验收审计；
  真实Control v4合同发现和执行未完成，不作为本次4.1已支持的证据。
- 原引用扫描：325 matches / 255 matched lines / 54 files，
  范围src、brain_tests、tests、docs；tests目录不存在，不据此遗漏brain_tests。
  重点迁移模块：commands_dag_v4、dual_arm_dag、dual_v4_planner、
  dual_v4_holds、task_expander、task_intent、task_understanding、
  pipeline、brain_session、robot_profile、ControlSkillContract、旧v3 planner及prompt。

## 已完成的局部实现

### 最新全量与安装检查点

- Python3.12全量2017通过/31跳过（38.68s），Python3.11全量2017通过/31跳过
  （33.02s）；XML在`var/dual-sequence-refactor/full-312.xml`和`full-311.xml`。
- 全量运行期间补充original派生同步mode lock revision修复，两版本该模块4项通过；
  该小修复晚于全量启动，不能声称上述全量覆盖了这段新增代码。
- 最新wheel：`/tmp/brain-sequence-final-review/dist/robot_agent_brain-0.1.0-py3-none-any.whl`，
  SHA256 `340a6623ae9cacd4836d041db2ae2a0c1bd25453299f5f6f459bcf6458d19687`。
  仓库外独立3.12和3.11环境wheel_smoke、wheel_understanding_smoke全部通过。
  安装包隔离HTTP `/health` 为200，未调用模型或Control。
- CLI schema入口导出commands_v41；旧staged prompt已从资源删除。
  旧v3模型保留历史读取，planner和dispatch入口均明确拒绝。
- 尚需按附件逐项完成覆盖审计，尤其单/双臂布局复合、首轮初始化来源、
  mode与场景事实冲突、受控外部变更，以及历史模块和文档引用清理。
  当前通过不代表真实双臂Control联调完成。

### 模式锁与prompt迁移补充

- RobotModeLock已接入profile导入、成功结果接受、SessionState保存/恢复及一致性校验。
  首轮配置切换/同profile no-op均经过接受路径；成功后锁定，下一轮不同mode/profile拒绝。
  重建会话后仅左臂任务继续输出4.1，锁定轮次不移动。
- 成功结果planner_trace.robot_mode记录mode/profile/revision/prompt_route/locked_at_turn；
  非规划结果的prompt_route为null，避免把编辑描述为调用技能模型。
- build_dual_atomic_skill_prompt与单臂读取同一Control源及SHA，使用独立双臂草稿包装。
  旧Qwen/recipe staged planner为明确退役错误入口，无旧生成实现。
- 分臂以operation ID分配，不再使用同对象或持物状态反推锁臂；same_arm_groups
  已从模型请求/输出校验删除。ArmAssignmentStep只保留step_id/arm。
- 最新全量检查1945通过/73失败/31跳过，含运行时迁移前旧fixture失败；
  此后已迁移显式依赖与首轮配置测试，尚未重跑全量，不能宣称无回归。
  模式锁/配置/application专项26通过（3.12），模式锁16通过（3.11）。

### 运行时迁移检查点

- `commands_dag_v4` 旧Python导入名现在只导出4.1模型；旧4.0文件不隐式升级。
  公共schema已重新生成，replay按4.1选择模型。
- `dual_arm_dag` 入口改为4.1序列构建器；`dual_v4_planner`删除资源窗口、
  sync和hold调用，`dual_v4_holds.py`已删除。ControlSkillContract拒绝旧调度能力字段。
- Pipeline双臂运行路径仅接受4.1，不再调用旧v3 planner；旧模块本身及其反馈路径
  仍待P6清理。实际dispatch保持未注册adapter拒绝，不伪造Control支持。
- TaskExpander的非串行模式仅保留显式依赖，不再按同物体/参照物推导边。
- 第一轮Full/Compact、TaskIntent/GroundedTask删除hold/parallel/same_arm字段；
  Prompt同步移除旧输出要求。旧Compact短码退役但其他码不重新编号。
  技能parameters不做递归删除。
- 两版本协议/规划/应用专项各133项通过；3.12布局/复合/U回归113项通过；
  加5项语义边界后3.11对应118项通过，3.12新增5项亦通过。
- 重构中全量首次结果：123失败、1865通过、31跳过；移除旧测试fixture中的空hold
  字段并回归后，缓存失败重跑仍有68项失败，证据为
  `var/dual-sequence-refactor/remaining-migration.xml`。
  剩余主要是旧v3、调度语义、恢复fixture和same_arm测试；不能据专项通过宣称全量完成。
- 未重启服务、未提交推送，当前源码为迁移中间态，不作为可发布版本。

- 新增`commands_sequence_v41.py`：封闭4.1传输模型、禁止共享调度字段、
  command唯一性、依赖引用/环、同臂顺序、operation臂身份及序列完整性。
  不递归修改技能parameters；参数合法性留给真实Control技能schema。
- 新增`dual_arm_sequence.py`：同臂结构边与显式operation依赖转换；
  不读取对象相同、目的地相同、持物或并行字段推导边。
- 模型文件自身不携带请求operation清单，因此operation完整覆盖在builder
  对原请求校验，不能由文件自行猜测。
- 两版本专项各56项通过。未切运行时、未修改控制端、未重启服务。

## 尚未完成（不得当作发布验收）

1. 4.1协议及主路径已接入；继续清理旧模块引用与导出文档。
2. 完成分臂模型旧same-arm字段及旧恢复路径的迁移，不能用删除回归覆盖代替实现。
3. 首轮RobotModeLock、持久化、重启恢复、同profile no-op及后续切换拒绝。
4. 单/双臂共用Control技能来源、独立短wrapper与固定prompt路由。
5. 移除旧v3运行时并检查外部导入，迁移schemas/replay/wheel测试。
6. 单/双臂复合布局的新版本绑定和失败保留场景回归。
7. 全量3.11/3.12、打包、隔离HTTP/规划测试和最终验收。

当前新模块是迁移中的目标实现，不是并行保留两套生产协议的最终设计。
现有服务仍运行原版本，不宣称已启用4.1或真实双臂控制。
