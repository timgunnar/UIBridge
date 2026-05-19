---
name: uibridge
description: UI 自动化测试脚本智能生成 — 录制浏览器操作 → 自动生成测试代码
kind: skill
---

# uibridge — 测试脚本智能生成

## 何时调用

当用户提到以下意图时触发本 Skill：
- "帮我测 XXX 功能"
- "录一个 XXX 流程的测试"
- "基于这个页面生成测试"
- "发现页面组件"
- "分析这个项目用什么测试框架"

## 可用工具

本 Skill 依赖 MCP Server `uibridge`，暴露 9 个工具：

| 工具 | 用途 | 何时用 |
|------|------|--------|
| `analyze_page` | 分析页面组件（无头浏览器，独立于录制） | 用户说"分析一下这个页面" |
| `open_browser` | 打开可见浏览器（不录制） | 用户说"打开浏览器" |
| `start_recording` | 在已打开的浏览器上开始录制 | 用户预置完成后说"开始录制" |
| `stop_recording` | 停止录制，保存文件，关闭浏览器 | 用户操作完成后 |
| `generate_test_code` | 从录制生成测试代码 | 录制完成后自动调用 |
| `diff_snapshots` | 对比前后快照 | 用户问"应该断言什么" |
| `seed_knowledge_base` | 播种知识库 | 首次接入新项目 |
| `query_knowledge_base` | 查询框架约定 | 需要了解框架细节时 |
| `check_environment` | 检查 uibridge 运行环境 | 排查问题时 |

## 工作流

### 首次接入
```
1. 用户说: "这是我的 Java TestNG 项目，帮我接入"
2. 确认 .uibridge/adapter.yaml 存在，没有则从 templates/ 复制并调整
3. seed_knowledge_base(project_dir=".") 扫描源码播种 KB
4. 报告: "发现了 X 个组件、Y 个页面、Z 个约定"
```

### 录制新功能测试（三段式）

**关键原则：录制全程只用 uibridge 的浏览器。不要用 Playwright MCP 的 `browser_navigate` 或其他工具打开浏览器。**

```
1. 用户说: "帮我测用户管理的搜索功能"
2. analyze_page(url="http://localhost:8080/users") 了解页面
3. open_browser(url="...") 打开浏览器（此时不录制）
4. 提示用户"浏览器已打开，请先做预置操作（登录、导航等），准备好后告诉我"
5. 用户预置完成后说"好了/开始录制"
6. start_recording() 在已打开的浏览器上开始录制
7. 提示用户"录制中，请操作"
8. 用户操作完成并告知后，stop_recording() 结束录制
9. generate_test_code(input_file="recording.json") 生成代码
10. 检查自检结果，失败的自动修复
11. 报告用户: "生成了 ShouldSearchUser.java，mvn test 通过"
```

### 维护已有测试
```
1. 用户说: "XX 页面改版了，更新测试"
2. analyze_page(url="...") 对比新旧组件
3. 对新页面重新录制
4. generate_test_code 重新生成
5. 更新受影响的其他测试
```

## 项目适配器选择

读取 `.uibridge/adapter.yaml` 确定适配器。如果不存在，根据项目结构自动判断：

| 项目特征 | 适配器 |
|---------|--------|
| Python + pytest + ComponentAW | `reference` |
| Python + pytest + screenplay | `screenplay` |
| Java + TestNG + Page Object | `java_testng` |
| Java + TestNG + Fluent/AssertJ | `java_fluent` |

如果都不匹配，Agent 需要开发自定义适配器（参见 docs/adapter-guide.md）。
