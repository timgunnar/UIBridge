# uibridge 脚本录制指南

**从浏览器操作到符合团队风格的测试代码，含审查和反馈闭环。**

## 人机交互模型

uibridge 录制是**人机协作的三阶段流程**：

```
你操作浏览器          AI 录制+生成           你审查+反馈
─────────────        ─────────────        ──────────────
  阶段一                 阶段二                 阶段三
```

每个阶段你和 AI Agent 各司其职。下面按顺序说明。

---

## 阶段一：录制浏览器操作

**你做的事**：打开要录制的页面，正常操作业务流程。
**AI 做的事**：打开浏览器、监听你的操作、录制为结构化数据。

### 操作流程

```
你: "帮我录制用户管理的搜索功能，页面是 http://localhost:8080/users"

AI: 调用 analyze_page() 了解页面组件
    → "发现 3 个组件：搜索输入框、搜索按钮、用户表格"

AI: 调用 open_browser(url="http://localhost:8080/users")
    → 浏览器窗口打开，等待用户预置操作

AI: "浏览器已打开，请做预置操作（登录、导航等），准备好后告诉我。"

你: [在浏览器中预置操作]
    1. 登录系统
    2. 导航到 users 页面
    ...（准备好后回到对话）

你: "好了"

AI: 调用 start_recording()
    → 在已打开的浏览器上开始录制

AI: "录制中，请操作。"

你: [在浏览器中正常操作]
    1. 在搜索框输入 "张三"
    2. 点击搜索按钮
    3. 查看搜索结果表格
    ...（操作完成后回到对话）

你: "完成了"

AI: 调用 stop_recording()
    → 录制保存到 recording.json，关闭浏览器
    → "录制完成，共捕获 3 个操作步骤。"
```

### 要点

- 浏览器会一直等你操作，不会自动关闭。在 start_recording 前可自由预置（登录、导航等）
- 操作完记得回到对话告诉 AI"完成了"（或"done""好了"）
- 录制期间不要在另一窗口操作 AI 对话（避免 Agent 在等待时做其他事）

---

## 阶段二：AI 生成代码

录制完成后，AI 调用 `generate_test_code()` 自动完成以下步骤：

```
recording.json
    → 语义分析：将原始 DOM 操作聚合成业务动作
    → 框架映射：匹配你的组件类（TableAW 等）和方法
    → 代码生成：按你团队的风格生成分层代码
    → 自检：运行 pytest / javac 验证代码可执行
```

**生成产物**（四层结构）：

```
generated/
├── tests/TestUserSearch.java         ← TestScript（含 ComponentAW/BusinessAW 四层架构）
└── data/UserSearchData.java          ← TestData（测试数据）
```

代码本身遵循 ComponentAW → BusinessAW → TestScript + TestData 四层结构，维护时只改对应层即可。

AI 报告："生成了 1 个测试用例，自检通过。"

### 录制质量保障

uibridge 内置多层噪声过滤，确保录制输出干净可用：

| 机制 | 阶段 | 效果 |
|------|------|------|
| JS 层 MutationObserver 防抖 | 录制 | 500ms 窗口聚合 DOM 变更，消除抖动噪声 |
| KB 驱动定位器白名单 | 录制 | 仅捕获包含已知定位属性（data-testid 等）的 DOM 变更 |
| Pipeline MUTATION 事件过滤 | 语义分析 | 跳过无业务意义的 DOM 变更事件 |
| KB Pattern 匹配 | 框架映射 | 识别频繁操作子序列，合并为 BAW 方法 |
| Pipeline 强制分割 | 框架映射 | 超长录制自动切分，防止单个场景代码膨胀 |

录制噪声问题已根除：1 分钟录制从 360+ 步降至 ~30 步正常输出。

---

## 阶段三：审查与反馈

这是 uibridge 区别于一次性生成工具的核心环节。**你审查代码，告诉 AI 问题在哪，AI 修正并记住规则。**

### 审查什么

| 检查项 | 问自己 |
|--------|--------|
| **组件类型** | 生成的类名和方法名是你项目里用的吗？ |
| **定位器** | XPath/CSS 符合你团队的优先级约定吗？ |
| **断言风格** | 断言库和断言方式对吗？（Assert.assertEquals vs assertThat） |
| **import** | 包路径对了吗？有没有多余的 import？ |
| **命名** | 文件名、测试方法名符合团队规范吗？ |
| **数据格式** | 测试数据用的是 Builder 还是常量类？ |

### 如何反馈

```
你: "生成的 UserSearchBox 定位器用的是 id，我们项目统一用 data-testid 属性"

AI: 调用 query_knowledge_base("定位器约定")
    → 发现 KB 中未记录此约定

AI: 修改生成代码，将 id 定位改为 data-testid
    → 同时调用 seed_knowledge_base() 更新 KB
    → "已修正代码，KB 已更新：定位器优先使用 data-testid。
       后续生成都会遵循此约定。"
```

反馈的常见类型：

| 你说的 | AI 做什么 | 下次影响 |
|--------|---------|---------|
| "定位器用 data-testid" | 修改 LocatorStrategy 优先级 | 所有生成代码改用 data-testid |
| "断言用 AssertJ 的 assertThat" | 修改 CodeGenerator 模板 | 生成 AssertJ 风格断言 |
| "类名用 XxxPage 不是 XxxAW" | 修改 ComponentResolver 命名规则 | 后续生成用新命名 |
| "这个组件多了个 getRowCount 方法" | KB 补充组件方法模板 | 该组件的方法更完整 |
| "测试数据用 Builder 别用常量" | 修改 DataFormatter 模板 | 生成 Builder 模式数据 |

### 反馈如何持久化

uibridge 的知识库（KB）在 `.uibridge/kb/` 下以 YAML 文件存储。你的每次反馈都会被记录：

```yaml
# .uibridge/kb/conventions/locator_priority.yaml
category: conventions
key: convention.locator_priority
value:
  priority:
    - data-testid
    - data-module
    - id
    - name
confidence: 0.95
description: "定位器优先级，用户反馈确认 data-testid 为首选"
```

**置信度机制**：
- 自动提取的规则：置信度 0.6-0.8
- 用户反馈确认：置信度 0.9-0.99
- 自检持续通过：置信度逐步上升
- 自检失败或长期未用：置信度衰减，过低则归档

---

## 完整交互示例

```
👤: "帮我录一下员工管理的 CRUD 流程"

🤖: "好的。先分析一下页面。"
    [调用 analyze_page(http://localhost:8080/employees)]
    "页面有 4 个组件：搜索栏、员工表格、新增按钮、编辑弹窗。
     开始录制，请在浏览器中操作。"

👤: [操作浏览器] 搜索 → 新增 → 填写 → 保存 → 验证

👤: "好了，录完了"

🤖: [调用 stop_recording → generate_test_code]
    "生成 3 个测试：test_search_employee、test_add_employee、test_edit_employee。
     自检全部通过。代码在 generated/ 下，请审查。"

👤: "test_add_employee 的断言不对。我们新增后用 toast 消息验证，
     不是用表格行数。应该是 Assert.assertEquals(toast.getText(), '添加成功')"

🤖: "明白。我来修改："
    [修改 CodeGenerator 模板 → 更新 KB]
    "已将断言策略改为 toast 消息验证。KB 已更新，后续生成都会使用此模式。
     重新生成... 自检通过。请再次审查。"

👤: "这次对了。再帮我录一个删除流程。"

🤖: [使用更新后的规则录制+生成]
    "生成的 test_delete_employee 已使用 toast 断言。自检通过。"
```

---

## 常见问题

**Q: 录制时浏览器没打开？**
A: 检查 `playwright install chromium` 是否已执行。

**Q: 生成的代码编译不过？**
A: 告诉 AI 具体的编译错误。AI 会解析错误并修正代码和 KB。

**Q: 同一个问题反复出现？**
A: 说明 KB 没收到反馈。直接告诉 AI "把这个规则记住"或"更新 KB"。

**Q: 手动改过的代码下次生成会不会覆盖？**
A: uibridge 生成到 `generated/` 目录，不会自动覆盖你项目里的文件。AI 手动移动时才需要判断。

**Q: KB 里的规则怎么查看？**
A: `.uibridge/kb/` 目录下是 YAML 文件，可以直接查看和手动编辑。

**Q: 生成的代码和目标目录怎么清理？**
A: `uibridge cleanup --dry-run` 预览，`uibridge cleanup --yes` 执行清理。会移除 `.uibridge/`、`generated/`、`recording.json` 及模板文件。
