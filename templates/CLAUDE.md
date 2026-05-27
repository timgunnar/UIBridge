# CLAUDE.md — 企业 UI 自动化项目 Agent 对接文件

将本文件放到企业项目的根目录，Claude Code 启动时会自动加载。
Agent 通过本文件了解如何调用 uibridge 框架知识翻译层。

## uibridge 简介

uibridge 给企业 UI 自动化框架装上 AI 接口。它学习你团队的框架封装（TableAW、@FindBy
等），把浏览器操作翻译成符合团队风格的分层测试代码 — ComponentAW → BusinessAW →
TestScript + TestData，人和 AI 都能持续维护。

## 对接方式：MCP Server

在项目 `.mcp.json` 中注册 uibridge：

```json
{
  "mcpServers": {
    "uibridge": {
      "command": "python",
      "args": ["-m", "uibridge.mcp_server"]
    }
  }
}
```

注册后 Agent 获得 21 个类型化 MCP 工具：

### 录制工具

| 工具 | 用途 |
|------|------|
| `open_browser(url)` | 打开可见浏览器（不录制），用户预置操作 |
| `start_recording()` | 在已打开的浏览器上开始录制 |
| `stop_recording(output_file?)` | 停止录制，保存文件，关闭浏览器 |
| `analyze_page(url)` | 无头分析页面组件结构 |

### 生成工具

| 工具 | 用途 |
|------|------|
| `generate_test_code(input_file?, output_dir?)` | 生成分层测试代码 + 自检 |
| `diff_snapshots(input_file?)` | 对比快照，生成断言候选 |
| `review_generated_code(session_id, feedback)` | 代码审查反馈 |
| `regenerate_code(session_id)` | 从持久化 IR 重新生成 |
| `regenerate_from_session(session_id)` | 从录制会话重新生成 |

### 知识库工具

| 工具 | 用途 |
|------|------|
| `seed_knowledge_base(project_dir?)` | 扫描源码播种 KB |
| `query_knowledge_base(query)` | 搜索 KB 条目 |
| `update_knowledge_base(instruction)` | NL 对话式 KB 增删改查 |
| `add_kb_rule(category, key, value, description?)` | 添加 KB 规则 |
| `modify_kb_rule(category, key, value)` | 修改 KB 规则 |
| `delete_kb_rule(category, key)` | 删除 KB 规则 |
| `query_kb_rules(category?, query?)` | 结构化查询 KB 规则 |

### 画像工具

| 工具 | 用途 |
|------|------|
| `get_profile()` | 获取当前项目框架画像 |
| `update_profile(field, value)` | 更新画像字段 |
| `get_project_layout()` | 获取项目布局信息 |

### 环境工具

| 工具 | 用途 |
|------|------|
| `check_environment()` | 检查运行环境（Python、Playwright 浏览器等） |
| `list_sessions()` | 列出历史录制会话 |

## 项目框架信息

- **语言/框架**: Java + TestNG + Maven  <!-- 按实际修改 -->
- **源码目录**:
  - 页面对象: `src/main/java/**/pages/`
  - 测试代码: `src/test/java/**/tests/`
  - 测试数据: `src/test/java/**/data/`

## 工作流

### 首次接入

1. 确保 uibridge 已安装：`pip show uibridge`
2. 调用 `check_environment()` 验证运行环境
3. 调用 `seed_knowledge_base(project_dir=".")` 扫描项目源码，播种知识库
4. Agent 报告发现了多少组件、页面、约定

### 录制新功能测试

1. 调用 `open_browser(url=...)` 打开可见浏览器
2. 告诉用户"浏览器已打开，请先做预置操作（登录、导航等），准备好后告诉我"
3. 等待用户告知预置完成
4. 调用 `start_recording()` 开始录制
5. 告诉用户"录制中，请操作。完成后告诉我"
6. 等待用户告知操作完成
7. 调用 `stop_recording()` 结束录制，保存 recording.json
8. 调用 `generate_test_code()` 生成代码 + 自检
9. 报告用户结果。鼓励用户审查生成的代码，如有问题告知 Agent 修正

### 维护已有测试

1. `analyze_page(url=...)` 了解当前页面组件
2. 重新录制受影响的功能
3. `generate_test_code()` 重新生成
4. 通过 `query_knowledge_base()` 或 KB CRUD 工具更新知识库

### 知识库维护

KB 存储在 `.uibridge/kb/` 下，YAML 格式，可读可改可 commit。

- 查询："表格组件的定位方式是什么？" → `query_knowledge_base("表格 定位")`
- 添加："新增规则：弹窗用 role='dialog' 识别" → `add_kb_rule(...)`
- 修改："定位器应该用 data-testid" → `modify_kb_rule(...)`
- 删除："删掉登录流程的规则" → `delete_kb_rule(...)`
- NL 对话式操作（自动识别意图）：`update_knowledge_base("定位器优先级改为 data-testid > id")`

KB 会随使用持续演化 — 自检通过的 knowledge confidence 上升，失败则下降。

## 关键约定

- 录制文件默认 `recording.json`，保存在项目根目录
- 生成代码默认输出 `generated/`，然后移入正确的源码目录
- 包名从项目结构自动推断，无需手动配置
- 生成的代码风格通过 StyleLearner 从项目已有测试自动学习
