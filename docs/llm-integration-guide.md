# 大模型自对接指南

**将 uibridge 接入你的 AI Agent（Claude Code、自定义 LLM 应用、CI/CD 管道等）。**

---

## 三种对接方式

| 方式 | 适用场景 | 体验 |
|------|---------|------|
| **MCP Server**（推荐） | Claude Code、支持 MCP 的 Agent | 类型化工具，Agent 自动发现 |
| **CLI 命令** | 任何能执行 shell 的环境 | Bash 调用，JSON 输出 |
| **Skill 文件** | Claude Code 斜杠命令 | `/uibridge:record` 等快捷方式 |

---

## 方式一：MCP Server（推荐）

### 原理

```
你的 Agent  ──→  MCP 协议  ──→  uibridge MCP Server  ──→  Playwright 浏览器
              (JSON-RPC)        (FastMCP, 常驻进程)
```

MCP Server 启动后保持常驻，暴露 10 个类型化工具。Agent 通过标准 MCP 协议调用。

### 配置（.mcp.json）

在你的项目根目录创建 `.mcp.json`：

```json
{
  "mcpServers": {
    "uibridge": {
      "command": "python",
      "args": ["-m", "uibridge.mcp_server"],
      "description": "UI 自动化测试脚本智能生成"
    }
  }
}
```

### 可用工具

| 工具 | 参数 | 返回 |
|------|------|------|
| `analyze_page` | `url`, `adapter_config?` | 页面组件列表（类型、XPath、ARIA role） |
| `open_browser` | `url` | `{session_id, status: "browser_ready"}` |
| `start_recording` | `adapter_config?` | `{session_id, status: "recording"}` |
| `stop_recording` | `output_file?` | `{steps: N, file: "recording.json", summary}` |
| `generate_test_code` | `input_file?`, `output_dir?`, `adapter_config?` | 生成代码 + 自检结果 |
| `diff_snapshots` | `input_file?` | 断言候选列表 |
| `seed_knowledge_base` | `project_dir` | KB 播种摘要 |
| `query_knowledge_base` | `query`, `project_dir?` | KB 查询结果 |
| `update_knowledge_base` | `instruction`, `project_dir?` | NL 对话式 KB 增删改查 |
| `check_environment` | (无) | 浏览器等运行环境状态 |

### Agent 工作流（三段式录制）

录制分为三个阶段，对应三次 MCP 调用：

```
1. 调用 open_browser(url="http://localhost:8080/users")
   → 浏览器打开（不录制）。返回 {session_id, status: "browser_ready"}

2. 告诉用户："浏览器已打开，请做预置操作（登录、导航等），准备好后告诉我。"

3. 用户预置完成后，调用 start_recording()
   → 在已打开的浏览器上注入录制脚本，开始捕获。返回 {session_id, status: "recording"}

4. 告诉用户："录制中，请操作。完成后告诉我。"

5. 用户操作完成并告知后，调用 stop_recording()
   → 停止录制，保存 recording.json，关闭浏览器

6. 调用 generate_test_code()
   → 生成代码 + 自检，报告结果
```

**为什么是三段式？** 用户可能需要预置操作（登录、导航到目标页面），这些不应被录制。
MCP 请求-响应模式天然跨越用户多轮对话。三个调用分别对应打开 → 开始录制 → 结束录制。

### 手动启动 MCP Server

```bash
python -m uibridge.mcp_server
# MCP Server 在 stdio 上监听 JSON-RPC 请求
```

---

## 方式二：CLI 命令

适用于无 MCP 支持的环境（CI/CD 管道、自定义脚本、非 Claude Code Agent）。

### 可用命令

```bash
uibridge analyze --url <URL>                     # 分析页面组件
uibridge record --url <URL> --headed -o out.json # 录制操作
uibridge generate -i recording.json -o gen/      # 生成代码
uibridge diff -i recording.json                  # 断言候选
uibridge cleanup --dry-run                       # 预览清理
uibridge cleanup --yes                           # 执行清理
```

### Agent 通过 Bash 调用

Agent 的 CLAUDE.md 中描述 CLI 工作流：

```markdown
## 录制测试（CLI 模式）

1. 如果 MCP 工具不可用，使用 Bash 调用 CLI：
   - `uibridge analyze --url <URL>` 分析页面
   - `uibridge record --url <URL> --headed` 录制（需用户按 Enter 结束）
   - `uibridge generate -i recording.json -o generated/` 生成代码

2. CLI record 命令会阻塞等待用户按 Enter，Agent 在调用前应告知用户。
```

---

## 方式三：Skill 文件

为 Claude Code 提供斜杠命令快捷方式。

### 安装

将 `.claude/skills/uibridge.md` 复制到项目目录：

```bash
cp .claude/skills/uibridge.md /path/to/your-project/.claude/skills/
```

### 效果

用户可输入 `/uibridge:record` 等命令快速触发工作流。

### Skill 文件内容

Skill 文件定义触发词和工作流步骤，详见 `.claude/skills/uibridge.md`。

---

## 接入新 Agent 平台

### 自定义 Agent 集成

如果你的 Agent 不支持 MCP 协议，可通过以下方式集成：

**1. HTTP 包装（需自行实现）**

```python
# 在 MCP Server 外包装 HTTP API
from flask import Flask, request, jsonify
from uibridge.pipeline import Pipeline
# ... 调用 Pipeline 的各个阶段
```

**2. Python SDK 直接调用**

```python
from uibridge.pipeline import Pipeline
from uibridge.adapter.java_testng import (
    JavaComponentResolver, JavaLocatorStrategy,
    JavaActionRecognizer, JavaCodeGenerator, JavaDataFormatter,
)

pipeline = Pipeline(
    JavaComponentResolver(),
    JavaLocatorStrategy(),
    JavaActionRecognizer(),
    JavaCodeGenerator(),
    JavaDataFormatter(),
    project_root="/path/to/project",
)

# 分析页面
with sync_playwright() as pw:
    page = pw.chromium.launch().new_page()
    page.goto("http://localhost:8080/users")
    components = pipeline.discover_components(page)
```

**3. CI/CD 集成**

```bash
# .github/workflows/uibridge.yml
- name: Generate tests from recording
  run: |
    pip install -e /path/to/uibridge
    uibridge generate -i recording.json -o generated/
    mvn test -Dtest=generated/*  # 验证生成的代码
```

---

## 安全注意事项

- MCP Server 在本地运行，不联网（除 `analyze_page` / `start_recording` 访问目标 URL）
- 录制时浏览器为有头模式（用户可见），不会静默录制
- 生成代码写入 `generated/` 目录，不覆盖现有代码
- KB 存储在 `.uibridge/kb/`，为本地 YAML 文件
- 适配器代码在 `uibridge/adapter/` 下，用户可审计

---

## 常见问题

**Q: MCP Server 启动失败？**
A: 确认 `pip install -e .` 已执行，`mcp` 包已安装（`pip install mcp`）。

**Q: Agent 说"工具不可用"？**
A: 检查 `.mcp.json` 配置是否正确，确认 MCP Server 进程已启动。

**Q: 可以同时使用 MCP 和 CLI 吗？**
A: 可以。两者互不冲突，Agent 会自动选择可用方式。

**Q: 多个项目如何共享一个 uibridge 安装？**
A: uibridge 通过 `pip install -e .` 全局安装。每个项目有独立的 `.uibridge/adapter.yaml` 和 `.uibridge/kb/`。

**Q: 如何在无图形界面的服务器上使用？**
A: `start_recording` 需要浏览器和图形界面。服务器环境可使用现有 `recording.json` 直接执行 `generate` 命令。
