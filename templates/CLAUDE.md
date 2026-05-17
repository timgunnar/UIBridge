# CLAUDE.md — 企业 UI 自动化项目 Agent 对接文件
#
# 将本文件放到企业项目的根目录，Claude Code 启动时会自动加载。
# Agent 通过本文件了解如何调用 uibridge 框架知识翻译层。
#
# 三种对接方式（按推荐度排序）:
#   A. MCP Server (推荐) — 在 .mcp.json 注册，Agent 获得类型化工具
#   B. CLI 命令 (兜底)   — Agent 通过 Bash 直接调用 uibridge 命令
#   C. Skill (可选)      — 在 .claude/skills/ 下安装 uibridge skill

## 可用工具

本项目对接了 **uibridge** — 给企业框架装上 AI 接口的翻译层。它学习你的框架约定，把浏览器操作翻译成符合你团队风格的分层结构化测试代码，人和 AI 都能持续维护。

### 方式 A: MCP Server（推荐 — 开箱即用）

在项目的 `.mcp.json` 中注册：

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

注册后 Agent 自动获得 8 个类型化工具：

| MCP 工具 | 参数 | 用途 |
|---------|------|------|
| `analyze_page` | `url`, `adapter_config?` | 分析页面，发现组件 |
| `start_recording` | `url`, `adapter_config?` | 开始交互式录制（打开浏览器） |
| `stop_recording` | `output_file?` | 停止录制，保存文件，关闭浏览器 |
| `record_browser_operations` | `url`, `output_file?` | [CLI 用] 一次性录制（按 Enter 结束） |
| `generate_test_code` | `input_file?`, `output_dir?`, `adapter_config?` | 生成测试代码 + 自检 |
| `diff_snapshots` | `input_file?` | 对比快照，生成断言候选 |
| `seed_knowledge_base` | `project_dir` | 扫描源码播种 KB |
| `query_knowledge_base` | `query`, `project_dir?` | 查询框架约定 |

### 方式 B: CLI 命令（兜底）

如果 MCP Server 不可用，Agent 用 Bash 直调 CLI：

| 命令 | 用途 |
|------|------|
| `uibridge analyze --url <URL>` | 分析页面组件 |
| `uibridge record --url <URL> --headed` | 录制操作 |
| `uibridge generate -i <文件> -o <目录>` | 生成代码 |
| `uibridge diff -i <文件>` | 断言候选 |

## 项目框架信息

- **语言/框架**: Java + TestNG + Maven  <!-- 按实际修改 -->
- **适配器配置**: `.uibridge/adapter.yaml`
- **源码目录**:
  - 页面对象: `src/main/java/**/pages/`
  - 测试代码: `src/test/java/**/tests/`
  - 测试数据: `src/test/java/**/data/`

## 工作流

### 首次接入

1. 确保 `pip install -e .` 已在 uibridge 目录执行
2. 检查 `.uibridge/adapter.yaml` 存在（没有则从 uibridge 的 `templates/adapter.yaml` 复制并调整 `base_package`）
3. 调用 `seed_knowledge_base(project_dir=".")` 扫描源码播种 KB
4. 报告发现了多少组件、页面、约定

### 录制新功能测试（交互式两步曲）

1. 调用 `analyze_page(url=...)` 了解页面组件
2. 调用 `start_recording(url=...)` 打开浏览器，开始录制
3. 告诉用户"浏览器已打开，请在浏览器中操作，完成后告诉我"
4. **等待用户告知完成**（用户操作完成后会在对话中说"好了"/"完成"）
5. 调用 `stop_recording()` 结束录制，保存 recording.json
6. 调用 `generate_test_code()` 生成代码 + 自检
7. 将生成的代码从 `generated/` 移动到正确的 Maven 目录
8. 如有自检失败，分析原因并修复
9. 报告用户结果。鼓励用户审查生成的代码，如有问题告知 Agent 修正。

### 维护已有测试

1. `analyze_page(url=...)` 对比新旧组件
2. 重新录制受影响的功能
3. `generate_test_code()` 重新生成
4. 更新受影响的已有测试

## 自定义适配器（预置适配器不匹配时）

如果 `.uibridge/adapter.yaml` 中配置的 4 组预置适配器（reference / screenplay / java_testng / java_fluent）都不匹配本项目的框架风格，Agent 需要判断**改什么**。

### 决策树：按这个顺序判断

```
企业框架分析结果
    │
    ├─ 与 4 组 demo 相似 >80%？
    │   → 直接用预置适配器。修改 adapter.yaml 即可，无需写代码。
    │
    ├─ 有独特命名/import/目录约定，但"组件→定位→操作→断言"结构不变？
    │   → seed_knowledge_base + StyleLearner 学习，KB 自动反馈到生成。不改核心。
    │
    ├─ 有自定义注解、组件工厂、链式等待、Builder、泛型、BDD、非英文命名……但仍是"组件→定位→操作→断言"？
    │   → 写自定义适配器（只改 5 个接口 + Jinja2 模板），不动核心引擎。
    │   详见下方"第一步"。
    │
    ├─ 框架抽象概念无法用现有 IR 数据结构表达？
    │   → 小改 IR 数据结构（engine/ir/framework_call.py 或 adapter/base.py，加字段/枚举值）。
    │   必须有默认值、向后兼容。不动引擎逻辑。详见 ADAPTER_GUIDE.md §需要扩展 IR 数据结构的信号。
    │
    └─ 非浏览器 UI / 非 UI 测试 / 框架没有组件抽象？
        → uibridge 不适用。诚实告知用户原因。
```

**核心认知**：通用引擎只生产数据（ScriptDef / ComponentDef 等），适配器决定怎么变成代码。Jinja2 模板完全自由。绝大多数"复杂"落在第三行——写适配器就够了，核心一行不改。

### 第一步：定位 uibridge 源码

```bash
# 找到 uibridge 的安装位置（pip install -e . 后为可编辑安装）
python -c "import uibridge; from pathlib import Path; print(Path(uibridge.__file__).parent.parent)"
```

该目录下包含：
- `docs/adapter-guide.md` — **适配器开发完整指南（必读，含 4 个 Phase 的详细步骤）**
- `uibridge/adapter/base.py` — 5 个接口定义 + 数据结构
- `uibridge/adapter/` — 4 组已有适配器参考实现
- `docs/` — 完整文档（用户手册、KB 维护、LLM 对接等）

### 第二步：按 docs/adapter-guide.md 的 4 个 Phase 执行

```
Phase 1: 分析项目   → 读取 pom.xml / 页面对象 / 测试文件 / 数据文件 → 确定框架特征
Phase 2: 映射接口   → 按 5 个接口逐一实现（Resolver / Locator / Recognizer / Generator / Formatter）
Phase 3: 生成文件   → 写入 uibridge/adapter/custom_<project>.py + tests/
Phase 4: 验证       → python -m pytest tests/test_custom_<project>.py -v
```

### 第三步（关键）：注册适配器

验证通过后，更新 `.uibridge/adapter.yaml` 的 `components` 段，5 个 key 对应 5 个接口：

```yaml
components:
  resolver: "uibridge.adapter.custom_myproject.MyComponentResolver"
  locator: "uibridge.adapter.custom_myproject.MyLocatorStrategy"
  recognizer: "uibridge.adapter.custom_myproject.MyActionRecognizer"
  generator: "uibridge.adapter.custom_myproject.MyCodeGenerator"
  data_formatter: "uibridge.adapter.custom_myproject.MyDataFormatter"
```

key 名不可改：`resolver` / `locator` / `recognizer` / `generator` / `data_formatter`。
详细格式和验证命令见 docs/adapter-guide.md Phase 5。

## 关键约定

- 录制文件默认 `recording.json`
- 生成代码默认输出 `generated/`，然后移入 Maven 目录
- 适配器配置在 `.uibridge/adapter.yaml`，用户明确要求才改
- 生成的代码风格要匹配已有测试
- Java 文件包名和目录结构要一致
