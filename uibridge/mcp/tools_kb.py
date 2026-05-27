"""MCP tools for knowledge base management."""
import json
from pathlib import Path
from typing import Optional

from .server import mcp


@mcp.tool()
async def seed_knowledge_base(
    project_dir: str,
) -> str:
    """从企业项目的源码目录提取知识，播种知识库。

    用于：首次接入新项目时，扫描源码提取组件、页面、约定等信息。
    支持 Python（AST）和 Java（javalang）源码。

    参数：
    - project_dir: 项目根目录路径
    返回：播种的 KB 条目数量和分类。
    """
    from uibridge.kb.manager import KBManager

    km = KBManager(project_dir)
    items = km.auto_seed()
    if not items:
        # KB 已有足够条目，返回当前状态
        existing = km.store.list_all()
        categories = {}
        for item in existing:
            categories[item.category] = categories.get(item.category, 0) + 1
        return json.dumps({
            "status": "ok",
            "message": "KB 已有足够条目，跳过自动播种",
            "total_items": len(existing),
            "by_category": categories,
            "kb_dir": str(Path(project_dir) / ".uibridge" / "kb"),
        }, indent=2, ensure_ascii=False)

    categories = {}
    for item in items:
        categories[item.category] = categories.get(item.category, 0) + 1

    return json.dumps({
        "status": "ok",
        "total_items": len(items),
        "by_category": categories,
        "kb_dir": str(Path(project_dir) / ".uibridge" / "kb"),
    }, indent=2, ensure_ascii=False)


@mcp.tool()
async def query_knowledge_base(
    query: str,
    project_dir: str = ".",
) -> str:
    """查询知识库，获取框架约定、组件信息等。

    用于：Agent 需要了解"这个项目的定位器优先级是什么"、"TableAW 用什么 XPath"等。

    参数：
    - query: 自然语言查询词（如 "定位器约定"、"TableAW"）
    - project_dir: 项目根目录路径
    返回：匹配的 KB 条目。
    """
    from uibridge.kb.manager import KBManager

    km = KBManager(project_dir)
    result = km.query_nl(query)
    return result


@mcp.tool()
async def update_knowledge_base(
    instruction: str,
    project_dir: str = ".",
) -> str:
    """通过自然语言指令操作知识库：查询、新增、修改、删除条目。

    用于：用户通过 Agent 对话来管理 KB，Agent 将此工具暴露给用户。
    支持 4 种意图：
    - QUERY: "表格组件的定位方式是什么？"
    - ADD:   "新增规则：弹窗用 role='dialog' 识别"
    - MODIFY:"把表格组件的定位方式改为 data-testid"
    - DELETE:"删掉表格排序的规则"

    KB 文件存储在 project_dir/.uibridge/kb/ 下，可 commit 到版本控制。

    参数：
    - instruction: 自然语言指令（中文/英文）
    - project_dir: 项目根目录路径
    返回：操作结果。
    """
    from uibridge.kb.manager import KBManager

    km = KBManager(project_dir)
    result = km.operate_nl(instruction)
    return json.dumps(result, indent=2, ensure_ascii=False)


@mcp.tool()
async def add_kb_rule(
    category: str,
    key: str,
    value_json: str,
    description: str = "",
    project_dir: str = ".",
) -> str:
    """新增 KB 规则。结构化参数，由 LLM 客户端解析用户的 NL 输入后填入。

    Args:
        category: conventions | components | patterns | pages
        key: 人类可读的规则键名，如 "locator.table"
        value_json: JSON 字符串，知识载荷，如 '{"preferred_attribute": "data-module"}'
        description: 可读描述
        project_dir: 项目根目录
    """
    from uibridge.kb.manager import KBManager
    from uibridge.kb.item import KnowledgeSource
    from uibridge.kb.audit import AuditLogger

    valid_cats = {"conventions", "components", "patterns", "pages"}
    if category not in valid_cats:
        return json.dumps({"error": f"Invalid category. Must be one of: {valid_cats}"},
                          indent=2, ensure_ascii=False)
    try:
        value = json.loads(value_json)
    except json.JSONDecodeError as e:
        return json.dumps({"error": f"Invalid value_json: {e}"}, indent=2, ensure_ascii=False)

    audit = AuditLogger(project_dir)
    km = KBManager(project_dir, audit_logger=audit)
    item = km.inject(category=category, key=key, value=value, description=description)
    item.confidence.source = KnowledgeSource.HUMAN_INJECTION
    km.store.save(item)

    return json.dumps({"status": "ok", "message": f"Added [{category}] {key}",
                       "item_id": item.id, "category": category, "key": key},
                      indent=2, ensure_ascii=False)


@mcp.tool()
async def modify_kb_rule(
    category: str,
    item_key: str,
    corrections_json: str,
    nl_note: str = "",
    project_dir: str = ".",
) -> str:
    """修改已有 KB 规则。按 key 查找，按 corrections_json 更新 value 字段。

    Args:
        category: conventions | components | patterns | pages
        item_key: 规则的 key（如 "locator.table"），非 ID
        corrections_json: JSON 字符串，要更新的字段，如 '{"preferred_attribute": "role"}'
        nl_note: 用户 NL 原文，记录在审计日志中
        project_dir: 项目根目录
    """
    from uibridge.kb.manager import KBManager
    from uibridge.kb.audit import AuditLogger

    try:
        corrections = json.loads(corrections_json)
    except json.JSONDecodeError as e:
        return json.dumps({"error": f"Invalid corrections_json: {e}"}, indent=2, ensure_ascii=False)

    audit = AuditLogger(project_dir)
    km = KBManager(project_dir, audit_logger=audit)

    item = km.store.get_by_key(category, item_key)
    if not item:
        return json.dumps({"error": f"KB item not found: {category}/{item_key}"},
                          indent=2, ensure_ascii=False)

    before = {"value": item.value.copy(), "description": item.description}
    km.correct(category, item.id, corrections, nl_note=nl_note)
    after_item = km.store.get(category, item.id)

    return json.dumps({"status": "ok", "message": f"Modified [{category}] {item_key}",
                       "old_value": before["value"],
                       "new_value": after_item.value if after_item else {}},
                      indent=2, ensure_ascii=False)


@mcp.tool()
async def delete_kb_rule(
    category: str,
    item_key: str,
    project_dir: str = ".",
) -> str:
    """删除（归档）KB 规则。按 key 查找。

    Args:
        category: conventions | components | patterns | pages
        item_key: 规则的 key
        project_dir: 项目根目录
    """
    from uibridge.kb.manager import KBManager
    from uibridge.kb.audit import AuditLogger

    audit = AuditLogger(project_dir)
    km = KBManager(project_dir, audit_logger=audit)

    item = km.store.get_by_key(category, item_key)
    if not item:
        return json.dumps({"error": f"KB item not found: {category}/{item_key}"},
                          indent=2, ensure_ascii=False)

    before = {"category": item.category, "key": item.key,
              "value": item.value.copy(), "description": item.description}
    km.store.archive(item)
    audit.log("kb.delete", f"{category}/{item_key}", before, {},
              source="delete_kb_rule")

    return json.dumps({"status": "ok", "message": f"Deleted [{category}] {item_key}",
                       "deleted": before}, indent=2, ensure_ascii=False)


@mcp.tool()
async def query_kb_rules(
    query: str = "",
    category: str = "",
    min_confidence: float = 0.3,
    project_dir: str = ".",
) -> str:
    """查询 KB 规则，返回结构化 JSON。

    Args:
        query: 搜索词（留空返回全部）
        category: 按分类过滤（留空返回全部）
        min_confidence: 最低置信度阈值
        project_dir: 项目根目录
    """
    from uibridge.kb.manager import KBManager

    km = KBManager(project_dir)

    if category:
        items = km.store.list_category(category)
        if query:
            q_lower = query.lower()
            items = [i for i in items
                     if q_lower in f"{i.key} {i.description} {str(i.value)}".lower()]
    elif query:
        items = km.store.search(query)
    else:
        items = km.store.list_all()

    items = [i for i in items
             if i.confidence.effective_score >= min_confidence and not i.archived]

    return json.dumps({
        "status": "ok",
        "count": len(items),
        "items": [{"category": i.category, "key": i.key, "id": i.id,
                   "value": i.value, "description": i.description,
                   "confidence": i.confidence.effective_score,
                   "source": i.confidence.source.value} for i in items],
    }, indent=2, ensure_ascii=False)
