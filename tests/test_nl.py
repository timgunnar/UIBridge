"""Tests for uibridge.nl — document ingestion, intent classification, dialogue."""

import pytest

from uibridge.nl import DocumentIngestor, IntentHandler, DialogueManager


# ══════════════════════════════════════════════════════════
# DocumentIngestor tests
# ══════════════════════════════════════════════════════════

class TestDocumentIngestNaming:
    """Test extraction of naming conventions from documents."""

    def test_aw_class_pattern(self):
        ingestor = DocumentIngestor()
        text = "AW类名格式为{Component}AW，例如 TableAW、FormAW。"
        items = ingestor.ingest(text, source_name="test.md")

        assert len(items) >= 1
        naming = [i for i in items if i["category"] == "naming_convention"]
        assert len(naming) >= 1
        assert any("{Component}AW" in n["value"] for n in naming)

    def test_method_naming_chinese(self):
        ingestor = DocumentIngestor()
        text = "方法名用click{Element}，例如 clickButton、clickLink。"
        items = ingestor.ingest(text)

        naming = [i for i in items if i["category"] == "naming_convention"]
        assert len(naming) >= 1
        assert any("click{Element}" in n["value"] for n in naming)

    def test_naming_convention_with_label(self):
        ingestor = DocumentIngestor()
        text = "命名规则: 页面对象必须以 Page 结尾"
        items = ingestor.ingest(text)

        naming = [i for i in items if i["category"] == "naming_convention"]
        assert len(naming) >= 1
        assert any("Page" in n["value"] for n in naming)

    def test_english_naming_pattern(self):
        ingestor = DocumentIngestor()
        text = "class names follow the pattern {Module}Page"
        items = ingestor.ingest(text)

        naming = [i for i in items if i["category"] == "naming_convention"]
        assert len(naming) >= 1

    def test_variable_naming_camelcase(self):
        ingestor = DocumentIngestor()
        text = "变量命名规则为 CamelCase"
        items = ingestor.ingest(text)

        naming = [i for i in items if i["category"] == "naming_convention"]
        assert len(naming) >= 1
        assert any("CamelCase" in n["value"] for n in naming)


class TestDocumentIngestLocator:
    """Test extraction of locator strategies from documents."""

    def test_unified_data_module(self):
        ingestor = DocumentIngestor()
        text = "统一使用data-module属性定位元素。"
        items = ingestor.ingest(text)

        locators = [i for i in items if i["category"] == "locator_strategy"]
        assert len(locators) >= 1
        assert any("data-module" in l["value"] for l in locators)

    def test_forbidden_xpath(self):
        ingestor = DocumentIngestor()
        text = "禁止使用XPath，统一用data-testid。"
        items = ingestor.ingest(text)

        locators = [i for i in items if i["category"] == "locator_strategy"]
        assert len(locators) >= 1
        forbidden = [l for l in locators if "forbidden" in l.get("key", "")]
        assert len(forbidden) >= 1
        assert any("XPath" in f["value"] for f in forbidden)

    def test_locator_use_data_testid(self):
        ingestor = DocumentIngestor()
        text = "locator使用data-testid属性"
        items = ingestor.ingest(text)

        locators = [i for i in items if i["category"] == "locator_strategy"]
        assert len(locators) >= 1
        assert any("data-testid" in l["value"].lower() for l in locators)

    def test_locator_strategy_colon_format(self):
        ingestor = DocumentIngestor()
        text = "定位策略: data-cy"
        items = ingestor.ingest(text)

        locators = [i for i in items if i["category"] == "locator_strategy"]
        assert len(locators) >= 1

    def test_via_data_attribute_find_element(self):
        ingestor = DocumentIngestor()
        text = "通过data-testid查找元素"
        items = ingestor.ingest(text)

        locators = [i for i in items if i["category"] == "locator_strategy"]
        assert len(locators) >= 1


class TestDocumentIngestComponent:
    """Test extraction of component information from documents."""

    def test_table_component_datagridaw(self):
        ingestor = DocumentIngestor()
        text = "表格组件叫DataGridAW"
        items = ingestor.ingest(text)

        components = [i for i in items if i["category"] == "component"]
        assert len(components) >= 1
        assert any("DataGridAW" in c["value"] for c in components)

    def test_form_component_chinese(self):
        ingestor = DocumentIngestor()
        text = "表单组件叫FormHandlerAW"
        items = ingestor.ingest(text)

        components = [i for i in items if i["category"] == "component"]
        assert len(components) >= 1
        assert any("FormHandlerAW" in c["value"] for c in components)

    def test_component_is_wrapper(self):
        ingestor = DocumentIngestor()
        text = "TableAW是我们封装的表格组件"
        items = ingestor.ingest(text)

        components = [i for i in items if i["category"] == "component"]
        assert len(components) >= 1
        assert any("TableAW" in c["value"] for c in components)

    def test_button_component(self):
        ingestor = DocumentIngestor()
        text = "按钮控件称为ClickButton"
        items = ingestor.ingest(text)

        components = [i for i in items if i["category"] == "component"]
        assert len(components) >= 1
        assert any("ClickButton" in c["value"] for c in components)


class TestDocumentIngestFileStructure:
    """Test extraction of file structure info from documents."""

    def test_xpath_constants_file(self):
        ingestor = DocumentIngestor()
        text = "XPath注册在XPathConstants.java"
        items = ingestor.ingest(text)

        files = [i for i in items if i["category"] == "file_structure"]
        assert len(files) >= 1
        assert any("XPathConstants.java" in f["value"] for f in files)

    def test_test_location(self):
        ingestor = DocumentIngestor()
        text = "测试用例在 src/test/java/tests/"
        items = ingestor.ingest(text)

        files = [i for i in items if i["category"] == "file_structure"]
        assert len(files) >= 1

    def test_source_location(self):
        ingestor = DocumentIngestor()
        text = "源码在 src/main/java/com/acme/"
        items = ingestor.ingest(text)

        files = [i for i in items if i["category"] == "file_structure"]
        assert len(files) >= 1

    def test_english_config_location(self):
        ingestor = DocumentIngestor()
        text = "constants are defined in Constants.java"
        items = ingestor.ingest(text)

        files = [i for i in items if i["category"] == "file_structure"]
        assert len(files) >= 1


class TestDocumentIngestEmpty:
    """Edge cases: empty or whitespace-only input."""

    def test_empty_string(self):
        ingestor = DocumentIngestor()
        items = ingestor.ingest("")
        assert items == []

    def test_whitespace_only(self):
        ingestor = DocumentIngestor()
        items = ingestor.ingest("   \n  \t  ")
        assert items == []

    def test_no_knowledge_text(self):
        ingestor = DocumentIngestor()
        items = ingestor.ingest("hello world, this is just random text.")
        assert items == []

    def test_source_name_tagging(self):
        ingestor = DocumentIngestor()
        text = "AW类名格式为{Component}AW"
        items = ingestor.ingest(text, source_name="framework_guide.md")

        for item in items:
            assert "source:framework_guide.md" in item.get("tags", [])

    def test_confidence_in_range(self):
        ingestor = DocumentIngestor()
        text = "表格组件叫DataGridAW，定位器使用data-testid，AW类名格式为{Component}AW"
        items = ingestor.ingest(text)

        for item in items:
            conf = item.get("confidence", 0)
            assert 0.0 <= conf <= 1.0


class TestDocumentIngestStructuredDoc:
    """Test ingestion of a realistic multi-paragraph document."""

    def test_full_document(self):
        ingestor = DocumentIngestor()
        text = """# 框架约定文档

## 命名规则
- AW类名格式为{Component}AW，如TableAW、FormAW
- 方法名用click{Element}和type{Field}格式

## 定位器策略
- 统一使用data-module属性
- 禁止使用XPath和索引

## 组件说明
- 表格组件叫DataGridAW
- 弹窗组件叫DialogHandler
- FormAW是我们封装的表单组件

## 文件结构
- XPath注册在XPathConstants.java
- 测试用例在 src/test/java/tests/
"""
        items = ingestor.ingest(text, source_name="conventions.md")

        categories = set(i["category"] for i in items)
        assert "naming_convention" in categories
        assert "locator_strategy" in categories
        assert "component" in categories
        assert "file_structure" in categories

        # Should have multiple items across categories
        assert len(items) >= 4

        # All should be tagged
        for item in items:
            assert "source:conventions.md" in item.get("tags", [])
            assert "doc_extracted" in item.get("tags", [])


# ══════════════════════════════════════════════════════════
# IntentHandler tests
# ══════════════════════════════════════════════════════════

class TestIntentClassifyQuery:
    """Classify question-like text as QUERY."""

    def test_chinese_question_what(self):
        handler = IntentHandler()
        intent, conf = handler.classify("定位器优先级是什么？")
        assert intent == "QUERY"
        assert conf > 0.3

    def test_chinese_question_how(self):
        handler = IntentHandler()
        intent, conf = handler.classify("如何命名新的表格组件？")
        assert intent == "QUERY"
        assert conf > 0.3

    def test_chinese_question_which(self):
        handler = IntentHandler()
        intent, conf = handler.classify("哪些组件支持自定义操作？")
        assert intent == "QUERY"
        assert conf > 0.3

    def test_english_question(self):
        handler = IntentHandler()
        intent, conf = handler.classify("what is the locator strategy?")
        assert intent == "QUERY"
        assert conf > 0.3

    def test_keyword_with_question_mark(self):
        handler = IntentHandler()
        intent, conf = handler.classify("命名规则？")
        assert intent == "QUERY"
        assert conf > 0.3


class TestIntentClassifyAdd:
    """Classify addition-like text as ADD."""

    def test_add_rule_colon(self):
        handler = IntentHandler()
        intent, conf = handler.classify("规则：弹窗用role='dialog'")
        assert intent == "ADD"
        assert conf > 0.3

    def test_new_rule_explicit(self):
        handler = IntentHandler()
        intent, conf = handler.classify("新增规则：弹窗用role='dialog'")
        assert intent == "ADD"
        assert conf > 0.3

    def test_add_knowledge_entry(self):
        handler = IntentHandler()
        intent, conf = handler.classify("加入规则：所有按钮使用data-testid定位")
        assert intent == "ADD"
        assert conf > 0.3

    def test_english_add(self):
        handler = IntentHandler()
        intent, conf = handler.classify("add rule: use data-testid for all buttons")
        assert intent == "ADD"
        assert conf > 0.3


class TestIntentClassifyModify:
    """Classify modification-like text as MODIFY."""

    def test_modify_locator_strategy(self):
        handler = IntentHandler()
        intent, conf = handler.classify("定位器应该用data-testid")
        assert intent == "MODIFY"
        assert conf > 0.3

    def test_change_to_new_value(self):
        handler = IntentHandler()
        intent, conf = handler.classify("改用aria-label作为首要选择器")
        assert intent in ("MODIFY",)  # 改用 matches modify patterns
        assert conf > 0.3

    def test_update_rule(self):
        handler = IntentHandler()
        intent, conf = handler.classify("更新：组件命名改为{Module}Component")
        assert intent in ("MODIFY", "ADD")
        assert conf > 0.3

    def test_english_modify(self):
        handler = IntentHandler()
        intent, conf = handler.classify("modify rule: use data-testid")
        assert intent in ("MODIFY", "ADD")
        assert conf > 0.3


class TestIntentClassifyDelete:
    """Classify deletion-like text as DELETE."""

    def test_delete_rule(self):
        handler = IntentHandler()
        intent, conf = handler.classify("删掉登录流程的规则")
        assert intent == "DELETE"
        assert conf > 0.3

    def test_remove_entry(self):
        handler = IntentHandler()
        intent, conf = handler.classify("移除XPath定位器条目")
        assert intent == "DELETE"
        assert conf > 0.3

    def test_clear_knowledge(self):
        handler = IntentHandler()
        intent, conf = handler.classify("清除旧的命名规则")
        assert intent == "DELETE"
        assert conf > 0.3

    def test_english_delete(self):
        handler = IntentHandler()
        intent, conf = handler.classify("delete the login rule")
        assert intent == "DELETE"
        assert conf > 0.3


class TestIntentClassifyDocument:
    """Classify long-form text as DOCUMENT."""

    def test_long_text_document(self):
        handler = IntentHandler()
        text = (
            "A" * 500 + " 这是很长的文档内容，包含了框架的命名约定、"
            "定位器策略、组件说明等多个部分。"
        )
        intent, conf = handler.classify(text)
        assert intent == "DOCUMENT"

    def test_markdown_headings(self):
        handler = IntentHandler()
        text = "# 标题\n\n## 小标题\n\n这是文档内容。"
        intent, conf = handler.classify(text)
        assert intent == "DOCUMENT"

    def test_code_blocks(self):
        handler = IntentHandler()
        text = "```java\npublic class Foo {}\n```"
        intent, conf = handler.classify(text)
        assert intent == "DOCUMENT"

    def test_multi_paragraph(self):
        handler = IntentHandler()
        text = (
            "这是一段比较长的描述文本，包含了多个句子的内容。"
            "框架使用Selenium作为底层驱动，封装了常用的UI组件。\n\n"
            "第二段落描述了命名约定的具体细节。"
            "所有AW类必须以AW结尾，方法名使用驼峰命名。"
        )
        intent, conf = handler.classify(text)
        assert intent == "DOCUMENT"


class TestIntentClassifyUnknown:
    """Edge cases for UNKNOWN classification."""

    def test_empty_string(self):
        handler = IntentHandler()
        intent, conf = handler.classify("")
        assert intent == "UNKNOWN"
        assert conf == 0.0

    def test_whitespace_only(self):
        handler = IntentHandler()
        intent, conf = handler.classify("   \n  ")
        assert intent == "UNKNOWN"
        assert conf == 0.0

    def test_random_text(self):
        handler = IntentHandler()
        intent, conf = handler.classify("hello world foo bar baz")
        assert intent in ("QUERY", "UNKNOWN")

    def test_kb_keyword_weak_query(self):
        handler = IntentHandler()
        intent, conf = handler.classify("组件")
        # single KB keyword → weak QUERY
        assert intent == "QUERY"
        assert conf < 0.5


class TestIntentExtractParams:
    """Test parameter extraction for various intents."""

    def test_extract_add_table_component(self):
        handler = IntentHandler()
        params = handler.extract_params(
            "表格组件叫DataGridAW",
            "ADD"
        )
        assert "value" in params
        assert params["value"] == "DataGridAW"

    def test_extract_add_locator(self):
        handler = IntentHandler()
        params = handler.extract_params(
            "定位器使用data-testid",
            "ADD"
        )
        assert "value" in params
        assert "data-testid" in params["value"]

    def test_extract_add_method_naming(self):
        handler = IntentHandler()
        params = handler.extract_params(
            "方法名用click{Element}格式",
            "ADD"
        )
        assert "value" in params
        assert "click{Element}" in params.get("value", "")

    def test_extract_modify(self):
        handler = IntentHandler()
        params = handler.extract_params(
            "定位器应该用data-testid",
            "MODIFY"
        )
        assert "new_value" in params
        assert "target_key" in params

    def test_extract_delete(self):
        handler = IntentHandler()
        params = handler.extract_params(
            "删掉登录流程的规则",
            "DELETE"
        )
        assert "target_key" in params
        assert len(params["target_key"]) > 0

    def test_extract_query(self):
        handler = IntentHandler()
        params = handler.extract_params(
            "定位器优先级是什么？",
            "QUERY"
        )
        assert "query_terms" in params
        assert "定位器" in params["query_terms"] or "定位器" in params.get("raw", "")

    def test_extract_unknown(self):
        handler = IntentHandler()
        params = handler.extract_params("random text", "UNKNOWN")
        assert "raw_text" in params


# ══════════════════════════════════════════════════════════
# DialogueManager tests
# ══════════════════════════════════════════════════════════

class TestDialogueShouldAskConflict:
    """Test should_ask when there are conflicting low-confidence findings."""

    def test_two_conflicting_low_confidence(self):
        dm = DialogueManager()
        conflicts = [{
            "findings": [
                {"category": "locator_strategy", "confidence": 0.25,
                 "value": "data-module", "description": "统一使用data-module"},
                {"category": "locator_strategy", "confidence": 0.30,
                 "value": "data-testid", "description": "统一使用data-testid"},
            ]
        }]
        # Both findings are low confidence (< 0.4), 2 findings, critical category
        assert dm.should_ask(conflicts) is True

    def test_three_findings_low_confidence(self):
        dm = DialogueManager()
        conflicts = [{
            "findings": [
                {"category": "component", "confidence": 0.20,
                 "value": "DataGridAW", "description": "表格组件叫DataGridAW"},
                {"category": "component", "confidence": 0.30,
                 "value": "TableAW", "description": "表格组件叫TableAW"},
                {"category": "component", "confidence": 0.35,
                 "value": "GridComponent", "description": "表格组件叫GridComponent"},
            ]
        }]
        assert dm.should_ask(conflicts) is True

    def test_naming_convention_conflict(self):
        dm = DialogueManager()
        conflicts = [{
            "findings": [
                {"category": "naming_convention", "confidence": 0.15,
                 "value": "{Component}AW"},
                {"category": "naming_convention", "confidence": 0.25,
                 "value": "{Module}Page"},
            ]
        }]
        assert dm.should_ask(conflicts) is True


class TestDialogueShouldNotAsk:
    """Test should_ask returns False when conditions are not met."""

    def test_single_finding(self):
        dm = DialogueManager()
        conflicts = [{
            "findings": [
                {"category": "locator_strategy", "confidence": 0.25,
                 "value": "data-module"},
            ]
        }]
        # Only 1 finding, min is 2
        assert dm.should_ask(conflicts) is False

    def test_two_findings_high_confidence(self):
        dm = DialogueManager()
        conflicts = [{
            "findings": [
                {"category": "locator_strategy", "confidence": 0.75,
                 "value": "data-module"},
                {"category": "locator_strategy", "confidence": 0.80,
                 "value": "data-testid"},
            ]
        }]
        # High confidence, should not trigger
        assert dm.should_ask(conflicts) is False

    def test_two_findings_non_critical_category(self):
        dm = DialogueManager()
        conflicts = [{
            "findings": [
                {"category": "misc", "confidence": 0.20, "value": "foo"},
                {"category": "misc", "confidence": 0.25, "value": "bar"},
            ]
        }]
        # Non-critical category → won't affect correctness
        assert dm.should_ask(conflicts) is False

    def test_empty_conflicts(self):
        dm = DialogueManager()
        assert dm.should_ask([]) is False

    def test_one_low_one_high_confidence(self):
        dm = DialogueManager()
        conflicts = [{
            "findings": [
                {"category": "locator_strategy", "confidence": 0.25,
                 "value": "data-module"},
                {"category": "locator_strategy", "confidence": 0.85,
                 "value": "data-testid"},
            ]
        }]
        # Only 1 low-confidence, min is 2
        assert dm.should_ask(conflicts) is False


class TestDialogueFormatQuestion:
    """Test that format_question produces readable output."""

    def test_formats_two_findings(self):
        dm = DialogueManager()
        conflict = {
            "findings": [
                {"category": "locator_strategy", "confidence": 0.25,
                 "value": "data-module", "description": "统一使用data-module"},
                {"category": "locator_strategy", "confidence": 0.30,
                 "value": "data-testid", "description": "统一使用data-testid"},
            ]
        }
        question = dm.format_question(conflict)
        assert "locator_strategy" in question
        assert "data-module" in question
        assert "data-testid" in question
        assert len(question) > 0

    def test_formats_single_finding(self):
        dm = DialogueManager()
        conflict = {
            "findings": [
                {"category": "component", "confidence": 0.25,
                 "value": "TableAW", "description": "表格组件叫TableAW"},
            ]
        }
        question = dm.format_question(conflict)
        assert "component" in question
        assert "TableAW" in question

    def test_formats_empty(self):
        dm = DialogueManager()
        question = dm.format_question({"findings": []})
        assert question == ""


class TestDialogueProcessAnswer:
    """Test answer processing extracts knowledge correctly."""

    def test_confirmed_answer(self):
        dm = DialogueManager()
        context = {
            "findings": [
                {"category": "locator_strategy", "confidence": 0.25,
                 "value": "data-module"},
                {"category": "locator_strategy", "confidence": 0.30,
                 "value": "data-testid"},
            ]
        }
        result = dm.process_answer(context, "是的，用data-testid，这是对的。")
        assert result["category"] == "locator_strategy"
        assert "dialogue_confirmed" in result["tags"]
        assert result["confidence"] >= 0.90

    def test_unconfirmed_answer(self):
        dm = DialogueManager()
        context = {
            "findings": [
                {"category": "component", "confidence": 0.25,
                 "value": "OldName"},
                {"category": "component", "confidence": 0.30,
                 "value": "NewName"},
            ]
        }
        result = dm.process_answer(context, "应该叫CustomTableAW")
        assert result["category"] == "component"
        assert "dialogue_answered" in result["tags"]
        assert result["confidence"] >= 0.80
        assert "CustomTableAW" in result["value"]

    def test_non_identifier_answer(self):
        dm = DialogueManager()
        context = {
            "findings": [
                {"category": "locator_strategy", "confidence": 0.20,
                 "value": "data-module"},
            ]
        }
        result = dm.process_answer(context, "就用我们一直用的那个定位方式吧")
        assert result["category"] == "locator_strategy"
        assert len(result["value"]) > 0
