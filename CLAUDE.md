# CLAUDE.md — uibridge 框架知识翻译层

本文件供 Claude Code 在 uibridge 项目内工作时使用。
企业项目使用本系统时，应将 `templates/CLAUDE.md` 复制到企业项目根目录。
用户操作指南见 [docs/user-guide.md](docs/user-guide.md)。

## 项目概述

uibridge 给企业 UI 自动化框架装上 AI 接口。核心思路：学习企业框架约定 → 把浏览器 DOM 操作翻译成企业风格的测试代码。不改架构、不换框架、不重构。

生成的代码是四层输出结构（ComponentAW → BusinessAW → TestScript + TestData），人和 AI 都能持续维护，长期保持代码质量。

## 架构速览

```
用户操作 (浏览器) → 录制 (RawRecording)
                  → 语义分析 (SemanticActionSequence)
                  → 框架映射 (FrameworkCallSequence)
                  → 代码生成 (Jinja2 模板)
                  → 自检 (pytest / mvn test)
```

系统分为三层（注意：系统的三层架构 ≠ 代码产出的四层结构，详见下文）：
- **Layer 1 通用引擎**：录制、ARIA 快照、DOM diff、场景分割。语言无关、框架无关。
- **Layer 2 框架适配器**：5 个接口（ComponentResolver / LocatorStrategy / ActionRecognizer / CodeGenerator / DataFormatter）。换公司 = 换适配器。
- **Layer 3 生成产物**：产出四层代码结构（ComponentAW → BusinessAW → TestScript + TestData）。

## 关键目录

| 目录 | 内容 |
|------|------|
| `uibridge/engine/` | 通用引擎：录制、ARIA 分析、DOM diff、自检 |
| `uibridge/engine/ir/` | 三层 IR 数据结构 |
| `uibridge/adapter/` | 4 组适配器（reference / screenplay / java_testng / java_fluent） |
| `uibridge/kb/` | 知识库：KBItem、KBStore、KBExtractor、KBManager |
| `uibridge/generator/` | 生成器：组件 AW、业务 AW、测试脚本 |
| `uibridge/pipeline.py` | 编排管道（含 KB 包名集成、名称安全化、自动修复） |
| `uibridge/cli.py` | CLI 命令入口（record / generate / analyze / diff / cleanup） |
| `uibridge/mcp_server.py` | MCP Server（Agent 工具接口） |
| `templates/` | 企业项目接入模板（CLAUDE.md + .mcp.json + adapter.yaml） |
| `docs/` | 用户文档（用户手册、适配器开发、录制指南、KB 维护、LLM 对接） |
| `demo_projects/` | 4 组演示项目（Python A/B, Java C/D） |
| `tests/` | 兼容性测试（131 个，全部通过） |

## 文档索引

| 文档 | 读者 |
|------|------|
| [docs/user-guide.md](docs/user-guide.md) | 安装、接入、日常使用、卸载 |
| [docs/positioning.md](docs/positioning.md) | 核心价值、方案对比 |
| [docs/recording-guide.md](docs/recording-guide.md) | 录制交互、代码审查、反馈 |
| [docs/adapter-guide.md](docs/adapter-guide.md) | 自定义适配器开发 4 阶段 |
| [docs/kb-maintenance-guide.md](docs/kb-maintenance-guide.md) | KB 查看、编辑、播种、版本控制 |
| [docs/llm-integration-guide.md](docs/llm-integration-guide.md) | MCP/CLI/Skill 三种对接方式 |

## 常用命令

```bash
# 运行所有测试
python -m pytest tests/ -v

# 运行单个测试
python -m pytest tests/test_java_compatibility.py::TestJavaAdapterSwap -v -s

# CLI 测试
uibridge --help
uibridge analyze --url https://example.com

# 安装/重装
pip install -e .
```

## 添加新适配器

1. 在 `uibridge/adapter/` 创建新文件（如 `dotnet_nunit.py`）
2. 实现 5 个接口：ComponentResolver、LocatorStrategy、ActionRecognizer、CodeGenerator、DataFormatter
3. 在 `tests/` 添加兼容性测试

完整流程见 [docs/adapter-guide.md](docs/adapter-guide.md)（Phase 1-5），含接口代码骨架、参考实现、复杂封装对策。测试数当前为 131 个，以此为准。

### 适配器 vs 改核心：决策树

遇到企业框架复杂封装时，按以下顺序判断：

```
企业框架与 4 组 demo 相似 >80%？
  → 直接用预置适配器，改 adapter.yaml 即可

有独特命名/import/目录约定，但组件→定位→操作→断言结构不变？
  → seed_knowledge_base + StyleLearner，KB 自动反馈

有自定义注解、工厂、Builder、等待包装、泛型、BDD、非英文命名……但仍是"组件→定位→操作→断言"？
  → 写自定义适配器（只改 5 个接口实现 + Jinja2 模板），不动核心

框架抽象概念无法用现有 IR 数据结构表达（如缺少 StepKind 枚举值、MethodCall 缺字段）？
  → 小改 IR 数据结构（`engine/ir/framework_call.py` 加枚举值/dataclass 字段，或 `adapter/base.py` 加 dataclass 字段），有默认值，向后兼容，不动引擎逻辑

非浏览器 UI / 非 UI 测试 / 框架没组件抽象？
  → uibridge 不适用，诚实告知用户
```

**关键认知**：引擎只生产数据（ScriptDef / ComponentDef 等），适配器决定怎么变代码。Jinja2 模板完全自由。绝大多数"复杂封装"落在第三行——写适配器就够了。

详细对策和代码示例见 [docs/adapter-guide.md](docs/adapter-guide.md) §复杂封装应对指南。

## Agent 对接

本系统通过三种方式对接 AI Agent：
- **MCP Server**：`python -m uibridge.mcp_server` 启动，暴露类型化工具
- **CLAUDE.md**：描述 CLI 命令和工作流，Agent 用 Bash 调用
- **Skill**：`.claude/skills/uibridge.md` 提供斜杠命令

详见 [docs/llm-integration-guide.md](docs/llm-integration-guide.md)。

## KB 集成关键特性

- **包名自动解析**：Pipeline 的 `_resolve_package_from_kb()` 从 KB 条目中提取公共包名前缀
- **Import 替换**：`_apply_kb_imports()` 将硬编码 `com.acme.*` 替换为实际包名
- **Package 声明替换**：`_apply_kb_package_to_code()` 修正 Java `package` 行
- **测试名安全化**：`_sanitize_test_name()` 过滤 @/./空格等非法字符
- **自检自动修复**：`fix_and_retry()` 最多 3 次重试，5 条修正规则
