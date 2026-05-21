# MCP 工具参考

uibridge 通过 MCP Server 暴露 10 个工具，供 AI Agent（Claude Code 等）调用。所有工具均为异步，Agent 按需组合调用。

## 工具总览

| # | 工具 | 用途 | 典型场景 |
|---|------|------|---------|
| 1 | `check_environment` | 检查运行环境 | 首次接入、故障排查 |
| 2 | `analyze_page` | 分析页面组件 | 了解页面结构后再录制 |
| 3 | `open_browser` | 打开可见浏览器 | 三段式录制第一步 |
| 4 | `start_recording` | 开始录制用户操作 | 三段式录制第二步 |
| 5 | `stop_recording` | 停止录制并保存 | 三段式录制第三步 |
| 6 | `generate_test_code` | 生成分层测试代码 | 录制完成后生成代码 |
| 7 | `diff_snapshots` | 对比页面快照差异 | 生成断言候选 |
| 8 | `seed_knowledge_base` | 扫描源码播种 KB | 首次接入新项目 |
| 9 | `query_knowledge_base` | 查询框架约定 | 了解项目组件和定位策略 |
| 10 | `update_knowledge_base` | NL 对话式 KB 管理 | 通过对话增删改查 KB |

---

## 1. check_environment

**用途**：检查 Playwright 浏览器、依赖等是否就绪。

**参数**：无

**返回**：浏览器可用性、uibridge 版本。

**使用时机**：Agent 在开始录制前验证环境，或用户排查安装问题。

**返回示例**：
```json
{
  "status": "ok",
  "browsers": {
    "chromium": {"available": true, "path": "..."},
    "firefox": {"available": true, "path": "..."}
  },
  "issues": [],
  "uibridge_version": "0.3.1"
}
```

---

## 2. analyze_page

**用途**：分析一个页面，发现其中的 UI 组件（表格、输入框、按钮等）并输出注册表。

**参数**：

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `url` | string | 是 | 页面 URL（需 http/https） |
| `adapter_config` | string | 否 | 适配器配置文件路径 |

**返回**：JSON 格式的组件列表，每个组件含 `type`/`name`/`xpath`/`aria_role`。

**使用时机**：在录制或生成测试之前，先了解页面有哪些组件、它们叫什么、怎么定位。

**典型工作流**：
```
Agent: analyze_page(url="http://localhost/users")
Agent: "页面有一个 TableAW（用户列表）、一个 InputAW（搜索框）、两个 ButtonAW。现在帮你录制。"
Agent: open_browser → start_recording → 用户操作 → stop_recording
```

---

## 3. open_browser

**用途**：打开可见浏览器窗口（不录制），导航到指定 URL。

**参数**：

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `url` | string | 否 | 起始页面 URL，默认 `about:blank` |

**返回**：会话 ID、浏览器状态。

**使用时机**：三段式录制的第一步。仅打开浏览器，不注入录制脚本。用户在此阶段可进行预置操作（登录、导航到目标页面等）。

**设计要点**：
- 使用持久化用户目录，保留 cookie/localStorage（防反爬、免重复登录）
- 注入反检测脚本，隐藏自动化标记
- 30 分钟超时保护，防止资源泄露

**典型工作流**：
```
open_browser(url="http://localhost/login")
→ 用户手动登录 → 导航到目标页面
→ start_recording()
→ 用户执行测试操作
→ stop_recording()
```

---

## 4. start_recording

**用途**：在已打开的浏览器上开始录制用户操作。

**参数**：

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `adapter_config` | string | 否 | 适配器配置文件路径 |

**前置条件**：必须先调用 `open_browser` 打开浏览器。

**返回**：会话 ID、录制状态、当前页面 URL。

**使用时机**：三段式录制的第二步。注入事件监听，开始捕获用户操作。`start_recording` 之前的预置操作（登录、导航等）不会被录制。

**设计要点**：
- 从 `open_browser` 的 staging 状态转移为 recording 状态
- 10 分钟超时保护

---

## 5. stop_recording

**用途**：停止当前活跃的录制会话，保存录制文件，关闭浏览器。

**参数**：

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `output_file` | string | 否 | 录制输出文件路径，默认 `recording.json` |

**返回**：录制结果摘要（步骤数、文件路径、每步描述）。

**使用时机**：三段式录制的最后一步。用户在浏览器中完成操作后，Agent 调用此工具结束录制。

**安全保护**：
- 输出路径限制在 CWD 内，防止路径穿越
- 自动创建父目录

**返回示例**：
```json
{
  "status": "ok",
  "steps": 5,
  "events_received": 12,
  "file": "/path/to/recording.json",
  "summary": [
    "navigate: http://localhost/users",
    "click: 查询",
    "input: 搜索框",
    "click: 用户管理",
    "click: 新建用户"
  ]
}
```

---

## 6. generate_test_code

**用途**：从录制 JSON 生成分层测试代码（ComponentAW → BusinessAW → TestScript + TestData）。

**参数**：

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `input_file` | string | 否 | 录制文件路径，默认 `recording.json` |
| `output_dir` | string | 否 | 生成代码输出目录，默认 `generated/` |
| `adapter_config` | string | 否 | 适配器配置文件路径 |

**返回**：每个生成文件的测试名、自检状态、文件路径、代码片段。

**处理流程**：
```
录制 JSON → 语义分析 → 框架映射 → 代码生成 → 自检验证 → 输出文件
```

**输出结构**：
```
generated/
├── test_<场景名>.py       # 测试脚本
└── factories/             # 测试数据工厂
    └── <domain>_factory.py
```

---

## 7. diff_snapshots

**用途**：对比录制中的前后快照差异，生成断言候选列表。

**参数**：

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `input_file` | string | 否 | 录制文件路径，默认 `recording.json` |
| `adapter_config` | string | 否 | 适配器配置文件路径 |

**返回**：断言候选列表（如"新增了 1 个 table row"、"button 从 disabled 变为 enabled"）。

**使用时机**：录制完成后，想知道"操作后页面发生了什么变化，应该断言什么"。

**返回示例**：
```json
{
  "count": 3,
  "candidates": [
    "table.user-list: 新增 1 行",
    "button.submit: 从 disabled 变为 enabled",
    "div.toast: 新增元素 '保存成功'"
  ]
}
```

---

## 8. seed_knowledge_base

**用途**：从企业项目的源码目录提取知识，播种知识库。

**参数**：

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `project_dir` | string | 是 | 项目根目录路径 |

**返回**：播种的 KB 条目数量和分类统计。

**提取内容**：
- 组件定义（从 Python AST / Java 源码解析）
- 定位器约定（XPath、CSS 模式）
- 命名规则
- 设计文档中的 YAML frontmatter

**使用时机**：首次接入新项目时，让 Agent 自动学习框架知识。

**自动检测**：
- 识别项目语言（Python / Java）
- 自动检测源码目录结构（含 pom.xml 非标布局）
- 非 Java/Python 项目返回空（不会报错）

**返回示例**：
```json
{
  "status": "ok",
  "total_items": 23,
  "by_category": {
    "components": 15,
    "conventions": 5,
    "pages": 3
  },
  "kb_dir": "/path/to/.uibridge/kb"
}
```

---

## 9. query_knowledge_base

**用途**：查询知识库，获取框架约定、组件信息等。

**参数**：

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `query` | string | 是 | 自然语言查询词 |
| `project_dir` | string | 否 | 项目根目录路径，默认当前目录 |

**返回**：匹配的 KB 条目摘要。

**搜索策略**：
1. 精确子串匹配（优先）
2. IDF 加权语义搜索（回退），结合置信度排序

**查询示例**：

| 查询 | 用途 |
|------|------|
| `"定位器"` 或 `"locator"` | 了解定位优先级（data-testid → id → xpath） |
| `"TableAW"` | 获取表格组件的 XPath 和方法 |
| `"断言风格"` | 了解项目用 pytest assert 还是 Hamcrest |
| `"包名"` | 获取 Java 项目的基础包名 |

---

## 10. update_knowledge_base

**用途**：NL 对话式知识库增删改查。Agent 根据用户自然语言指令，自动识别意图（新增/修改/删除/查询），并更新或检索知识库条目。

**参数**：

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `instruction` | string | 是 | 自然语言指令（如"定位器用 data-testid"、"删掉表格排序规则"） |
| `project_dir` | string | 否 | 项目根目录路径，默认当前目录 |

**返回**：操作结果摘要，包含意图类型、匹配条目、更新内容。

**返回示例**：
```json
{
  "status": "ok",
  "intent": "MODIFY",
  "matched_items": 1,
  "changes": [
    {
      "item_id": "locator-strategy",
      "action": "updated",
      "detail": "定位器优先级: data-testid → id → xpath"
    }
  ]
}
```

**使用时机**：用户通过对话修正框架约定、补充项目知识、或删除过时规则时。Agent 将用户的自然语言指令转换为对 `.uibridge/kb/` 目录下知识条目文件的增删改操作。

**意图识别**：

| 意图 | 触发词示例 | 操作 | 示例指令 |
|------|-----------|------|---------|
| ADD | "添加"、"新增"、"增加"、"录入" | 创建新 KB 条目 | "添加约定：所有按钮用 `data-testid` 定位" |
| MODIFY | "修改"、"改成"、"换成"、"调整"、"原来" | 更新已有 KB 条目 | "定位策略改成 data-testid 优先" |
| DELETE | "删除"、"去掉"、"移除"、"不要" | 删除匹配的 KB 条目 | "删掉表格排序规则" |
| QUERY | "查询"、"搜索"、"看看"、"有没有"、"列出" | 检索 KB 条目（同 `query_knowledge_base`） | "查询项目中 TableAW 的使用约定" |

**典型工作流**：

```
用户: "这个项目定位器应该用 data-testid"
Agent: update_knowledge_base(instruction="定位器使用 data-testid")
Agent: "已将定位器策略更新为 data-testid 优先。"
       "影响范围：1 条 locator-strategy 条目。"

用户: "删掉表格排序的规则，我们不用那个"
Agent: update_knowledge_base(instruction="删掉表格排序规则")
Agent: "已删除 'table-sort' 条目。"

用户: "看看知识库里有什么"
Agent: update_knowledge_base(instruction="列出所有知识库条目")
Agent: "当前 KB 共 23 条：组件 15、约定 5、页面 3。"
```

---

## Agent 典型工作流

### 录制新测试

```
1. check_environment()                          ← 验证环境
2. analyze_page(url="...")                      ← 了解页面组件
3. open_browser(url="...")                      ← 打开浏览器（用户预置：登录、导航）
4. 告诉用户："浏览器已打开，请完成预置操作后告诉我"
5. start_recording()                            ← 开始录制
6. 告诉用户："请操作浏览器，完成后告诉我"
7. stop_recording()                             ← 停止录制
8. diff_snapshots()                             ← 生成断言候选
9. generate_test_code()                         ← 生成代码 + 自检
```

### 首次接入新项目

```
1. check_environment()                          ← 验证环境
2. seed_knowledge_base(project_dir=".")         ← 扫描源码播种 KB
3. query_knowledge_base("定位器约定")            ← 验证 KB 已播种
4. query_knowledge_base("组件类型")             ← 了解项目封装了哪些 AW
```

### 只分析不录制

```
1. analyze_page(url="...")                      ← 了解页面结构
2. query_knowledge_base("TableAW")              ← 了解框架组件
```

### KB 维护

```
1. update_knowledge_base("定位器用 data-testid")  ← 通过对话修正定位约定
2. update_knowledge_base("删掉过时的组件规则")      ← 删除无用条目
3. update_knowledge_base("添加新组件 DateTimePicker AW") ← 补充新框架知识
4. query_knowledge_base("定位器约定")              ← 验证更新结果
```

---

## 安全设计

所有工具均内置安全保护：

| 保护项 | 措施 |
|--------|------|
| URL 校验 | 拒绝 `javascript:`、`data:`、`file:` 等危险协议 |
| 路径穿越 | 输出路径限制在 CWD 内；输入路径解析后使用 |
| 资源泄露 | 超时定时器自动清理浏览器和录制会话 |
| 并发安全 | 录制锁 + 单线程 Playwright 执行器 |
| 反爬检测 | 启动参数隐藏自动化标记，注入反检测脚本 |
