"""测试新能力：StyleLearner Java、KB 搜索/NL 操作/演化"""

import tempfile
from pathlib import Path

import pytest

from uibridge.generator.style_learner import StyleLearner, StyleProfile


# ═══════════════════════════════════════════════════════════════
# StyleLearner — Java 支持
# ═══════════════════════════════════════════════════════════════

class TestStyleLearnerJava:
    """StyleLearner Java 文件学习测试"""

    def test_learn_from_java_string(self):
        java_code = """
package com.example.tests;

import org.testng.annotations.Test;
import static org.assertj.core.api.Assertions.assertThat;

public class TestUserSearch {
    @Test
    public void testSearchUser() {
        assertThat(page.getTitle()).isEqualTo("Users");
    }
}
"""
        learner = StyleLearner()
        profile = learner._analyze_java(java_code)
        assert profile is not None
        assert profile.language == "java"
        assert profile.package_name == "com.example.tests"
        assert profile.assert_style == "assertj"
        assert profile.test_annotation == "@Test"

    def test_learn_java_testng_assert(self):
        java_code = """
package com.test;
import org.testng.Assert;
public class TestLogin {
    @Test
    public void testLogin() {
        Assert.assertEquals(page.getTitle(), "Login");
        Assert.assertTrue(page.isDisplayed());
    }
}
"""
        learner = StyleLearner()
        profile = learner._analyze_java(java_code)
        assert profile.assert_style == "testng_assert"

    def test_learn_java_extends(self):
        java_code = """
package com.test;
public class TestBase extends BaseTest {
    @Test
    public void testSomething() {}
}
"""
        learner = StyleLearner()
        profile = learner._analyze_java(java_code)
        assert profile.extends_class == "BaseTest"

    def test_java_comment_density(self):
        java_code = """
// comment 1
package com.test;
// comment 2
public class Test {
    // comment 3
    public void test() {}
}
"""
        learner = StyleLearner()
        profile = learner._analyze_java(java_code)
        assert profile.comment_density > 0.2

    def test_learn_python_preserved(self):
        learner = StyleLearner()
        # Write a temporary Python test file for analysis
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False, encoding="utf-8") as f:
            f.write("""
import pytest

class TestExample:
    def test_something(self):
        assert True
""")
            py_path = f.name
        try:
            profile = learner._analyze_python(py_path)
            assert profile is not None
            assert profile.language == "python"
        finally:
            Path(py_path).unlink(missing_ok=True)


# ═══════════════════════════════════════════════════════════════
# MCP Server 辅助函数
# ═══════════════════════════════════════════════════════════════

class TestMCPHelpers:
    """MCP Server URL 校验和路径安全化测试"""

    def test_validate_url_http(self):
        from uibridge.mcp.helpers import _validate_url
        assert _validate_url("https://example.com") == "https://example.com"

    def test_validate_url_about_blank(self):
        from uibridge.mcp.helpers import _validate_url
        assert _validate_url("about:blank") == "about:blank"

    def test_validate_url_rejects_empty(self):
        from uibridge.mcp.helpers import _validate_url
        with pytest.raises(ValueError, match="URL 不能为空"):
            _validate_url("")
        with pytest.raises(ValueError, match="URL 不能为空"):
            _validate_url("   ")

    def test_validate_url_rejects_javascript(self):
        from uibridge.mcp.helpers import _validate_url
        with pytest.raises(ValueError, match="禁止的 URL 协议"):
            _validate_url("javascript:alert(1)")

    def test_validate_url_rejects_data(self):
        from uibridge.mcp.helpers import _validate_url
        with pytest.raises(ValueError, match="禁止的 URL 协议"):
            _validate_url("data:text/html,<script>alert(1)</script>")

    def test_validate_url_rejects_no_scheme(self):
        from uibridge.mcp.helpers import _validate_url
        with pytest.raises(ValueError, match="URL 必须以 http"):
            _validate_url("example.com")

    def test_sanitize_output_path_inside_base(self):
        from uibridge.mcp.helpers import _sanitize_output_path
        result = _sanitize_output_path("recording.json")
        assert result.name == "recording.json"

    def test_sanitize_output_path_traversal_blocked(self):
        from uibridge.mcp.helpers import _sanitize_output_path
        result = _sanitize_output_path("../../../etc/passwd")
        assert result.name == "passwd"
        assert not str(result).startswith("/etc")


# ═══════════════════════════════════════════════════════════════
# KBStore — 搜索功能
# ═══════════════════════════════════════════════════════════════

class TestKBStoreSearch:
    """KBStore.search() 和 _keyword_search() 测试"""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        from uibridge.kb.store import KBStore
        self.store = KBStore(str(self.tmpdir.name))
        from uibridge.kb.item import KBItem, Confidence, KnowledgeSource
        self.items = [
            KBItem(id="t1", category="components", key="component_type.ButtonAW",
                   value={"xpath": "//button[@data-test='submit']"},
                   confidence=Confidence(score=0.9, source=KnowledgeSource.HUMAN_INJECTION),
                   description="Submit button component", tags=["button", "submit"]),
            KBItem(id="t2", category="components", key="component_type.TableAW",
                   value={"xpath": "//table[@data-module='user-list']"},
                   confidence=Confidence(score=0.7, source=KnowledgeSource.STATIC_ANALYSIS),
                   description="User list table with pagination", tags=["table", "user", "pagination"]),
            KBItem(id="t3", category="conventions", key="convention.locator.priority",
                   value={"priority": ["data-testid", "id", "xpath"]},
                   confidence=Confidence(score=0.85, source=KnowledgeSource.HUMAN_INJECTION),
                   description="定位器优先级约定", tags=["locator", "convention"]),
            KBItem(id="t4", category="patterns", key="pattern.login_flow",
                   value={"steps": ["enter_username", "enter_password", "click_login"]},
                   confidence=Confidence(score=0.5, source=KnowledgeSource.LLM_INFERENCE),
                   description="Login flow pattern", tags=["login", "auth"]),
        ]
        for item in self.items:
            self.store.save(item)

    def teardown_method(self):
        self.tmpdir.cleanup()

    def test_search_exact_match(self):
        results = self.store.search("ButtonAW")
        assert len(results) >= 1
        assert results[0].confidence.effective_score >= results[-1].confidence.effective_score

    def test_search_keyword_fallback(self):
        results = self.store.search("table pagination")
        assert len(results) >= 1
        assert any("TableAW" in r.key for r in results)

    def test_search_cjk_query(self):
        results = self.store.search("定位器")
        assert len(results) >= 1
        assert any("locator" in r.key for r in results)

    def test_search_empty_results_for_unmatched(self):
        results = self.store.search("zzz_nonexistent_xyz")
        assert results == []

    def test_search_ranks_by_combined_score(self):
        results = self.store.search("component")
        assert len(results) >= 2
        scores = [r.confidence.effective_score for r in results]
        assert scores == sorted(scores, reverse=True), \
            f"Results should be sorted by confidence desc, got {scores}"

    def test_keyword_search_ignores_low_relevance(self):
        results = self.store._keyword_search("login", min_score=0.1)
        assert len(results) >= 1
        keys = [r.key for r in results]
        assert "pattern.login_flow" in keys

    def test_keyword_search_empty_tokens(self):
        results = self.store._keyword_search("")
        assert results == []

    def test_keyword_search_single_token(self):
        results = self.store._keyword_search("button")
        assert len(results) >= 1
        assert any("ButtonAW" in r.key for r in results)


# ═══════════════════════════════════════════════════════════════
# KBManager — NL CRUD 操作
# ═══════════════════════════════════════════════════════════════

class TestKBNLOperations:
    """KBManager.operate_nl() NL CRUD 操作测试"""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        from uibridge.kb.manager import KBManager
        self.km = KBManager(str(self.tmpdir.name))
        self.km.inject(
            category="conventions", key="locator_priority",
            value={"priority": ["id", "xpath"]},
            description="默认定位器优先级: id > xpath",
        )
        self.km.inject(
            category="components", key="table_aw",
            value={"class_name": "TableAW", "xpath_pattern": "//table"},
            description="表格组件: TableAW, XPath 用 class 定位",
        )
        self.km.inject(
            category="patterns", key="login_flow",
            value={"steps": ["enter_username", "enter_password", "click_login"]},
            description="登录流程: 输入用户名 → 密码 → 点击登录",
        )

    def teardown_method(self):
        self.tmpdir.cleanup()

    def test_nl_query_finds_result(self):
        result = self.km.operate_nl("定位器优先级是什么？")
        assert result["status"] == "ok"
        assert result["intent"] == "QUERY"
        assert "locator" in result["result"].lower()

    def test_nl_query_no_result(self):
        result = self.km.operate_nl("有没有关于颜色的规则？")
        assert result["status"] == "ok"
        assert "No KB entries found" in result["result"]

    def test_nl_query_implicit(self):
        result = self.km.operate_nl("表格组件")
        assert result["intent"] == "QUERY"

    def test_nl_add_new_rule(self):
        result = self.km.operate_nl("新增规则：弹窗用 role='dialog' 识别")
        assert result["status"] == "ok"
        assert result["intent"] == "ADD"
        assert "dialog" in result["added"]["description"]
        items = self.km.store.list_category("components")
        assert any("dialog" in item.description for item in items)

    def test_nl_add_infers_category(self):
        result = self.km.operate_nl("添加表格组件的高亮功能")
        assert result["status"] == "ok"
        assert result["intent"] == "ADD"
        assert result["added"]["category"] == "components"

    def test_nl_modify_existing(self):
        result = self.km.operate_nl("表格组件的定位方式改为 data-testid")
        assert result["status"] == "ok"
        assert result["intent"] == "MODIFY"
        assert "table_aw" in result["modified"]["key"]
        item = self.km.store.get_by_key("components", "table_aw")
        assert item is not None
        assert "nl_modification" in item.value
        assert "data-testid" in item.value["nl_modification"]

    def test_nl_modify_not_found(self):
        result = self.km.operate_nl("把不存在的规则改成 xxx")
        assert result["status"] == "not_found"
        assert result.get("suggest_add") is True

    def test_nl_modify_with_should_pattern(self):
        result = self.km.operate_nl("定位器应该用 data-module")
        assert result["status"] == "ok"
        assert result["intent"] == "MODIFY"

    def test_nl_delete_existing(self):
        result = self.km.operate_nl("删掉登录流程的规则")
        assert result["status"] == "ok"
        assert result["intent"] == "DELETE"
        assert "login" in result["deleted"]["key"].lower()
        items = self.km.store.list_category("patterns")
        assert not any("login" in item.key for item in items)

    def test_nl_delete_not_found(self):
        result = self.km.operate_nl("删除不存在的规则")
        assert result["status"] == "not_found"
        assert result["intent"] == "DELETE"

    def test_nl_empty_instruction(self):
        result = self.km.operate_nl("")
        assert result["status"] in ("ok", "error")

    def test_nl_add_with_special_chars(self):
        result = self.km.operate_nl("新增: 表单校验规则 @NotNull @Size(min=1)")
        assert result["status"] == "ok"
        assert result["intent"] == "ADD"


# ═══════════════════════════════════════════════════════════════
# KBEvolution — KB 生命周期演化：衰减、泛化、归档
# ═══════════════════════════════════════════════════════════════

class TestKBEvolution:
    """KBEvolution: decay, generalize, archive lifecycle tests."""

    def test_evolve_applies_decay(self):
        import shutil
        import time
        from uibridge.kb.store import KBStore
        from uibridge.kb.item import KBItem, Confidence, KnowledgeSource
        from uibridge.kb.evolution import KBEvolution

        td = tempfile.mkdtemp()
        try:
            store = KBStore(td)
            item = KBItem(
                id="evolve_decay_1",
                category="components",
                key="component.test_decay",
                value={"xpath": "//btn"},
                confidence=Confidence(
                    score=0.8,
                    source=KnowledgeSource.LLM_INFERENCE,
                    last_validated_at=time.time() - 864000,
                ),
            )
            store.save(item)
            original_score = item.confidence.score

            evolution = KBEvolution(store)
            evolution.evolve()

            updated = store.get("components", "evolve_decay_1")
            assert updated is not None
            assert updated.confidence.score < original_score, \
                f"Score should decrease from {original_score}, got {updated.confidence.score}"
        finally:
            shutil.rmtree(td, ignore_errors=True)

    def test_evolve_ignores_archived(self):
        import shutil
        import time
        from uibridge.kb.store import KBStore
        from uibridge.kb.item import KBItem, Confidence, KnowledgeSource
        from uibridge.kb.evolution import KBEvolution

        td = tempfile.mkdtemp()
        try:
            store = KBStore(td)
            item = KBItem(
                id="evolve_archived_1",
                category="components",
                key="component.archived_item",
                value={"xpath": "//old"},
                confidence=Confidence(
                    score=0.1,
                    source=KnowledgeSource.PATTERN_MINING,
                    last_validated_at=time.time() - 864000,
                ),
                archived=True,
            )
            store.save(item)
            original_score = item.confidence.score

            evolution = KBEvolution(store)
            evolution.evolve()

            updated = store.get("components", "evolve_archived_1")
            assert updated is not None
            assert updated.confidence.score == original_score, \
                "Archived item score should not change"
            assert updated.archived is True
        finally:
            shutil.rmtree(td, ignore_errors=True)

    def test_evolve_archives_low_confidence_with_failures(self):
        import shutil
        from uibridge.kb.store import KBStore
        from uibridge.kb.item import KBItem, Confidence, KnowledgeSource
        from uibridge.kb.evolution import KBEvolution

        td = tempfile.mkdtemp()
        try:
            store = KBStore(td)
            item = KBItem(
                id="evolve_archive_1",
                category="components",
                key="component.archive_me",
                value={"xpath": "//bad"},
                confidence=Confidence(
                    score=0.15,
                    source=KnowledgeSource.HUMAN_INJECTION,
                    self_test_failures=3,
                ),
            )
            store.save(item)

            evolution = KBEvolution(store)
            evolution.evolve()

            updated = store.get("components", "evolve_archive_1")
            if updated is not None:
                assert updated.archived is True
            else:
                pass
        finally:
            shutil.rmtree(td, ignore_errors=True)

    def test_evolve_empty_store(self):
        import shutil
        from uibridge.kb.store import KBStore
        from uibridge.kb.evolution import KBEvolution

        td = tempfile.mkdtemp()
        try:
            store = KBStore(td)
            evolution = KBEvolution(store)
            evolution.evolve()
        finally:
            shutil.rmtree(td, ignore_errors=True)

    def test_generalize_boosts_patterns(self):
        import shutil
        from uibridge.kb.store import KBStore
        from uibridge.kb.item import KBItem, Confidence, KnowledgeSource
        from uibridge.kb.evolution import KBEvolution

        td = tempfile.mkdtemp()
        try:
            store = KBStore(td)
            for i in range(3):
                item = KBItem(
                    id=f"gen_{i}",
                    category="components",
                    key=f"component.gen_{i}",
                    value={"xpath": "//table", "role": "table"},
                    confidence=Confidence(
                        score=0.6,
                        source=KnowledgeSource.STATIC_ANALYSIS,
                    ),
                )
                store.save(item)

            evolution = KBEvolution(store)
            evolution.evolve()

            for i in range(3):
                updated = store.get("components", f"gen_{i}")
                assert updated is not None, f"Item gen_{i} should still exist"
                assert "generalized" in updated.tags, \
                    f"Item gen_{i} should have 'generalized' tag"
                assert updated.confidence.score > 0.64, \
                    f"Item gen_{i} score should be boosted, got {updated.confidence.score}"
        finally:
            shutil.rmtree(td, ignore_errors=True)
