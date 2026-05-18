# CHANGELOG

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

### 文档修正

- CLAUDE.md：修复"三层架构"表述，明确区分系统架构（3层）与代码产出（四层）

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
- 107 个兼容性测试
