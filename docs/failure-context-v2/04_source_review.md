# 本次源码核对与方案变更依据

## 证据边界

- 通过 GitHub 连接器核对远端 main，获得固定 SHA：`3c568c23752418d9c15321fbd321b3696c8eaef5`。
- 核对下列源码的实际正文，不以旧会话摘要代替当前实现。
- 已重读上传的 `robot_agent_brain_context_v1_implementation_plan.md`（224行）和对应 Codex TXT。
- 没有运行本仓库的 pytest、真实 Qwen、OLS、Gateway、浏览器、Control 或物理机器人，也没有提交或推送。
- 附带69项是待执行规格，不是通过报告。文件自检只证明交付包的JSON/编号/链接/ZIP结构可用，不证明业务实现有效。

## 当前源码

所有链接固定到上述提交。

| 编号 | 文件 | 核对结论 |
|---|---|---|
| S1 | [session/dialogue_state.py](https://github.com/haotian2410/robot_agent_brain/blob/3c568c23752418d9c15321fbd321b3696c8eaef5/src/robot_agent_brain/session/dialogue_state.py) | 维护last_entity_id/ids、代词、另一个，仍不是完整历史与失败链 |
| S2 | [session/store.py](https://github.com/haotian2410/robot_agent_brain/blob/3c568c23752418d9c15321fbd321b3696c8eaef5/src/robot_agent_brain/session/store.py) | SessionState可扩展；执行恢复和对话失败续接应分开 |
| S3 | [application.py](https://github.com/haotian2410/robot_agent_brain/blob/3c568c23752418d9c15321fbd321b3696c8eaef5/src/robot_agent_brain/application.py) | _handle会begin_turn；公开服务在理解后拒绝未就绪双臂；请求产物是子步骤证据 |
| S4 | [web/service.py](https://github.com/haotian2410/robot_agent_brain/blob/3c568c23752418d9c15321fbd321b3696c8eaef5/src/robot_agent_brain/web/service.py) | execute支持拆分、dispatch；_run_steps保留成功前缀；MAX_STEP_ATTEMPTS=5；final结果晚于app.handle |
| S5 | [pipeline.py](https://github.com/haotian2410/robot_agent_brain/blob/3c568c23752418d9c15321fbd321b3696c8eaef5/src/robot_agent_brain/pipeline.py) | understand_turn、decompose、process_turn为复用入口；正常请求仍主要为原指令/场景/目录 |
| S6 | [grounding/scene_grounder.py](https://github.com/haotian2410/robot_agent_brain/blob/3c568c23752418d9c15321fbd321b3696c8eaef5/src/robot_agent_brain/grounding/scene_grounder.py) | GroundingAmbiguous携带候选；当前动作路径启用allow_description_fallback |
| S7 | [grounding/semantic_entity_selector.py](https://github.com/haotian2410/robot_agent_brain/blob/3c568c23752418d9c15321fbd321b3696c8eaef5/src/robot_agent_brain/grounding/semantic_entity_selector.py) | 存在ignore_colour/relax_colour及tag最高分候选；新自动策略不能把这些当完全满足条件 |
| S8 | [models/task_understanding.py](https://github.com/haotian2410/robot_agent_brain/blob/3c568c23752418d9c15321fbd321b3696c8eaef5/src/robot_agent_brain/models/task_understanding.py) | 原TaskUnderstandingRequest仍是严格v3.1输入；正常契约无需增历史 |
| S9 | [models/qwen_http.py](https://github.com/haotian2410/robot_agent_brain/blob/3c568c23752418d9c15321fbd321b3696c8eaef5/src/robot_agent_brain/models/qwen_http.py) | 现有理解/修复/decompose调用与trace应保持；额外R需要独立stage和raw evidence |
| S10 | [ports/execution.py](https://github.com/haotian2410/robot_agent_brain/blob/3c568c23752418d9c15321fbd321b3696c8eaef5/src/robot_agent_brain/ports/execution.py) | ExecutionOutcome有步骤、moved、holding、traj，尚不能仅用ok=false判断无副作用 |
| S11 | [contracts/release_policy.py](https://github.com/haotian2410/robot_agent_brain/blob/3c568c23752418d9c15321fbd321b3696c8eaef5/src/robot_agent_brain/contracts/release_policy.py) | 继续禁止对话平台变更；不能套用旧附件“所有Control始终关闭”的设计前提 |
| S12 | [web/protocol.py](https://github.com/haotian2410/robot_agent_brain/blob/3c568c23752418d9c15321fbd321b3696c8eaef5/src/robot_agent_brain/web/protocol.py) | StartTask与SessionRequest extra=forbid；新可选参数需显式声明，幂等仍用clientRequestID |

## 旧附件与本版的明确区别

| 项目 | 旧附件 v1 | 本版 v2 |
|---|---|---|
| 正常调用 | 给原U追加最近5轮 | 正常U不加历史，只留档 |
| 失败续接 | 同一U综合理解 | 独立R整理，再进入原U验证 |
| 上下文范围 | 最近五轮滚动窗口 | 从首失败轮起的同一任务链，最多五次失败用户轮 |
| 非歧义失败 | 以语义补全为主 | 类型化区分用户可改写、环境阻断、未知副作用、部分执行 |
| 完成事实 | 多为计划与单场景编辑 | 必须等Web外层dispatch/writeback/finally结果 |
| 多步骤 | 主要讨论单次原子语义 | 当前已有逐步提交，需要成功前缀防重放 |
| 候选策略 | 默认询问 | 二值开关，但auto只选严格合法、允许替代的actor |
| 附件验收 | CT01～CT27 | FR01～FR69，全部待执行 |

## 外部工程原则（不是仓库实现声明）

AWS官方文档指出重试应考虑幂等性；带副作用的请求在超时后可能已经完成，不能仅凭失败结果反复调用。本方案据此要求未知事务先核验、同一逻辑任务选择和提交具备持久身份，不因此引入任何AWS依赖。

- [Retry with backoff pattern](https://docs.aws.amazon.com/prescriptive-guidance/latest/cloud-design-patterns/retry-backoff.html)
- [Making retries safe with idempotent APIs](https://aws.amazon.com/builders-library/making-retries-safe-with-idempotent-APIs/)
