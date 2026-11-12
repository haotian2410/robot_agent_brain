# 联调栈启动与交接说明（2026-11-12）

面向接手本仓库的 agent / 工程师。本文所有命令、端口、pid、文件路径均为交接当天的实测
值，不是设想；文末"未决事项"是交接时仍未闭合的部分。

配套细读：[docs/scene_scale_color.md](scene_scale_color.md)（缩放/颜色/选择规则）、
[docs/contracts.md](contracts.md)（协议契约）、
[docs/webeditor_integration.md](webeditor_integration.md)（大脑↔网关接线）。

## 1. 当前运行态快照

| 进程 | 端口 | cwd | 探活 |
|---|---|---|---|
| `llama-server`（Qwen3.8-27B 视觉+文本） | 127.0.0.1:8080 | `/home/cscvlab/lht` | `GET /health` 200 |
| ObjectLibraryServer（资产目录） | 0.0.0.0:8000 | `/home/cscvlab/lht/ObjectLibraryServer` | `GET /list?type=model&uid=0` 200（**没有** `/health`） |
| web-frontend `local_gateway.py`（场景真值+浏览器+SPA+大脑作业 API） | 0.0.0.0:8099 | `/home/cscvlab/lht/web-frontend-master` | `GET /health` 200 |
| `robot-brain serve`（大脑） | 127.0.0.1:8500 | `/home/cscvlab/lht` | `GET /health` 200 |

仓库状态（HEAD 与工作区脏度，接手前先看清）：

```
robot_agent_brain    main   05c43e2 2026-11-10  dirty=107
web-frontend-master  master c182148 2026-11-11  dirty=11
ObjectLibraryServer  master f6f7497 2026-11-10  dirty=1
robot_agent_control  main   414195b 2026-11-12  dirty=8
robot_agent_link / robot_agent_workspace        非 git 目录
```

大脑是 **editable 安装**（`.../src/robot_agent_brain/__init__.py` 被加载），改源码只需
重启服务，不需要重新打包。

## 2. 启动命令（照抄可用）

```bash
PY=/home/cscvlab/miniconda3/envs/robot_agent_integ/bin/python

# 1) 模型（最大瓶颈，先起）。正式入口是
#    QWEN38_CTX_SIZE=32768 robot_agent/scripts/start_qwen38_vlm.sh；下面是它实际执行的 argv
/home/cscvlab/llama.cpp/build/bin/llama-server \
  --model /home/cscvlab/models/qwen3.8-27b/Qwen3.8-27B-UD-Q4_K_M.gguf \
  --mmproj /home/cscvlab/models/qwen3.8-27b/mmproj-BF16.gguf \
  --host 127.0.0.1 --port 8080 --ctx-size 32768 --n-gpu-layers 999 \
  --image-min-tokens 1024 --reasoning off

# 2) 资产目录
cd /home/cscvlab/lht/ObjectLibraryServer && $PY server.py          # :8000

# 3) 网关（SPA 走 dist/，改前端后要先 npm run build）
cd /home/cscvlab/lht/web-frontend-master && $PY local_gateway.py --port 8099

# 4) 大脑（后台跑时日志追加到 /tmp/brain_8500.log）
cd /home/cscvlab/lht && $PY /home/cscvlab/miniconda3/envs/robot_agent_integ/bin/robot-brain serve \
  --config robot_agent_brain/config/webeditor.json \
  --gateway-url http://127.0.0.1:8099 \
  --ols-url http://127.0.0.1:8000 \
  --joint-inventory robot_agent_brain/var/webeditor/joint_inventory.json \
  --camera-id 5 --port 8500
```

停大脑**只按 pid**：

```bash
ss -ltnp | grep ':8500'          # 取 pid=
kill <pid>
```

不要用 `pkill -f "robot-brain serve"`——它会连当前 shell 一起杀掉（命令行包含同样
的字符串）。

上下文长度：交接时运行的 llama-server 带 `--ctx-size 32768`，且它自己的进程 env 里有
`QWEN38_CTX_SIZE=32768`（实测），即由 `robot_agent/scripts/start_qwen38_vlm.sh` 启动。
该脚本第 11 行的默认只有 **16384**，浏览器场景一轮约 21 000 prompt tokens，默认值会让
llama-server 直接 HTTP 400，在大脑侧只表现为 `canonical_v3_rejected / provider_error`。
所以重建模型时**必须**先 `export QWEN38_CTX_SIZE=32768`。大脑与网关进程 env 里没有这个
变量（实测），它不参与大脑/网关，只管模型启动。

## 3. `config/webeditor.json` 关键项

- `provider` / `planner` = `qwen`，`base_url` = `http://127.0.0.1:8080/v1`，
  `model` = gguf 绝对路径，`timeout` = 300。
- `asset_library_root` = `../../webeditor_runtime/ObjectLibraryServer-1.0.8-rel/data`
  ——大脑按**文件**读目录索引（`model_index.json`/`robot_index.json`/`scene_index.json`），
  同时按 `--ols-url` 走 `/list` 校验一致性（`web/assets.py:check_ols`）。两侧
  `no_display` 标记必须一致，否则整批资产库测试红。
- `default_table_metadata_ref` = `$LIBRARY_SERVER/29`，`default_robot_metadata_ref`
  = `$LIBRARY_SERVER/1`；`default_scene_edit_assets` 是"新增 X"的资产兜底表（25 项）。
- `default_scene` 指向 `.../data/scenes/1/ur5_table_empty.json`；
  `editor_scene_manifests` 给每个模板场景列出平台对象号。
- 执行五件套：`execution_enabled=true`、`execution_python=.../envs/robot_exec/bin/python`、
  `execution_control_root=/home/cscvlab/lht/robot_agent_control`、
  `execution_library=/home/cscvlab/lht/_thirdparty/SimPlatform-main/build/libsim_platform_c.so`、
  `execution_link_root=/home/cscvlab/lht/robot_agent_link`；
  `execution_workspace_root=/home/cscvlab/lht/robot_agent_workspace`。
  执行授权**只认** `execution_enabled`，在派发入口校验。
- `release_policy`：`dynamic_platform_rebind=false`、`runtime_robot_setup_change=false`、
  `nl_initial_platform_selection=false` —— 平台换绑/运行期换机械臂会被
  `config.release_policy.deny_dynamic_platform()` 挡下。
- `debug=true` 才落 `debug/*` 产物；`output_dir="var/webeditor/tasks"`（相对
  `/home/cscvlab/lht`，实际绝对路径 `/home/cscvlab/lht/var/webeditor/tasks`）。

## 4. 端到端怎么驱动（最容易踩的一环）

浏览器持有**唯一**的场景租约。直接调大脑 `POST :8500/sessions` + `/startTask`
会在 commit 时被网关拒：`scene_lease_required: commitWorld requires the target
session's active lease`。**正确做法是走网关作业 API**，由网关自己持租：

```bash
python /home/cscvlab/lht/var/lian-tiao/drive_five.py "把最右边的苹果放到绿色苹果的上方"
```

脚本做的事：`GET :8099/getWorld`（带 `X-WebEditor-Browser-ID` 头）拿基线场景 →
`POST :8099/api/agent/jobs` → 轮询 `GET :8099/api/agent/jobs/<id>` 直到 `terminal`。

- 当前浏览器 ID：`af196302-c14f-478d-a9f1-f2b6905f6391`（换浏览器要换这个头）。
- 驱动脚本已固定在 `/home/cscvlab/lht/var/lian-tiao/`（`/tmp` 里的原件会随重启丢失，勿再
  依赖）：`drive_five.py`（走网关作业 API，打印整句多任务判定）、`drive_job.py`（单个
  作业 terminal 视图）、`drive_ui.py`（按页面方式跑一条命令）、`drive_task.py`
  （直连大脑 `:8500`，只适合看理解/分解结果，**不能**提交场景）。
- 动手改世界前先备份 live world：`/home/cscvlab/lht/var/lian-tiao/live-world-vN.backup.json`。
  交接时世界 = scene 3 `ur5_table_sorting` **v12**、19 个对象（实测 `/getWorld`）：
  平台件 0-6、14；7 `Apple`(graspable，**带 `forceOverrideColor="#00FF00"`** 即那枚染绿的
  苹果)、8 Banana、9 Marker、10 Screwdriver、11 RubiksCube、12 Basket、13 Tray；
  33 `green_apple`(button)；37/38/39 `apple`(fruit)。所有实例的 `Semantic.tags` 都是
  `null` —— tag 匹配只来自 OLS 目录，不是场景实例，别在场景里找 tags。

## 5. 产物与排查入口

```
/home/cscvlab/lht/var/webeditor/tasks/<sessionID>/<requestID>/
  request_record.json  result.json  scene_config.json
  query_result.json            # 查询路由才有
  debug/brain_turn.json        # 本轮 status/turn_kind/model payload
  debug/task_intent.json       # 有分解时
  debug/semantic_protocol.json # 语义协议快照
  debug/raw_model_response.txt # {"turn_id":..., "<stage>": 原始文本}
  debug/model_calls.json       # prompt_sha256 / asset_catalog_sha256 / token 数 / 耗时
  debug/traceback.txt          # 只在抛异常时存在，直接定位行号
../gateway_transactions/*.json # 网关侧 commit 回执（租约问题看这里）
../traj_playback/              # 执行轨迹（含失败轨迹）
```

`raw_model_response.txt` 现在**按轮隔离**：`turn_id` 等于本 request id，且只含本轮
真实跑过的 stage。看到陌生 stage 或重复 blob 即为回归。

## 6. 测试

```bash
/home/cscvlab/miniconda3/envs/robot_agent_integ/bin/python -m pytest brain_tests -q
```

基线 = **9 个资产库相关失败**（环境性，与逻辑无关，勿当新失败修）：
`test_asset_catalog_v31.py` ×4、`test_reported_scene_add_regressions.py` ×1、
`test_robot_config_noop.py` ×2、`test_scene_default_grid.py` ×1、
`test_web_initial_platform_import.py` ×1。特征是断言里的资产号（如 `model:29`）
不在当前 revision 的 prompt/目录里。

颜色与选择专项：`brain_tests/test_recolored_selection.py`（16 条）、
`test_scene_scale_color.py`、`test_component_runtime.py`。

## 7. 本轮已闭合的改动（含文件位置）

1. **颜色策略 v3**：颜色是软偏好，**永远不因"匹配不到颜色"而报错**。
   - 整批无颜色证据 → 丢掉颜色词、按名称/类别/tag 的主体重选一次
     [semantic_entity_selector.py:108](../src/robot_agent_brain/grounding/semantic_entity_selector.py)；
     `grounding_evidence_missing: color` 已从全链路删除（只保留 tags 那一处）。
   - 读不出来的颜色词（如「彩色」）与非法 override 读作"无证据"，不抛
     `scene_edit_color_unknown` [colors.py:83](../src/robot_agent_brain/scene/colors.py)。
   - `COLOR_POLICY_VERSION = "3"`，随诊断载荷输出。
   - **仍保留**的护栏：某实例确实声明过别的颜色时，"矛盾"照样排除它，因此染过色的
     场景里「有几个红苹果」答 0；批量 `quantity_mode=all`/显式 count 与查询路由
     不做"矛盾退化"（`allow_description_fallback` 只在 `SceneGrounder` 打开）。
   - 无证据时批量也会吃到主体集合（用户裁决"永远"），即整批没染过色的场景里
     「所有红苹果」= 所有苹果。
2. **tags 兜底拓宽**：名字与别名都落空后，再按 tag 重叠打分拓宽一次候选池，取最高分
   集合；只拓宽"找不到"，不改变已有命中。颜色词在打分前从 tags 摘出，仍是硬过滤位，
   所以 33 号青苹果不会因为「绿色」被抓走。
3. **`begin_turn` 按轮隔离**：`models/qwen_http.py` 轮首清 `last_raw_text`/
   `last_raw_values` 并记 `turn_id`，`application.py` 调用之；修掉了
   `debug/raw_model_response.txt` 跨轮跨会话复制。
4. **撤销"上下文补色名"**：理解阶段场景上下文不再给模型派生颜色名（`instance_color_name`
   已删除），因为用户要求模型不得核对场景；`color_override` 原值维持改动前的样子。

## 8. 未决事项（交接给下一位）

- **#73 模型层三句**（大脑侧无法修，
  [src/robot_agent_brain/models/prompt_templates/task_understanding_clean_v3.txt](../src/robot_agent_brain/models/prompt_templates/task_understanding_clean_v3.txt)
  归用户维护，别的 agent 不要动）：
  - 「把最左边的红苹果拿起来」：模型在 understanding 直接返回
    `clarification_required`、`entities=[]`，大脑拿不到请求，退化阶梯无从运行。
  - 「有几个红苹果」「有几个染成绿色的苹果」：模型输出 `color=null, tags=["苹果"]`，
    颜色词丢失 → 大脑按主体数成 4。重启服务后复测仍是这样（`brain_turn.json` 为证）。
  - 「绿色苹果」在任务句里被模型写成目录 slug `green_apple` → 名字门命中目录里的青
    苹果 33，而不是刚染色的 7。
  磁盘上的 prompt 仍是 19:40 那份，用户"不许查场景"的编辑**尚未落盘**。落盘后需要
  重跑第 4 节那三句验收。
- **为什么"染色的苹果"这么难选**（对象清单见第 4 节）：同名不同类 —— 7 是 Scene-v1
  导入的 `Apple`/`graspable`，37/38/39 是浏览器新增的 `apple`/`fruit`，所以"苹果"永远
  是 4 个；33 在 OLS 里挂在 `button` 类下且自己不带颜色证据，只能靠整词「青苹果」命中。
  用户已裁决**不改 OLS 数据**，下一位别把它当 bug 去补 tags。
- **控制端能力下限**（几何/物理归控制端，大脑不校验）：`put` 需要对象落点、抓取半径
  约 18.6 cm、`PLACEMENT_HEIGHT_SEARCH_FAILED`。上一条五步句即止步于此。
- 其余开放任务：#19 浏览器端到端闭环、#43 五步句、#46 五步句四个出口、#53 新增物体
  默认落点、#54 面内侧向落点、#55 面内区域落点、#41 多机械臂步骤。

## 9. 操作禁忌（踩过）

- 不校验几何/碰撞/抓取可行性——那是控制端职责，大脑只做任务分解与语义选择。
- 执行失败要向前端推失败轨迹，但**不更新场景**。
- 停服务按 pid；`pkill -f "robot-brain serve"` 会自杀当前 shell。
- 改世界先备份 live world；场景真值在网关，不在大脑。
- 用户的 prompt 文件不替用户改；要改先问。
