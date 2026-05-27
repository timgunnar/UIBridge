"""Intent handler — classify user NL input into KB operations.

Pure regex/keyword matching. No LLM dependency.
"""

import re
from typing import Optional


class IntentHandler:
    """Recognize user intent from natural language instructions.

    Operates on raw text — classifies into one of:
    QUERY, ADD, MODIFY, DELETE, DOCUMENT, UNKNOWN
    """

    INTENTS = ["QUERY", "ADD", "MODIFY", "DELETE", "DOCUMENT", "UNKNOWN"]

    # ── classification rules ────────────────────────────────────────

    # Patterns that strongly indicate each intent.  Patterns are tried in
    # priority order: DELETE > MODIFY > ADD > QUERY > DOCUMENT > UNKNOWN.

    DELETE_PATTERNS = [
        (re.compile(r'(?:删[除掉去]?|移除|清除|去掉)\s*'),
         0.82),
        (re.compile(r'(?:delete|remove|drop|clear)\s+(?:rule|knowledge|entry|item|the)'),
         0.78),
        (re.compile(r'\b(?:delete|remove|drop|clear)\b', re.IGNORECASE),
         0.72),
    ]

    MODIFY_PATTERNS = [
        (re.compile(r'(?:修改|更改|改[成为]?|更新|变更|调整)'),
         0.80),
        (re.compile(r'(?:应该|必须|最好|建议|可以)\s*(?:用|使用|采用|换成|改为)'),
         0.72),
        (re.compile(r'(?:换[成为]?|变成|转为)\s*(?:用|使用|采用)?'),
         0.70),
        (re.compile(r'(?:modify|update|change|adjust|revise|replace)'),
         0.80),
        (re.compile(r'(?:should|must|need\s+to)\s+(?:use|change|switch)'),
         0.70),
    ]

    ADD_PATTERNS = [
        (re.compile(r'(?:新增|加入|添加|增加|录入|注册|记录)\s*(?:规则|知识|条目|一项)?'),
         0.85),
        (re.compile(r'(?:规则|rule)\s*[：:]\s*'),
         0.75),
        (re.compile(r'(?:add|insert|register|record|create)\s+(?:rule|knowledge|entry)'),
         0.80),
    ]

    QUERY_PATTERNS = [
        (re.compile(r'[？?]'),
         0.65),
        (re.compile(r'(?:什么是|是什么|怎么|如何|怎样|哪些|哪个|查询|告诉我|'
                     r'介绍一下|解释一下|了解|查一下|看看|查查)'),
         0.72),
        (re.compile(r'(?:what|how|which|where|who|explain|describe|'
                     r'list|show|tell|query|find|search|look\s+up)'),
         0.72),
        (re.compile(r'(?:定位器|组件|命名|规则|框架|目录|文件|配置)'
                     r'\s*(?:的|是什么|有哪些|怎么|如何)'),
         0.68),
    ]

    # ── parameter extraction patterns ────────────────────────────────

    # Extract key-value pairs from ADD/MODIFY statements
    KEY_VALUE_PATTERNS = [
        # "表格组件叫 DataGridAW"
        re.compile(
            r'(?P<subject>表格|表单|弹窗|对话框|下拉|菜单|导航|按钮|输入|'
            r'日期|时间|上传|分页|标签|卡片|搜索|过滤|树|列表|面板|table|form|'
            r'dialog|dropdown|menu|button|input|pagination|card|search|filter|'
            r'tree|list|panel)\s*(?:组件|控件)\s*(?:叫|是|为|名为|叫作|称为)'
            r'\s*(?P<value>[A-Za-z_]\w*)',
            re.IGNORECASE
        ),
        # "定位器使用 data-testid"
        re.compile(
            r'(?:定位器|locator)\s*(?:使用|用|采用)\s*(?P<value>(?:data-\w+|aria-\w+|'
            r'id|class|CSS|XPath|role|text|placeholder|testid))',
            re.IGNORECASE
        ),
        # "方法名用 click{Element}"
        re.compile(
            r'(?:方法|函数)\s*(?:名|名称)?\s*(?:用|使用|采用|格式为)'
            r'\s*(?P<value>[a-zA-Z_]\w*(?:\s*\{[^}]+\}\s*)+)',
            re.IGNORECASE
        ),
        # "key: value" / "key： value"
        re.compile(
            r'(?P<key>[A-Za-z_一-鿿][\w一-鿿]*)\s*[：:]\s*'
            r'(?P<value>[^\n，。,]{1,80})',
        ),
    ]

    def __init__(self):
        pass

    # ── public API ──────────────────────────────────────────────────

    def classify(self, text: str) -> tuple[str, float]:
        """Classify text into intent + confidence.

        Args:
            text: Raw user input (Chinese or English).

        Returns:
            (intent_type, confidence) where intent_type is one of:
            QUERY, ADD, MODIFY, DELETE, DOCUMENT, UNKNOWN
        """
        if not text or not text.strip():
            return ("UNKNOWN", 0.0)

        text = text.strip()

        # Check DOCUMENT first: long text with structural markers
        if self._is_document(text):
            return ("DOCUMENT", 0.85)

        # Run intent classification in priority order
        checks = [
            (self.DELETE_PATTERNS, "DELETE"),
            (self.MODIFY_PATTERNS, "MODIFY"),
            (self.ADD_PATTERNS, "ADD"),
            (self.QUERY_PATTERNS, "QUERY"),
        ]

        best_intent = "UNKNOWN"
        best_conf = 0.0

        for patterns, intent in checks:
            for pat, base_conf in patterns:
                if pat.search(text):
                    conf = min(base_conf + 0.05, 0.99)
                    if conf > best_conf:
                        best_conf = conf
                        best_intent = intent

        # If UNKNOWN but contains KB-related keywords, weak QUERY
        if best_intent == "UNKNOWN" and self._has_kb_keywords(text):
            return ("QUERY", 0.30)

        return (best_intent, best_conf)

    def extract_params(self, text: str, intent: str) -> dict:
        """Extract structured parameters based on the classified intent.

        Args:
            text: Raw user input.
            intent: Pre-classified intent type.

        Returns:
            dict with intent-specific fields:
            - ADD: {category, key, value, description}
            - MODIFY: {target_key, changes, new_value}
            - DELETE: {target_key}
            - QUERY: {query_terms}
        """
        if intent == "ADD":
            return self._extract_add_params(text)
        elif intent == "MODIFY":
            return self._extract_modify_params(text)
        elif intent == "DELETE":
            return self._extract_delete_params(text)
        elif intent == "QUERY":
            return self._extract_query_params(text)
        else:
            return {"raw_text": text}

    # ── document detection ────────────────────────────────────────

    @staticmethod
    def _is_document(text: str) -> bool:
        """Check if the input looks like a document rather than a command."""
        # Long text with structural markers → likely a document
        if len(text) > 400:
            return True
        # Contains markdown headings or code blocks
        if re.search(r'^#{1,6}\s', text, re.MULTILINE):
            return True
        if re.search(r'```', text):
            return True
        # Multiple paragraphs with topic sentences
        paragraphs = [p for p in text.split("\n\n") if len(p.strip()) > 30]
        if len(paragraphs) >= 2:
            return True
        return False

    @staticmethod
    def _has_kb_keywords(text: str) -> bool:
        """Check if text contains KB-relevant keywords for weak QUERY fallback."""
        keywords = [
            "定位器", "组件", "命名", "规则", "框架", "目录", "文件", "配置",
            "locator", "component", "naming", "rule", "framework",
            "structure", "config", "convention",
        ]
        text_lower = text.lower()
        return any(kw.lower() in text_lower for kw in keywords)

    # ── parameter extractors ────────────────────────────────────────

    def _extract_add_params(self, text: str) -> dict:
        """Extract structured params for ADD intent."""
        result = {
            "category": "",
            "key": "",
            "value": "",
            "description": text.strip()[:200],
        }

        for pat in self.KEY_VALUE_PATTERNS:
            m = pat.search(text)
            if m:
                groups = m.groupdict()
                if "value" in groups and groups["value"]:
                    result["value"] = groups["value"].strip()
                if "subject" in groups and groups["subject"]:
                    result["category"] = groups["subject"].strip()
                if "key" in groups and groups["key"]:
                    result["key"] = groups["key"].strip()

                # derive missing key from category/value
                if not result["key"] and result["category"]:
                    result["key"] = f"{result['category']}:{result['value']}"
                elif not result["key"] and result["value"]:
                    result["key"] = result["value"]
                break

        return result

    def _extract_modify_params(self, text: str) -> dict:
        """Extract structured params for MODIFY intent."""
        result = {
            "target_key": "",
            "changes": "",
            "new_value": "",
        }

        # Try to extract what's being changed and the new value
        for pat in self.KEY_VALUE_PATTERNS:
            m = pat.search(text)
            if m:
                groups = m.groupdict()
                if "value" in groups and groups["value"]:
                    result["new_value"] = groups["value"].strip()
                if "key" in groups and groups["key"]:
                    result["target_key"] = groups["key"].strip()
                if "subject" in groups and groups["subject"]:
                    result["target_key"] = groups["subject"].strip()
                break

        result["changes"] = text.strip()[:200]
        return result

    @staticmethod
    def _extract_delete_params(text: str) -> dict:
        """Extract structured params for DELETE intent."""
        result = {"target_key": ""}

        # Extract what to delete after the action verb
        delete_markers = ["删掉", "删除", "删去", "移除", "清除", "去掉",
                          "delete", "remove", "drop", "clear"]
        for marker in delete_markers:
            idx = text.lower().find(marker.lower())
            if idx >= 0:
                remaining = text[idx + len(marker):].strip()
                # take first meaningful fragment
                remaining = re.sub(r'^[的\s]+', '', remaining)
                if remaining and len(remaining) < 60:
                    result["target_key"] = remaining.rstrip("，。,.!！?？")
                break

        if not result["target_key"]:
            result["target_key"] = text.strip()[:60]

        return result

    @staticmethod
    def _extract_query_params(text: str) -> dict:
        """Extract search-relevant terms for QUERY intent."""
        # Strip question words and punctuation to get search terms
        cleaned = re.sub(r'[?？?！!。，,、]', ' ', text)
        # Remove common query prefixes
        cleaned = re.sub(
            r'(什么是|是什么|怎么|如何|怎样|哪些|哪个|查询|告诉我|介绍一下|'
            r'解释一下|了解|查一下|看看|查查|what\s+is|how\s+to|which|'
            r'explain|describe|list|show|tell\s+me|find)\s*',
            ' ', cleaned, flags=re.IGNORECASE
        )
        # Normalize whitespace
        terms = [t for t in cleaned.split() if t]
        return {
            "query_terms": " ".join(terms),
            "raw": text.strip(),
        }
