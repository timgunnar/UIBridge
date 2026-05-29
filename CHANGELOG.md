# CHANGELOG

## v0.4.1

### scanner 噪声过滤 + generator 模板引擎 + 录制恢复

- **scanner/** 新增 `UIRelevanceFilter` — 五维信号判定（PATH + NAMING + INHERITANCE + ANNOTATION + LOCATOR），至少 2 个独立信号命中才认定为 UI 文件，消除 KB 噪声
- **generator/** 新增 `engine.py`（CodeGenerator Jinja2 ChoiceLoader）+ 10 模板（Python/Java × 5 类型），3 个 `*_gen.py` 已对接；`_build_context()` 对接 KB 查询 naming/imports/assertions/locators 四类 convention，生成代码消费团队知识
- **browser/** `start_recording` 从 stub 恢复为 RecordingSession 实时注入，三段式录制全流程打通
- **mcp/** `generate_test_code` 从 stub 改为对接 CodeGenerator；`start_recording` 恢复
- **kb/** 移除 ad-hoc `_quick_ui_check()`，委托给 scanner UIRelevanceFilter

### 测试

- 643 个测试全部通过（v0.4.0: 551 个）
- 新增 95 个 scanner filter 测试，移除 3 个旧 `_quick_ui_check` 测试

---

## v0.4.0

### 架构重构：五大引擎 + MCP 接口

uibridge 重构为五个独立引擎模块，按职责清晰拆分：

- **扫描引擎** (`scanner/`) — 自动发现项目结构（构建系统、语言、AW 目录、基类、定位器策略），7 类原语提取（文件扫描、继承链、调用链、注解、PrefixSpan 模式挖掘、统计分布、定位器），3 组检测模板
- **KB 引擎** (`kb/`) — 新增图查询层（KnowledgeGraph + GraphNode + GraphEdge）和三源交叉验证（CrossValidator），extractor 从 Mixin 继承重构为组合模式（6 个独立提取器），store 新增 search_by_tag / search_by_category
- **NL 引擎** (`nl/`) — 新增模块：文档摄取（DocumentIngestor，~20 个中英文正则）、意图分类（IntentHandler，QUERY/ADD/MODIFY/DELETE/DOCUMENT/UNKNOWN）、对话管理（DialogueManager，3 条决策规则），纯规则零 LLM 依赖
- **浏览器引擎** (`browser/`) — 已有，本轮未变更
- **生成引擎** (`generator/`) — 已有，本轮未变更。StyleLearner 可用，模板驱动引擎 v0.5.0
- **MCP 接口** (`mcp/`) — get_profile / update_profile / get_project_layout 从 stub 改为真实实现；generation 工具返回友好指引；recording 工具改善 stub 消息

### 关键变更

- scanner/ 新模块（discover.py + parser.py + 7 primitives + 3 templates + **UIRelevanceFilter**）
- scanner/ **噪声过滤**：UIRelevanceFilter 五维信号判定（PATH + NAMING + INHERITANCE + ANNOTATION + LOCATOR），至少 2 个独立信号命中才认定为 UI 文件，消除 KB 噪声
- nl/ 新模块（doc_ingest.py + intent_handler.py + dialogue.py）
- kb/ 新增 graph.py + cross_validate.py
- kb/ extractor 重构：Mixin 继承 → 组合模式
- kb/ 移除 ad-hoc `_quick_ui_check()`，委托给 scanner UIRelevanceFilter
- **browser/ 录制恢复**：`start_recording` 从 stub 改为 RecordingSession 实时注入，三段式录制全流程打通
- **generator/ 模板引擎**：新建 `engine.py`（CodeGenerator Jinja2 引擎）+ 10 模板（Python/Java × 5 类型），3 个 `*_gen.py` 已对接
- mcp/ 去 stub 化：KB/Profile/Env 工具全部返回真实数据；`start_recording` 恢复；`generate_test_code` 从 stub 改为对接生成引擎
- 模板文件更新：CLAUDE.md、.mcp.json、adapter.yaml

### 删除

- 旧适配器测试文件：test_compatibility.py、test_custom_playwright_java.py、test_java_compatibility.py、test_e2e.py、test_aria_analyzer.py、test_runtime_analyzer.py
- 旧 kb extractor mixin 文件：_aggregation.py、_conventions.py、_documents.py、_java.py、_profile.py、_python.py
- source_detection.py（功能移入 scanner/）
- docs/ 目录归档至 OLD/

### 测试

- 643 个测试全部通过（v0.3.7: 338 个）
- 新增 305 个测试（scanner 94 + scanner_filter 95 + nl 70 + kb_graph 49，移除 3 旧 _quick_ui_check 测试）

---

## v0.3.7

### Bug 修复

- `cli.py` `_load_adapter_safe()` 递归调用自身 → 改为调用 `load_adapter()`
- `style_learner.py` `ast.get_docstring()` 对不可文档化节点抛 `TypeError` → 安全包装 `_safe_get_docstring()`

### 测试

- 770 个测试全部通过（v0.3.6: 297 个）
- 新增 473 个测试（custom_playwright_java 82 + kb_extractor 156 + aria_analyzer 54 + runtime_analyzer 39 + kb_manager 42 + style_learner 37 + mcp_helpers 63 + cli 19）

## v0.3.6

### 三个反馈信道

**信道 1: 自检结果反馈 KB** — 生成代码的自检结果自动更新 KB 条目置信度：

- `StageGeneration` 追踪生成过程中使用的 KB 条目（命名规则、定位器约定、组件映射）
- 自检通过 → 关联的 KB 条目置信度 +0.02，失败 → -0.25
- `generate_test_code` MCP 工具返回中新增 `review_needed` 和 `kb_items_updated` 字段

**信道 2: NL KB/画像管理** — 8 个新的结构化 MCP 工具：

- `add_kb_rule` / `modify_kb_rule` / `delete_kb_rule` / `query_kb_rules` — KB CRUD
- `update_profile_field` / `confirm_profile_fields` — 画像管理
- `review_generated_code` / `regenerate_code` — 代码审查与重生成
- 所有变更写入审计日志（`.uibridge/audit.yaml`）
- `operate_nl()` 的 ADD/MODIFY/DELETE 路径均记录审计日志

**信道 3: 代码生成纠正** — 首创的中间 IR 持久化与增量重生成：

- IR 持久化（`.uibridge/sessions/`）：录制 → 语义分析 → 框架映射 → 生成结果 三级 IR
- `regenerate_code`：从持久化 IR 重新生成，支持 NL 反馈同时更新 KB（信道 2+3 联动）

### 清理

- 删除 5 个向后兼容 shim（`kb_item.py` 等）
- 删除死代码 `apply_nl_feedback()`
- 全代码库 `kb_xxx` 导入统一为无前缀路径

### 测试

- 297 个测试全部通过（与 v0.3.5 一致，无行为变更）

## v0.3.5

### 架构重构

**循环依赖消除** — KBManager ↔ ProfileManager 循环引用已完全解除：

- KBManager 不再创建 ProfileManager 实例，通过构造函数注入接收
- ProfileManager 使用顶层 import 引用 KBExtractor 和 SourceDetector，移除 4 处 lazy import
- KBManager 移除 5 个纯委托方法（get_profile / reprofile / update_profile / confirm_profile / enhance_profile_from_document）
- 两个服务完全独立，由 Pipeline 编排层协调

**Pipeline 拆分** — 从 ~875 行单文件拆为 `pipeline/` 包：

- `_orchestrator.py`：~206 行编排器，持有 4 个 stage 引用
- `stage_recording.py`：录制阶段管理
- `stage_analysis.py`：RawRecording → SemanticActionSequence
- `stage_mapping.py`：SemanticAction → FrameworkCall
- `stage_generation.py`：代码生成 + 自检 + fix-and-retry

**适配器去重** — 5 个适配器的重复代码统一到 `adapter/base.py`：

- `extract_domain()`、`JINJA_ENV`、`resolve_package()`、`common_package_prefix()` 共享函数
- `LocatorStrategy.best_attr()` 基类默认实现 + `_build_ancestor_chain()` 共享 helper
- `ActionRecognizer.aggregate()` 模板方法（`_should_aggregate` / `_flush_buffer` 钩子）
- `CodeGenerator.get_import_style()` / `get_assertion_style()` KB 查询+回退默认实现
- 预期消除 ~1,200 行重复代码

**日志覆盖** — 全部 Python 文件添加 `logger = logging.getLogger(__name__)`，88 处 `except Exception: pass` 添加 `logger.warning(..., exc_info=True)`

**硬编码清理** — Java 包名（`com.acme` 等）提取为 `DEFAULT_PACKAGE` 类常量，数值阈值提取为 Pipeline/MCP 类常量，页面名字符串提取为类常量

**死代码移除** — `custom_playwright_java.py` 中 4 行不可达代码

**动态层驱动代码生成** — 消除硬编码层映射，实现画像驱动的动态生成：

- `CodeGenerator.generate(def_obj, layer_config)` 统一调度方法，按 `maps_to` 字段路由到具体生成方法
- `stage_generation.py` 从 `_get_generatable_layers()` 动态获取 `managed_by_user=False` 的层，替代原有硬编码 if 分支
- `_load_output_config()` 使用通用 `maps_to` 字段匹配，不再绑定特定层名
- 项目增加新层时只需更新画像 `layer_structure`，无需修改生成逻辑

### 测试

- 297 个测试全部通过（与 v0.3.4 一致，无行为变更）

---

## v0.3.4

### 目录结构重整

**KB 包文件重组** — 可维护性提升：

- **`kb_extractor.py`（2401 行）拆分为 `kb/extractor/` mixin 子包**：7 个模块（`_base.py`/`_python.py`/`_java.py`/`_documents.py`/`_profile.py`/`_aggregation.py`/`_conventions.py`），每个 <650 行
- **源检测逻辑独立**：450 行目录检测代码从 `kb_manager.py` 提取为 `kb/source_detection.py`（`SourceDetector` 类）
- **去 `kb_` 冗余前缀**：`kb_item.py` → `item.py`，`kb_store.py` → `store.py`，`kb_manager.py` → `manager.py`，`kb_evolution.py` → `evolution.py`
- **`__init__.py` 便捷导入**：`engine/`、`engine/ir/`、`adapter/`、`generator/` 包新增 re-exports，支持 `from uibridge.engine.ir import RawRecording` 短路径
- **向后兼容**：旧路径（`from uibridge.kb.kb_extractor import KBExtractor` 等）仍可用，触发 `DeprecationWarning`

### 测试

- 297 个测试全部通过（与 v0.3.3 一致，无行为变更）

---

## v0.3.3

### 关键升级

**KB 两阶段聚合提取** — 知识库播种从逐文件 1-YAML-per-file 重构为两阶段聚合：

- **根因**：大型项目 15,973 个 YAML 中仅 3 个是 UI 组件，其余全是 Model/Service/DTO 噪声
- **Phase 1 框架画像**：扫描 pom.xml + 抽样源码，生成 `FrameworkProfile`（UI 包路径、基类映射、定位器优先级、命名约定）。存储为 `.uibridge/profile.yaml`
- **Phase 2 聚合提取**：只扫描 UI 目录，按组件族聚合（Table* → "table"，等同类合并为一个 KBItem）。产出 ~50-200 条精准知识
- **画像持续演化**：NL 对话更新单个画像字段（"我们的基类是 X"）、文档理解增强画像（"这是我们团队的编码规范.md"）、字段级来源追踪和置信度（auto / human_dialogue / document / runtime）
- **新增** `FrameworkProfile`、`ProfileField` dataclass；`seed_two_phase()`、`reprofile()`、`update_profile()`、`enhance_profile_from_document()`；PROFILE 意图识别
- **向后兼容**：旧 `seed_from_static_analysis()` 保留为回退路径；旧 YAML 格式继续可加载

**画像/KB 解耦** — FrameworkProfile 从 KB 模块独立为顶层模块：

- **新建** `profile.py`、`profile_store.py`、`profile_manager.py` 三个独立模块
- **存储路径**：画像从 `.uibridge/kb/profile.yaml` 迁移到 `.uibridge/profile.yaml`，首次加载自动迁移
- **TTL 缓存**：ProfileStore 内置 300 秒内存缓存，减少磁盘 I/O
- **向后兼容**：`from uibridge.kb import FrameworkProfile, ProfileField` 继续有效

**画像 ProfileField 增强**：

- 每个 ProfileField 新增 `description` 字段（Agent 可解释性）
- layer_structure 新增 `maps_to`（层→输出类型映射）和 `managed_by_user`（区分用户维护层/生成层）

**KB 性能优化** — 倒排索引加速搜索：

- 新增 token + bigram 倒排索引，save/delete 时增量更新
- 搜索三级退化：索引命中 → 子串匹配 → TF-IDF 关键词评分
- 大型 KB（200+ 条目）搜索性能提升显著

**快照对比结构化升级** — 方法签名解析：

- 新增 `_parse_method_signature()` 支持 Java / Python 两种签名格式
- `compare_snapshot()` 从方法名比较升级为结构化比较（返回类型、参数变更检测）
- 新增 `signature_changes` 字段标记签名变更

**Pipeline 拆分** — 职责分离：

- 新增 `DiscoveryService`（`discovery.py`）承载组件发现和 BAW 模式挖掘
- Pipeline 由 893 行精简为 ~750 行

**KB 生命周期拆分** — 单一职责：

- 新增 `KBEvolution`（`kb/kb_evolution.py`）— 衰减、泛化、归档
- 新增 `FreshnessMonitor`（`kb/freshness.py`）— 组件新鲜度检测
- KBManager 改为委托调用，职责更清晰

**遗留方法标记** — 5 个 `_legacy_extract_*` 方法添加 DeprecationWarning，引导使用 `extract_aggregated()`

**文档**：新增 `docs/profile-maintenance-guide.md`（框架画像维护指南），整体刷新全部文档

### 测试

- 297 个测试全部通过（v0.3.2: 216 个）
- 新增 81 个测试（KB 两阶段聚合、画像序列化、组件族分组、快照签名解析、索引搜索、缓存失效、KB 演化、组件新鲜度）

---

## v0.3.2

### 关键升级

**录制噪声爆炸修复** — 1 分钟录制从 360+ 步 / 400KB / 超时崩溃 → ~30 步正常输出：

- **根因链**：MutationObserver 无防抖 → 每次 DOM 变更生成 1 个 RawStep → Pipeline 无过滤 → 适配器 else 分支生成 page.mutation() 方法名 → 代码行数爆炸
- **JS 层防抖**：500ms 窗口 + 2000ms 最大停留，stop 前 flush 未决事件
- **Pipeline 过滤**：MUTATION 事件直接跳过 + MAX_STEPS_PER_SCENE=50 强制分割
- **语义分割点**：组件类型变化 → 时间间隔 → 强制切分（避免截断业务逻辑）
- **MCP 保护**：`generate_test_code` 超过 200 步返回警告 + CLI 建议

**断言占位符消除** — 5 个适配器全部从注释/占位符升级为框架原生断言：

- `base.py` 新增 `parse_assertion_candidate()` — 6 种正则模式解析断言候选
- 每个适配器实现 `_render_assertion()` → `url_equals` / `element_visible` / `element_absent` / `text_equals` / `count_changed` / `layout_stable` / `generic`
- reference → `assert page.locator(...).is_visible()` / screenplay → `actor.should(See.that(...))` / java_testng → `Assert.assertEquals(...)` / java_fluent → `assertThat(...).isVisible()` /
  playwright_java → `Assert.assertTrue(page.isVisible(...))`

**知识库自动播种** — 接入零配置：

- `KBManager.auto_detect_source_dirs()` 自动检测项目结构（Maven `<modules>` / Gradle sourceSets / Python 目录）
- `auto_seed()` 在 Pipeline / MCP / CLI 入口集成，首次使用自动触发
- 支持非标准 Maven（pom.xml `<sourceDirectory>`）+ Gradle Groovy/Kotlin DSL
- 动态阈值：`max(5, total_files // 10)`，大项目按比例扩展

**知识库提取深化** — 从类名到框架语义：

- Java 17+ javalang 失败 → regex 回退（类名/继承/注解/方法签名）
- 继承链检测（extends/implements）→ `_infer_component_type()` 15 种分类
- 注解解析（@FindBy/@DataModule/@DataTestId）→ 定位器策略提取
- 差异化置信度：annotation+locator 0.80 → base class 0.75 → regex fallback 0.55
- 命名规范批量分析：类后缀/方法前缀/字段风格聚合

**KB 驱动全流程噪声过滤** — 录制到生成四阶段过滤链：

- Stage 1 录制层：KB 定位器白名单 — 仅捕获含已知定位属性（data-testid 等）的 DOM 变更
- Stage 2 语义分析层：组件 KB 验证 — 检查步骤组件是否匹配已知组件类型，标记高/中/低置信度
- Stage 3 框架映射层：KB Pattern 匹配 — 子序列匹配识别频繁操作模式，合并为复合动作
- Stage 4 代码生成层：KB 命名/定位器约定驱动生成（已有机制）

**KB NL 对话式增删改查** — `update_knowledge_base` MCP 工具：

- 正则意图解析：ADD/MODIFY/DELETE/QUERY 四类操作，10+ 条意图模式
- 分类自动推断：组件/约定/模式/页面四类知识自动归入对应目录
- 置信度管理：用户注入初始 0.85-0.95

**KB 自动模式挖掘** — 每次 `generate_test_code` 后从语义序列挖掘 BAW 模式，写入 KB patterns 目录

### 新增 MCP 工具

- `update_knowledge_base`：NL 对话式知识库增删改查（QUERY/ADD/MODIFY/DELETE）
- MCP Server 工具总数：9 → 10

### 测试

- 216 个测试全部通过（v0.3.1: 186 个）
- 新增 30 个测试（KB NL CRUD 操作 12 个 + KB Pattern 匹配 10 个 + KB 驱动噪声过滤 8 个）

---

## v0.3.1

### 关键升级

**适配器代码去重** — 消除 5 个适配器文件间的 7 处重复实现：

- `load_adapter` 提取为 `adapter/loader.py` 共享工厂函数
- `_java_class_name` 5 份副本 → `to_java_class_name()` 共享函数
- `_post_process` 3 份副本 → `post_process_java_code()` 共享函数
- `_get_aria_map` 4 份副本 → `ComponentResolver._resolve_aria_map()` 基类方法
- `get_locator_priority` 4 份副本 → `LocatorStrategy._resolve_locator_priority()` 基类方法
- `recognize_pattern` 5 份副本 → `ActionRecognizer.recognize_pattern()` 基类实现
- `render_step` 参数格式化 3 份副本 → `format_action_params()` 共享函数

**性能优化** — 5 处全局优化：

- Jinja2 Environment 单例化（5 个适配器文件，消除 ~20 处重复创建）
- 正则编译为模块级对象（7 个文件）
- ActionType 类型规范化前置到 `RawStep.__post_init__`（消除 5 处重复）
- `suggest_name` Java 适配器统一 PascalCase
- `build_xpath` ancestor_chain 补齐（`screenplay.py`、`java_fluent.py`、`custom_playwright_java.py`）

**KB 自动播种全链路集成** — `auto_detect_source_dirs()` + `auto_seed()` → Pipeline / MCP / CLI 入口，首次使用自动触发

### 关键 Bug 修复

**P0（5 项）**：

- `FluentDataFormatter._infer_java_type` 生成 Python 类型名（`bool`/`str`）改为 Java 类型（`boolean`/`String`），提取为 `base.py` 共享函数
- `ReferenceCodeGenerator.render_step` 断言从 Python 注释改为可执行 `assert True, f"TODO: ..."`
- `component_aw_gen.py` 使用 `sanitize_identifier()` 替代手动字符串替换，防止中文/特殊字符泄露到代码
- 3 处 `except Exception: pass` 添加 `logger.warning()`（`cli.py`、`runtime_analyzer.py`、`aria_analyzer.py`）
- `_extract_domain` 正则补齐 `edit|detail` 路径段（`screenplay.py`、`java_fluent.py`）

**功能补全（1 项）**：

- `FluentActionRecognizer.aggregate()` 实现缓冲聚合逻辑，连续 input+click 合并为 `fillAndSubmit`，与其他 4 个适配器一致

### 测试

- 186 个测试全部通过（v0.3.0: 159 个）
- 新增 26 个测试（KB 搜索语义匹配 8 个 + Screenplay ARIA 扩展 9 个 + JavaFluent ARIA 扩展 9 个）
- 新增 1 个测试（安装/卸载正确性）

---

## v0.3.0

### 关键升级

**录制交互模型重设计** — 从单工具调用改为三段式：

- `open_browser(url)` 打开可见浏览器，不录制。用户可在此阶段预置（登录、导航等）
- `start_recording()` 在已打开的浏览器上注入录制 JS
- `stop_recording()` 停止录制、保存文件、关闭浏览器
- 解决了 MCP 请求-响应模式与录制交互多回合性不匹配的根本问题

**录制覆盖大幅扩展** — 从 ~10 种事件类型扩展到 ~20 种：

- 新增 ActionType：`UNCHECK` / `SUBMIT` / `FOCUS` / `BLUR` / `DIALOG` / `CLIPBOARD` / `FILE_UPLOAD`
- 键盘：所有功能键（Tab / Escape / 方向键 / F-键）+ 修饰键组合（Ctrl/Meta/Alt）
- 表单：checkbox/radio/file input/range/multi-select 变更
- 弹窗拦截：alert/confirm/prompt 自动捕获
- 剪贴板：copy/cut/paste 事件
- DOM 变更：MutationObserver 自动追踪
- Tab 导航：focusin 事件追踪

**浏览器模拟** — 无痕模式改为持久化 Profile：

- `launch_persistent_context` 替代 `browser.new_context`
- `no_viewport=True` 让页面跟随浏览器窗口大小
- 反爬措施：`--disable-blink-features=AutomationControlled` + JS 属性覆盖

### 关键 Bug 修复

**录制器（3 项）**：

- B12 事件丢失：`page.wait_for_timeout()` 在 stop_recording 和 _setup_bridge 中刷新排队回调
- B13 录制文件路径：`_OUTPUT_BASE` 改为 `Path.cwd()`，文件保存到调用者工作目录
- 首快照缺失：`_setup_bridge()` 中增加初始 `_capture_snapshot()`

**MCP Server（3 项）**：

- 命名空间包遮蔽：`sys.meta_path` 重新排序，可编辑 finder 优先
- 分段浏览器超时：open_browser 添加 30 分钟超时自动关闭
- start_recording/stop_recording 状态互斥保护

**录制事件派发（1 项）**：

- sync_playwright().start() 不维护常驻派发器 → 事件只在 Playwright API 调用时处理 → 添加 wait_for_timeout 确保回调被刷新

### 新增 MCP 工具

- `open_browser`：打开可见浏览器（不录制），支持用户预置
- `check_environment`：检查 uibridge 运行环境

MCP Server 工具总数：8 → 9（原有 `analyze_page` / `start_recording` / `stop_recording` / `generate_test_code` / `diff_snapshots` / `seed_knowledge_base` / `query_knowledge_base` + 新增 2）

### 测试

- 159 个测试全部通过（v0.2.0: 131 个）
- 新增 24 个安装/卸载正确性测试（cleanup 扫描、CLI 行为、安装元数据验证）
- 新增 4 个回归测试：回调保留、变更事件、事件计数、空闲页面捕获

---

## v0.2.0

### 关键升级

**非标 Java 项目兼容** — `_detect_source_dirs()` 重写，支持：

- `pom.xml` 中声明的 `<sourceDirectory>` / `<testSourceDirectory>`
- 递归扫描 `src/` 下的 `.java` 文件反推目录结构
- 无 `com/` 目录、只有 `src/` 的项目也可正常生成代码

**源码包名扫描** — 新增 `scan_java_source_for_package()`：

- 不再依赖知识库（KB）才能检测 Java 包名
- 直接扫描项目 `.java` 文件的 `package` 声明推断包名
- Pipeline 和适配器均集成此兜底逻辑

**默认包支持** — 当项目 `.java` 文件无 `package` 声明时：

- 生成的代码自动跳过 `package` 行
- 自动修复项目内 `import` 引用

### 关键 Bug 修复

**MCP Server（7 项）**：

- #1 `record_browser_operations` 死锁：MCP 模式下直接返回错误提示
- #2 资源泄露：所有工具添加 try/finally 确保 browser/pw 清理
- #3 超时定时器未取消：`stop_recording` 中先 cancel 再清理
- #4 路径穿越：`_sanitize_output_path()` 约束路径在项目根目录内
- #5 URL 无校验：`_validate_url()` 拦截 javascript:/data: 等危险协议
- #6 `stop_recording` 不创建父目录：`output_path.parent.mkdir()` 自动创建
- #7 文件不存在时崩溃：`generate_test_code`/`diff_snapshots` 返回结构化错误

**引擎 — 录制器（4 项）**：

- #8 `page.url` 线程安全违规：`_current_url` 缓存在安全线程更新
- #9 Popup 不录制：弹窗注入录制 JS、`expose_binding`、`add_init_script`
- #10 快照静默吞异常：错误存入 `Snapshot.error` 字段
- #11 iframe 缺少 `add_init_script`：`_on_frame_attached` 中注入录制 JS

**引擎 — 通用（4 项）**：

- #12 Shadow DOM 不支持：`_query_all_deep()` 递归遍历 shadowRoot
- #13 SPA 导航检测不完整：Turbolinks/Turbo 事件监听
- #14 MutationObserver 窗口期：body 轮询 + documentElement 初始监听
- #15 场景分割粗糙：5 秒空闲间隔自动创建新场景（idle-gap splitting）

**自检（2 项）**：

- #16 修复规则仅 5 条：新增 4 条（缺 @Test 注解、NPE→tearDown、缺 self、缺冒号）
- #17 Java 自检缺依赖 JAR：`_find_java_jars()` 搜索 `~/.m2/repository/`

**适配器（2 项）**：

- #19 Java 适配器硬编码包名：`_resolve_package()` 从 KB 自动检测 → 源码扫描兜底
- #20 Reference ARIA 角色覆盖不足：ARIA_MAP 从 ~15 扩展到 ~45 个角色

**工程（2 项）**：

- #28 依赖无版本 pin：所有依赖添加 `<NEXT_MAJOR` 上界
- #29 javalang 可选依赖作硬依赖：`_check_javalang()` 检测可用性，ImportError 单独捕获

**知识库（1 项）**：

- #25 Java AST 提取静默吞异常：全部替换为 `logger.debug("Error... %s", e)`

### 测试

- 131 个测试全部通过（v0.1.0: 107 个）

---

## v0.1.0

### 架构概览

```
用户操作 (浏览器) → 录制 (RawRecording)
                  → 语义分析 (SemanticActionSequence)
                  → 框架映射 (FrameworkCallSequence)
                  → 代码生成 (Jinja2 模板)
                  → 自检 (pytest / mvn test)
```

三层系统架构：

- **Layer 1 通用引擎**：录制、ARIA 快照、DOM diff、场景分割。语言无关、框架无关
- **Layer 2 框架适配器**：5 个接口（ComponentResolver / LocatorStrategy / ActionRecognizer / CodeGenerator / DataFormatter）
- **Layer 3 生成产物**：ComponentAW → BusinessAW → TestScript + TestData 四层输出

### 功能

- 4 组预置适配器（reference / screenplay / java_testng / java_fluent）
- MCP Server（8 个工具：analyze / start_recording / stop_recording / record / generate / diff / seed_kb / query_kb）
- CLI 命令（record / generate / analyze / diff / cleanup）
- 知识库系统（KBStore / KBExtractor / KBManager / StyleLearner）
- 自检系统（fix_and_retry 最多 3 次重试，5 条修正规则）
- 4 组演示项目（Python A/B, Java C/D）

### 测试

- 107 个兼容性测试全部通过
