"""Document ingestion — parse markdown/text docs to extract structured KB knowledge.

Pure regex/keyword matching. No LLM dependency.
"""

import re
from typing import Optional


class DocumentIngestor:
    """Parse markdown/text documents to extract structured KB knowledge items.

    Each extracted item is a dict with: category, key, value, description,
    confidence, tags.  Confidence defaults to 0.7 for document-sourced knowledge
    (lower than human_injection but higher than pattern_mining).
    """

    SOURCE_CONFIDENCE = 0.7

    # ── pattern registry ──────────────────────────────────────────────

    # Chinese + English naming convention patterns
    NAMING_PATTERNS = [
        # "AW类名格式为{Component}AW"
        (re.compile(
            r'(?:AW|页面对象|组件)\s*(?:类名|命名|格式|规则)\S{0,4}(?:为|是|使用|采用)'
            r'\s*(?P<pattern>\{[^}]+\}\s*(?:AW|Page|PO|Screen)?(?:[+\s]*\{[^}]+\})?)',
            re.IGNORECASE
        ), 0.75),
        # "方法名用click{Element}" / "method names use click{Element}"
        (re.compile(
            r'(?:方法名|函数名|方法|函数)\s*(?:用|使用|采用|格式为|是)'
            r'\s*(?P<pattern>[a-zA-Z_]\w*(?:\s*\{[^}]+\}\s*)+)',
            re.IGNORECASE
        ), 0.75),
        # English: "class names follow the pattern {Component}AW"
        (re.compile(
            r'(?:class|component)\s+(?:names?|naming)\s+(?:follow|use|are)'
            r'\s+(?:the\s+)?(?:pattern\s+)?(?P<pattern>\{[^}]+\}\s*(?:AW|Page|PO|Screen)?)',
            re.IGNORECASE
        ), 0.70),
        # "变量命名规则为 CamelCase"
        (re.compile(
            r'(?:变量|包|目录|文件)\s*(?:命名|名称|规则|格式)'
            r'\S{0,4}(?:为|是|使用|采用)\s*(?P<pattern>(?:CamelCase|snake_case|'
            r'PascalCase|kebab-case|UPPER_CASE|lowercase|中文拼音))',
            re.IGNORECASE
        ), 0.70),
        # Generic: "命名规则: xxx" / "naming convention: xxx"
        (re.compile(
            r'(?:命名规则|naming\s+convention)s?\s*[：:]\s*(?P<pattern>.+?)(?:$|\n)',
            re.IGNORECASE
        ), 0.65),
        # "包名小写" / "package names are lowercase"
        (re.compile(
            r'(?:包名|package\s+names?)\s*(?:为|是|are|should\s+be)\s*'
            r'(?P<pattern>(?:小写|lowercase|全小写))',
            re.IGNORECASE
        ), 0.65),
    ]

    # Chinese + English locator strategy patterns
    LOCATOR_PATTERNS = [
        # "统一使用data-module属性" / "统一使用 data-module 属性"
        (re.compile(
            r'(?:统一|优先|必须|始终|一律|只|只能)\s*(?:使用|用|通过)'
            r'\s*(?P<strategy>(?:data-\w+|aria-\w+|id|class|name|CSS|XPath|'
            r'role|text|placeholder|testid|test-id|data-testid))',
            re.IGNORECASE
        ), 0.80),
        # "不要用XPath" / "禁止使用XPath"
        (re.compile(
            r'(?:不要|禁止|避免|不准|切勿|绝不)\s*(?:使用|用|写)'
            r'\s*(?P<forbidden>(?:XPath|CSS\s*Selector|id|class|name|绝对路径|'
            r'索引|index|下标|坐标))',
            re.IGNORECASE
        ), 0.80),
        # "locator使用data-module"
        (re.compile(
            r'(?:locator|定位器|选择器)\s*(?:使用|用|采用|是)'
            r'\s*(?P<strategy>(?:data-\w+|aria-\w+|id|class|CSS|XPath|'
            r'role|text|placeholder|testid))',
            re.IGNORECASE
        ), 0.75),
        # "Locator strategy: data-testid"
        (re.compile(
            r'(?:locator|定位)\s*(?:strategy|策略|方式|方案)\s*[：:]\s*'
            r'(?P<strategy>.+?)(?:$|\n|，|。)',
            re.IGNORECASE
        ), 0.70),
        # "通过data-module查找元素"
        (re.compile(
            r'(?:通过|使用|用)\s*(?P<strategy>(?:data-\w+|aria-\w+|id|class|CSS|'
            r'XPath))\s*(?:查找|定位|获取|找到)',
            re.IGNORECASE
        ), 0.65),
    ]

    # Component info patterns
    COMPONENT_PATTERNS = [
        # "表格组件叫DataGridAW" / "表格组件叫 DataGridAW"
        (re.compile(
            r'(?P<comp_type>表格|表单|弹窗|对话框|下拉|菜单|导航|按钮|输入|'
            r'日期|时间|上传|文件|分页|翻页|标签|卡片|搜索|筛选|过滤|树|'
            r'列表|步骤|进度|通知|提示|抽屉|面板|table|form|dialog|'
            r'dropdown|menu|nav|button|input|date|time|upload|pagination|'
            r'card|search|filter|tree|list|steps|progress|notification|'
            r'drawer|panel)\s*(?:组件|控件|模块|元素)\s*(?:叫|是|为|名为|叫作|'
            r'叫做|称为)\s*(?P<name>[A-Za-z_]\w*)',
            re.IGNORECASE
        ), 0.85),
        # "DataGridAW是我们封装的表格组件"
        (re.compile(
            r'(?P<name>[A-Z][A-Za-z_]*)\s*(?:是|为我们|是我们)\s*(?:封装|自定义|'
            r'自己)\s*(?:的|了)\s*(?P<comp_type>表格|表单|弹窗|对话框|下拉|菜单|'
            r'导航|按钮|输入|日期|时间|上传|分页|标签|卡片|搜索|过滤|树|列表|'
            r'步骤|面板|table|form|dialog|dropdown|menu|button|input|pagination|'
            r'card|search|filter|tree|list|panel)\s*(?:组件|控件|模块)',
            re.IGNORECASE
        ), 0.80),
        # "Component hierarchy: DataGridAW extends BaseAW"
        (re.compile(
            r'(?:component|组件)\s*(?:hierarchy|层级|继承)\s*[：:]\s*'
            r'(?P<info>.+?)(?:$|\n)',
            re.IGNORECASE
        ), 0.65),
    ]

    # File structure patterns
    FILE_STRUCTURE_PATTERNS = [
        # "XPath注册在XPathConstants.java" / "XPath定义在XPathConstants.java"
        (re.compile(
            r'(?P<what>(?:XPath|定位符|选择器|locator|URL|配置|常量|枚举|工具|'
            r'基类|工厂|数据|模型))\s*(?:注册在|定义在|存放于|位于|注册|定义|存放|放在|写|位于|在)'
            r'\s*(?P<where>[A-Za-z_][\w./]*\.(?:java|py|xml|json|ya?ml|'
            r'properties|cfg|ini|ts|js))',
            re.IGNORECASE
        ), 0.80),
        # "constants defined in Constants.java"
        (re.compile(
            r'(?P<what>(?:constants?|config|utils?|helpers?|base|common|core))'
            r'\s*(?:is |are |)\s*(?:defined|located|placed|found)\s+(?:in|under)'
            r'\s*(?P<where>[A-Za-z_][\w./]*\.(?:java|py|xml|json|ya?ml|ts|js))',
            re.IGNORECASE
        ), 0.70),
        # "测试用例在 src/test/java/tests/" / "源码在 src/main/java/com/acme/"
        (re.compile(
            r'(?P<what>(?:测试用例|测试|源码|工具|组件|页面|数据|配置|test|src|pages?|'
            r'components?|utils?|data|config))\s*(?:在|位于|存放于|under|in)'
            r'\s*(?P<where>[A-Za-z_][\w./-]+(?:/[A-Za-z_][\w./-]*)*)',
            re.IGNORECASE
        ), 0.65),
    ]

    def __init__(self):
        pass

    # ── public API ──────────────────────────────────────────────────

    def ingest(self, content: str, source_name: str = "") -> list[dict]:
        """Parse document content and return extracted knowledge items.

        Args:
            content: Markdown or plain text document content.
            source_name: Optional label for the source (e.g. filename).

        Returns:
            List of knowledge item dicts, each with:
            category, key, value, description, confidence, tags
        """
        if not content or not content.strip():
            return []

        items: list[dict] = []
        text = content

        items.extend(self._extract_naming_conventions(text))
        items.extend(self._extract_locator_strategies(text))
        items.extend(self._extract_component_info(text))
        items.extend(self._extract_file_structure(text))

        # tag items with source
        for item in items:
            item.setdefault("tags", [])
            if source_name:
                item["tags"].append(f"source:{source_name}")
            item.setdefault("confidence", self.SOURCE_CONFIDENCE)

        return items

    # ── extractors ──────────────────────────────────────────────────

    def _extract_naming_conventions(self, text: str) -> list[dict]:
        """Extract naming conventions from text."""
        items: list[dict] = []
        seen = set()

        for pattern, base_conf in self.NAMING_PATTERNS:
            for m in pattern.finditer(text):
                raw = m.group("pattern").strip().rstrip("，。,.")
                if raw in seen:
                    continue
                seen.add(raw)

                desc = self._build_naming_desc(m, text)
                items.append({
                    "category": "naming_convention",
                    "key": f"naming:{raw[:40]}",
                    "value": raw,
                    "description": desc,
                    "confidence": min(base_conf + 0.05, 0.99),
                    "tags": ["naming", "doc_extracted"],
                })

        return items

    def _extract_locator_strategies(self, text: str) -> list[dict]:
        """Extract locator strategy rules from text."""
        items: list[dict] = []
        seen = set()

        for pattern, base_conf in self.LOCATOR_PATTERNS:
            for m in pattern.finditer(text):
                group = m.groupdict()

                if "strategy" in group and group["strategy"]:
                    key_val = group["strategy"].strip().rstrip("，。,.")
                    if key_val in seen:
                        continue
                    seen.add(key_val)
                    items.append({
                        "category": "locator_strategy",
                        "key": f"locator_strategy:{key_val}",
                        "value": key_val,
                        "description": self._build_locator_desc(m, text, "strategy"),
                        "confidence": min(base_conf + 0.05, 0.99),
                        "tags": ["locator", "doc_extracted"],
                    })

                if "forbidden" in group and group["forbidden"]:
                    key_val = group["forbidden"].strip().rstrip("，。,.")
                    if key_val in seen:
                        continue
                    seen.add(key_val)
                    items.append({
                        "category": "locator_strategy",
                        "key": f"locator_forbidden:{key_val}",
                        "value": key_val,
                        "description": self._build_locator_desc(m, text, "forbidden"),
                        "confidence": min(base_conf + 0.05, 0.99),
                        "tags": ["locator", "forbidden", "doc_extracted"],
                    })

        return items

    def _extract_component_info(self, text: str) -> list[dict]:
        """Extract component descriptions from text."""
        items: list[dict] = []
        seen = set()

        for pattern, base_conf in self.COMPONENT_PATTERNS:
            for m in pattern.finditer(text):
                name = m.group("name").strip()
                comp_type = (m.groupdict().get("comp_type") or "").strip()

                dedup_key = f"{name}|{comp_type}"
                if dedup_key in seen:
                    continue
                seen.add(dedup_key)

                desc = f"组件 '{name}' 类型为 {comp_type}" if comp_type else \
                    f"组件 '{name}'"

                # derive key from info if present
                if "info" in m.groupdict() and m.group("info"):
                    desc = m.group("info").strip()

                items.append({
                    "category": "component",
                    "key": f"component:{name}",
                    "value": name,
                    "description": desc,
                    "confidence": min(base_conf + 0.05, 0.99),
                    "tags": ["component", "doc_extracted"],
                })

        return items

    def _extract_file_structure(self, text: str) -> list[dict]:
        """Extract file/project structure information from text."""
        items: list[dict] = []
        seen = set()

        for pattern, base_conf in self.FILE_STRUCTURE_PATTERNS:
            for m in pattern.finditer(text):
                what = m.group("what").strip()
                where = m.group("where").strip().rstrip("，。,.")

                dedup_key = f"{what}|{where}"
                if dedup_key in seen:
                    continue
                seen.add(dedup_key)

                items.append({
                    "category": "file_structure",
                    "key": f"file:{what}",
                    "value": where,
                    "description": f"{what} 位于 {where}",
                    "confidence": min(base_conf + 0.05, 0.99),
                    "tags": ["file_structure", "doc_extracted"],
                })

        return items

    # ── helpers ─────────────────────────────────────────────────────

    @staticmethod
    def _build_naming_desc(match: re.Match, full_text: str) -> str:
        """Build a readable description for a naming convention match."""
        # extract the sentence context (up to 2 sentences)
        start = max(0, match.start() - 60)
        end = min(len(full_text), match.end() + 100)
        snippet = full_text[start:end].replace("\n", " ").strip()
        # truncate if too long
        if len(snippet) > 120:
            snippet = snippet[:117] + "..."
        return f"从文档提取的命名约定: {snippet}"

    @staticmethod
    def _build_locator_desc(match: re.Match, full_text: str,
                            field: str) -> str:
        """Build a readable description for a locator strategy match."""
        start = max(0, match.start() - 40)
        end = min(len(full_text), match.end() + 80)
        snippet = full_text[start:end].replace("\n", " ").strip()
        if len(snippet) > 120:
            snippet = snippet[:117] + "..."
        prefix = "禁止的定位方式" if field == "forbidden" else "定位策略"
        return f"从文档提取的{prefix}: {snippet}"
