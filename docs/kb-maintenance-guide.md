# 知识库维护指南

**如何查看、编辑、播种和版本控制你的 uibridge 知识库。**

---

## 知识库是什么

知识库（KB）是 `.uibridge/kb/` 目录下的 YAML 文件集合。它存储从你的项目源码中自动提取的框架约定，以及你通过自然语言反馈注入的规则。

**知识库决定了生成代码的包名、import、组件类名、定位器优先级和断言风格。**

```
.uibridge/kb/
├── components/     ← 组件类名、方法、定位器
│   ├── table.yaml
│   ├── form.yaml
│   └── ...
├── conventions/    ← 命名约定、定位器优先级、import 风格
│   ├── naming_rules.yaml
│   ├── locator_priority.yaml
│   └── ...
├── patterns/       ← 频繁操作序列模式
│   └── composite_actions.yaml
├── pages/          ← 页面构成信息
│   └── page_registry.yaml
└── archive/        ← 低置信度归档条目
```

---

## 查看知识库

### 直接查看 YAML 文件

```bash
ls .uibridge/kb/
cat .uibridge/kb/conventions/locator_priority.yaml
```

### 通过 Agent 查询

```
你：查询 KB 中关于定位器优先级的约定
Agent：[调用 query_knowledge_base("定位器优先级")]
       → 返回当前约定和置信度
```

---

## 播种知识库

播种（Seed）是从项目源码中提取框架知识的过程。

### 自动播种（Agent）

```
你：扫描我的项目源码，建立知识库
Agent：调用 seed_knowledge_base(project_dir=".")
       → 扫描 pages/、tests/、data/ 目录
       → 报告：发现 8 个组件、12 个页面、5 个约定
```

### 手动播种（CLI）

```bash
# 在项目目录下
python -c "
from uibridge.kb.kb_manager import KBManager
kb = KBManager(project_root='.')
kb.seed_from_source_dirs(['src/main/java/**/pages/', 'src/test/java/**/tests/'])
kb.persist()
print('KB seeded:', kb.summary())
"
```

### 播种内容

| 源文件 | 提取内容 | 初始置信度 |
|--------|---------|-----------|
| `pages/*.java` | 组件类名、方法签名、定位器模式 | 0.6-0.8 |
| `tests/*.java` | 测试命名、断言风格、import 列表 | 0.6-0.8 |
| `data/*.java` | 数据格式（Builder/常量/JSON） | 0.7 |
| 设计文档 | 命名约定、架构说明 | 0.5 |

---

## 置信度机制

每个 KB 条目都有置信度（0.0~1.0），决定是否被生成代码采纳。

| 来源 | 初始置信度 | 说明 |
|------|-----------|------|
| 自动提取 | 0.6-0.8 | 源码静态分析，可能有误 |
| 自检通过 | +0.02/次 | 每次生成代码通过自检 |
| 自检失败 | -0.25/次 | 每次生成代码编译/运行失败 |
| 用户 NL 反馈 | 0.9-0.99 | "这个规则记住" — 高置信度 |
| 手动编辑 | 0.95 | 直接改 YAML，可手动设 confidence |
| 长期未用 | 逐步衰减 | 超过 30 天不使用开始衰减 |
| 低置信度 | → archive | 低于 0.3 自动归档 |

### 置信度阈值

| 范围 | 含义 | 生成时行为 |
|------|------|-----------|
| 0.8-1.0 | 高置信度 | 直接采纳 |
| 0.5-0.8 | 中置信度 | 采纳，但标记 review_needed |
| 0.3-0.5 | 低置信度 | 不采纳，使用默认值 |
| <0.3 | 归档 | 移入 archive/，不参与生成 |

---

## 通过 NL 反馈修正 KB

当生成的代码不符合团队约定时，直接告诉 Agent：

```
你："生成的定位器用的是 id，我们项目统一用 data-testid 属性"

Agent：1. 修改当前生成的代码
       2. 更新 KB → 定位器优先级改为 data-testid 优先
       3. "KB 已更新。后续生成都会遵循此约定。"
```

常见反馈类型：

| 你说的 | KB 变化 | 影响范围 |
|--------|---------|---------|
| "定位器用 data-testid" | locator_priority 更新 | 所有生成代码的定位策略 |
| "断言用 AssertJ" | assert_style 更新 | 所有测试脚本的断言 |
| "类名用 XxxPage 不是 XxxAW" | naming_rules 更新 | 所有组件的命名 |
| "这个组件多了 getRowCount()" | 组件方法列表更新 | 该组件的 AW |
| "测试数据用 Builder" | data_format 更新 | 数据生成模板 |

---

## 手动编辑 KB

KB 是纯 YAML，可直接编辑：

```yaml
# .uibridge/kb/conventions/locator_priority.yaml
category: conventions
key: convention.locator_priority
value:
  priority:
    - data-testid      # ← 编辑：调整优先级顺序
    - data-module
    - id
    - name
    - css
confidence: 0.95       # ← 编辑：手动设定置信度
description: "用户确认 data-testid 为首选定位属性"
last_validated_at: "2026-05-17"
```

编辑后下次生成即刻生效，无需重启。

---

## 版本控制

KB 是 YAML 文件，天然适合 Git 管理：

```bash
git add .uibridge/kb/
git commit -m "KB: 更新定位器优先级为 data-testid"
```

**团队共享 KB**：

```bash
# 团队成员 A：提交 KB 更新
git push origin main

# 团队成员 B：拉取 KB 更新
git pull origin main
# KB 即刻生效，下次生成使用新规则
```

**建议**：将 `.uibridge/kb/` 加入 Git 仓库。`.uibridge/` 下的 `adapter.yaml` 也应纳入版本控制。

---

## 归档与清理

### 自动归档

低置信度条目（<0.3）自动移入 `archive/` 目录，不参与生成。可在 90 天后手动删除归档条目。

### 手动清理 KB

```bash
# 预览归档条目
ls .uibridge/kb/archive/

# 删除归档
rm -rf .uibridge/kb/archive/

# 完全重置 KB
rm -rf .uibridge/kb/
# 然后重新播种：seed_knowledge_base(project_dir=".")
```

### 完全卸载（含 KB）

```bash
uibridge cleanup --yes    # 移除 .uibridge/、generated/ 等
pip uninstall uibridge -y # 卸载 Python 包
```

---

## 常见问题

**Q: KB 的 YAML 文件可以直接删除吗？**
A: 可以。删除后下次 `seed_knowledge_base` 会重新提取。手工编辑的条目会丢失。

**Q: 如何确认 KB 是否生效？**
A: 看生成的代码。如果 `package` 和 `import` 使用了你的实际包名（而非 `com.acme`），说明 KB 集成正常。

**Q: 多个团队成员同时编辑 KB 会冲突吗？**
A: KB 是 YAML 文件，Git 合并冲突的处理方式和普通代码一样。建议小步提交。

**Q: KB 条目太多会影响性能吗？**
A: 不会。高置信度条目通常 <50 个，YAML 解析极快。
