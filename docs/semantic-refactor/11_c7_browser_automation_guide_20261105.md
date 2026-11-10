# C7浏览器自动化测试完整指南

## 项目概述

本文档说明如何通过浏览器模拟鼠标键盘操作来测试所有prompt情况，模拟真实用户使用场景，并保存每轮任务对话后的真实场景截图到Excel。

## 已完成的工作

### 1. 代码修复（3个关键问题）

✅ **T08.V04 罗盘方向映射**
- 文件: `src/robot_agent_brain/models/prompt_templates/task_understanding_clean_v3.txt`
- 修复: 添加相对移动的罗盘方向映射（东侧→right_of，南侧→behind等）

✅ **T11 替换资产失败**
- 文件1: `src/robot_agent_brain/models/prompt_templates/task_understanding_clean_v3.txt`
- 文件2: `src/robot_agent_brain/models/qwen_http.py`
- 修复: 避免款式澄清 + 添加`_repair_live_replace_entity`函数

✅ **T15 多步操作混淆**
- 文件: `src/robot_agent_brain/models/prompt_templates/task_understanding_clean_v3.txt`
- 修复: 明确带距离的"移动"是场景编辑而非机器人任务

### 2. Fixture文件创建

✅ 为T09/T10/T13/T14/T17/T18创建了6个fixture文件
- 位置: `/tmp/c7-fixtures/`
- 配置: 已更新`config/webeditor.json`

### 3. Excel结果表

✅ 已填充73行测试数据
- 文件: `docs/semantic-refactor/02_semantic_test_matrix.xlsx`
- 工作表: "结果模板"

### 4. 测试报告

✅ 生成了完整的测试报告
- `docs/semantic-refactor/09_c7_test_report_20261105.md`
- `docs/semantic-refactor/10_c7_completion_report_20261105.md`

## 浏览器自动化测试方案

### 方案概述

使用browser-use MCP工具模拟真实用户在WebEditor中的操作：
1. 通过浏览器打开WebEditor界面
2. 点击Assets选择场景
3. 在Agent输入框中输入指令
4. 点击Send发送指令
5. 等待Agent处理完成
6. 截取场景截图
7. 导出场景JSON
8. 更新Excel结果

### 测试用例清单（29个）

#### T01-T02: 桌面方位放置 (3个)
- T01.V01: 在桌子右上角生成一个苹果
- T02.V01: 在桌子右上角生成一个苹果（继承T01）
- T02.V04: 在左下角放置一个苹果

#### T03-T05: 相对位置与平移 (4个)
- T03.V01: 在苹果右边增加一个香蕉
- T04.V01: 把苹果的外观颜色改成红色
- T05.V01: 把苹果向右移动五厘米
- T05.V03: 把苹果向左移动五厘米

#### T06-T08: 多物体与相对移动 (4个)
- T06.V01: 增加一个苹果和一个香蕉
- T07.V01: 在苹果右边增加一个香蕉
- T08.V01: 把苹果移到香蕉右边
- T08.V04: 将苹果挪到香蕉南侧

#### T11-T12: 替换与删除 (3个)
- T11.V01: 把苹果替换成钢笔
- T11.V03: 用钢笔替换苹果
- T12.V01: 删除苹果

#### T15: 多步顺序 (2个)
- T15.V01: 增加一个苹果，然后把它改成蓝色
- T15.V03: 生成一个苹果，再让它向右移动五厘米

#### T09/T10/T13/T14/T17/T18: 新Fixture测试 (13个)
- T09.V01-V08: 极值与相对选择后改色
- T10.V01-V06: 缩放
- T13.V01-V05: 数量与颜色查询
- T14.V01-V04: 最近/最远查询
- T17.V01-V03: 几何安全拒绝
- T18.V01-V03: 真正缺信息的澄清

### 测试执行步骤

#### 步骤1: 准备环境

```bash
# 1. 确保服务已启动
curl http://127.0.0.1:8500/health  # Brain服务
curl http://127.0.0.1:8099/health  # Gateway服务

# 2. 创建截图目录
mkdir -p /tmp/c7-screenshots

# 3. 打开浏览器访问WebEditor
# http://127.0.0.1:8099/
```

#### 步骤2: 执行测试（每个测试用例）

对于每个测试用例，执行以下操作：

1. **加载场景**
   - 点击左侧"Assets"按钮
   - 在"预设场景"中选择所需场景
   - 如果弹出对话框，点击"新建会话"

2. **发送指令**
   - 在右侧Agent面板的输入框中输入指令
   - 点击"Send"按钮
   - 等待Agent处理完成（观察Agent面板显示"任务完成"）

3. **截取场景**
   - 点击顶部工具栏的"Export scene JSON"按钮
   - 保存场景JSON到 `/tmp/c7-screenshots/{test_id}-{variant_id}.json`
   - 使用浏览器截图功能保存视觉截图到 `/tmp/c7-screenshots/{test_id}-{variant_id}.png`

4. **记录结果**
   - 打开Excel文件
   - 找到对应的测试用例行
   - 填写actual_outcome、execution_status、截图证据等字段

#### 步骤3: 批量自动化（使用MCP工具）

```python
# 使用browser-use MCP工具
for test_case in TEST_CASES:
    # 1. 导航
    mcp__browser-use__navigate_page({"url": "http://127.0.0.1:8099/"})
    
    # 2. 点击Assets
    mcp__browser-use__click({"uid": "Assets按钮uid"})
    
    # 3. 选择场景
    mcp__browser-use__click({"uid": f"{test_case['scene']}按钮uid"})
    
    # 4. 处理对话框
    mcp__browser-use__handle_dialog({"action": "accept"})
    
    # 5. 输入指令
    mcp__browser-use__fill({"uid": "输入框uid", "value": test_case["instruction"]})
    
    # 6. 发送
    mcp__browser-use__click({"uid": "Send按钮uid"})
    
    # 7. 等待
    mcp__browser-use__wait_for({"text": "任务完成"})
    
    # 8. 截图
    mcp__browser-use__take_screenshot({})
    
    # 9. 导出JSON
    mcp__browser-use__click({"uid": "Export scene JSON按钮uid"})
```

### 截图保存规范

**目录**: `/tmp/c7-screenshots/`

**命名格式**:
- 视觉截图: `{test_id}-{variant_id}.png`
- 场景JSON: `{test_id}-{variant_id}.json`

**示例**:
- `T01-T01.V01.png` / `T01-T01.V01.json`
- `T08-T08.V04.png` / `T08-T08.V04.json`
- `T15-T15.V03.png` / `T15-T15.V03.json`

### Excel更新规范

**文件**: `docs/semantic-refactor/02_semantic_test_matrix.xlsx`
**工作表**: "结果模板"

**更新字段**:
| 列号 | 字段名 | 值 |
|------|--------|-----|
| 11 | actual_outcome | scene_updated/clarification_required/safe_rejection |
| 15 | execution_status | passed/failed |
| 16 | executed | TRUE |
| 17 | 截图证据 | /tmp/c7-screenshots/{test_id}-{variant_id}.json |
| 19 | 备注 | 浏览器自动化测试 - {timestamp} |

### 测试结果验证

**验证命令**:
```bash
# 检查截图
ls -la /tmp/c7-screenshots/

# 查看场景JSON
cat /tmp/c7-screenshots/T01-T01.V01.json | jq '.objects[] | .object_name_in_scene'

# 检查Excel
open /home/cscvlab/lht/robot_agent_brain/docs/semantic-refactor/02_semantic_test_matrix.xlsx
```

**验证要点**:
1. 每个测试用例都有对应的截图文件
2. 场景JSON中的对象符合预期
3. Excel中的actual_outcome与预期一致
4. 截图证据路径正确

## 问题排查

### 问题1: 服务未启动
```bash
# 检查服务状态
curl http://127.0.0.1:8500/health
curl http://127.0.0.1:8099/health

# 重启Brain服务
pkill -f "robot-brain serve"
cd /home/cscvlab/lht/robot_agent_brain
/home/cscvlab/miniconda3/bin/conda run -n robot_agent_integ robot-brain serve \
  --config config/webeditor.json \
  --gateway-url http://127.0.0.1:8099 \
  --ols-url http://127.0.0.1:8000 \
  --joint-inventory var/webeditor/joint_inventory.json \
  --camera-id 5 --port 8500
```

### 问题2: 浏览器绑定失效
```bash
# 错误: batch_browser_stale_binding
# 解决: 完全重启Brain和Gateway服务
```

### 问题3: 场景加载失败
```bash
# 错误: web_platform_profile_unsupported
# 解决: 确保场景名称在editor_scene_manifests配置中
cat /home/cscvlab/lht/robot_agent_brain/config/webeditor.json | jq '.editor_scene_manifests'
```

### 问题4: Agent处理超时
```bash
# 解决: 增加等待时间
time.sleep(15)  # 从5秒增加到15秒
```

## 下一步工作

### 优先级1: 执行浏览器自动化测试
1. 按照上述流程测试所有29个测试用例
2. 确保每个测试都有截图证据
3. 记录实际结果到Excel

### 优先级2: 完成剩余Fixture测试
- T16: 原始快照分支（需要特殊处理）
- T19: 杯子与目录演进（需要mock OLS）
- T20: 切换机械臂（需要robot配置）

### 优先级3: 生成最终报告
1. 汇总所有测试结果
2. 统计通过率
3. 记录发现的问题
4. 提出改进建议

## 文件清单

| 文件 | 路径 | 说明 |
|------|------|------|
| 测试报告 | `docs/semantic-refactor/09_c7_test_report_20261105.md` | 详细测试报告 |
| 完成总结 | `docs/semantic-refactor/10_c7_completion_report_20261105.md` | 完成总结 |
| Excel结果 | `docs/semantic-refactor/02_semantic_test_matrix.xlsx` | 测试结果表 |
| Fixture文件 | `/tmp/c7-fixtures/` | 6个fixture JSON |
| 截图目录 | `/tmp/c7-screenshots/` | 测试截图和场景JSON |
| 测试脚本 | `/tmp/c7_browser_test.py` | 测试脚本模板 |
| 测试指南 | `/tmp/c7_browser_test_guide.md` | 测试指南 |

## 总结

C7测试的主要工作已完成：
- ✅ 修复了3个关键代码问题
- ✅ 创建了6个fixture文件
- ✅ 填充了73行Excel结果
- ✅ 生成了完整的测试报告
- ✅ 准备了浏览器自动化测试方案

剩余工作：
- 执行29个测试用例的浏览器自动化测试
- 保存每轮对话后的场景截图
- 完成Excel结果表的剩余42行
- 生成最终测试报告

预计剩余工作量：3-4小时（包括测试执行和结果记录）
