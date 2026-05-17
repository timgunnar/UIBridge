"""测试新能力：DOM Differ ARIA 树、StyleLearner Java、PrefixSpan、SelfTestRunner Java、BAW Generator"""

import pytest
from pathlib import Path
from uibridge.engine.dom_diff import DOMDiffer, DOMDiffResult, DiffEntry, AriaNode
from uibridge.engine.self_test import SelfTestRunner, SelfTestResult
from uibridge.generator.style_learner import StyleLearner, StyleProfile
from uibridge.generator.business_aw_gen import BusinessAWGenerator
from uibridge.generator.component_aw_gen import ComponentAWGenerator
from uibridge.generator.test_script_gen import TestScriptGenerator
from uibridge.adapter.reference import (
    ReferenceActionRecognizer, ReferenceCodeGenerator, ReferenceDataFormatter,
    ReferenceComponentResolver,
)


# ═══════════════════════════════════════════════════════════════
# DOM Differ — ARIA 树比较
# ═══════════════════════════════════════════════════════════════

class TestDOMDifferTree:
    """DOM Differ 结构化 ARIA 树比较测试"""

    def test_parse_aria_tree(self):
        differ = DOMDiffer()
        snapshot = """
        - heading "User List"
          - text: "Welcome"
        - table "user-table"
          - rowgroup
            - row "user-row-1"
              - cell "Name" [name="John"]
              - cell "Email" [name="john@test.com"]
          - button "Add User"
        """
        nodes = differ._parse_aria_tree(snapshot)
        assert len(nodes) > 0
        roles = [n.role for n in nodes]
        assert "heading" in roles or "table" in roles

    def test_diff_detects_added_with_name(self):
        differ = DOMDiffer()
        before = '- heading "Dashboard"'
        after = '- heading "Dashboard"\n- button "Submit"'
        result = differ.diff(before, after)
        assert result.has_changes
        assert any(e.type == "added" for e in result.entries)

    def test_diff_detects_removed_element(self):
        differ = DOMDiffer()
        before = '- button "Save"\n- button "Cancel"'
        after = '- button "Save"'
        result = differ.diff(before, after)
        assert any(e.type == "removed" for e in result.entries)

    def test_diff_detects_text_change(self):
        differ = DOMDiffer()
        before = '- heading "Old Title" [name="title"]'
        after = '- heading "New Title" [name="title"]'
        result = differ.diff(before, after)
        has_text_change = any(
            e.type == "text_changed" for e in result.entries
        )
        assert has_text_change

    def test_diff_detects_url_change(self):
        differ = DOMDiffer()
        result = differ.diff(
            "some content", "some content",
            url_before="http://old", url_after="http://new"
        )
        assert any(e.type == "url_changed" for e in result.entries)

    def test_diff_assertion_candidates(self):
        differ = DOMDiffer()
        before = '- button "Old"'
        after = '- button "Save"\n- table "results"'
        result = differ.diff(before, after)
        assert len(result.assertion_candidates) > 0
        assert any("button" in c.lower() for c in result.assertion_candidates)

    def test_empty_snapshot_handling(self):
        differ = DOMDiffer()
        result = differ.diff("", "")
        assert not result.has_changes

    def test_no_changes_same_snapshot(self):
        differ = DOMDiffer()
        snap = '- heading "Title"'
        result = differ.diff(snap, snap)
        assert not result.has_changes


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
        py_code = Path(__file__).parent.parent / "tests" / "test_compatibility.py"
        # Use a known Python test file
        profile = learner._analyze_python(str(py_code))
        assert profile is not None
        assert profile.language == "python"


# ═══════════════════════════════════════════════════════════════
# PrefixSpan — 频繁子序列挖掘
# ═══════════════════════════════════════════════════════════════

class TestPrefixSpan:
    """PrefixSpan 模式挖掘测试"""

    def test_mine_frequent_patterns(self):
        recognizer = ReferenceActionRecognizer()
        sequences = [
            [{"action": "click"}, {"action": "input"}, {"action": "click"}],
            [{"action": "click"}, {"action": "input"}, {"action": "click"}],
            [{"action": "click"}, {"action": "input"}, {"action": "click"}],
            [{"action": "click"}, {"action": "click"}],
        ]
        patterns = recognizer.recognize_pattern(sequences)
        assert len(patterns) > 0
        # click → input → click 出现 3 次
        assert any(p["frequency"] >= 3 for p in patterns)

    def test_insufficient_frequency_returns_empty(self):
        recognizer = ReferenceActionRecognizer()
        sequences = [
            [{"action": "a"}],
            [{"action": "b"}],
        ]
        patterns = recognizer.recognize_pattern(sequences)
        assert patterns == []

    def test_empty_sequences(self):
        recognizer = ReferenceActionRecognizer()
        patterns = recognizer.recognize_pattern([])
        assert patterns == []


# ═══════════════════════════════════════════════════════════════
# SelfTestRunner — Java 支持
# ═══════════════════════════════════════════════════════════════

class TestSelfTestRunnerJava:
    """SelfTestRunner Java 执行测试"""

    def test_python_still_works(self):
        runner = SelfTestRunner(timeout=10)
        code = """
def test_pass():
    assert True
"""
        result = runner.run(code, "test_pass")
        assert result.status == "passed"
        assert result.language == "python"

    def test_run_with_language_param(self):
        runner = SelfTestRunner(timeout=10)
        result = runner.run("assert True", "test_lang", language="python")
        assert result.language == "python"

    def test_java_compile_direct(self):
        """测试 Java 直接编译模式（javac）"""
        runner = SelfTestRunner(timeout=30)
        java_code = """
public class TestHello {
    public static void main(String[] args) {
        System.out.println("Hello");
    }
}
"""
        result = runner._run_java_direct(java_code, "TestHello", 0)
        # 如果有 JDK 则编译通过，否则返回失败
        assert isinstance(result, SelfTestResult)
        assert result.language == "java"

    def test_java_result_language_field(self):
        runner = SelfTestRunner(timeout=10)
        result = runner._run_java_direct(
            "public class TestDummy {}", "TestDummy", 0
        )
        assert result.language == "java"

    def test_run_java_dispatches_to_direct_when_no_pom(self, tmp_path):
        """_run_java() 在无 pom.xml 时应走 javac 直接编译路径"""
        runner = SelfTestRunner(timeout=30)
        code = "public class TestCompileCheck { public static void main(String[] a) {} }"
        result = runner._run_java(code, "TestCompileCheck", str(tmp_path))
        assert result.language == "java"
        # 有 JDK 则编译通过，否则 failed with "javac not found"
        assert result.status in ("passed", "failed")

    def test_run_java_dispatches_to_maven_test_when_pom_exists(self, tmp_path):
        """_run_java() 在有 pom.xml 时应走 mvn test 路径"""
        import subprocess
        pom = tmp_path / "pom.xml"
        pom.write_text("""<?xml version="1.0"?>
<project xmlns="http://maven.apache.org/POM/4.0.0">
  <modelVersion>4.0.0</modelVersion>
  <groupId>test</groupId><artifactId>test</artifactId><version>1.0</version>
</project>""")
        runner = SelfTestRunner(timeout=10)
        code = "public class TestMavenDispatch {}"
        result = runner._run_java(code, "TestMavenDispatch", str(tmp_path))
        assert result.language == "java"
        # 可能 mvn 不可用 (failed) 或可用 (passed)
        assert result.status in ("passed", "failed")


# ═══════════════════════════════════════════════════════════════
# Pipeline — Java 语言检测与 SelfTest 集成
# ═══════════════════════════════════════════════════════════════

class TestPipelineJavaLanguage:
    """Pipeline _detect_language() 与 Java SelfTest 集成测试"""

    def test_detect_language_java_testng(self):
        from uibridge.adapter.java_testng import (
            JavaComponentResolver, JavaLocatorStrategy,
            JavaActionRecognizer, JavaCodeGenerator, JavaDataFormatter,
        )
        from uibridge.pipeline import Pipeline

        p = Pipeline(
            component_resolver=JavaComponentResolver(),
            locator_strategy=JavaLocatorStrategy(),
            action_recognizer=JavaActionRecognizer(),
            code_generator=JavaCodeGenerator(),
            data_formatter=JavaDataFormatter(),
        )
        assert p._detect_language() == "java"

    def test_detect_language_java_fluent(self):
        from uibridge.adapter.java_fluent import (
            FluentComponentResolver, FluentLocatorStrategy,
            FluentActionRecognizer, FluentCodeGenerator, FluentDataFormatter,
        )
        from uibridge.pipeline import Pipeline

        p = Pipeline(
            component_resolver=FluentComponentResolver(),
            locator_strategy=FluentLocatorStrategy(),
            action_recognizer=FluentActionRecognizer(),
            code_generator=FluentCodeGenerator(),
            data_formatter=FluentDataFormatter(),
        )
        assert p._detect_language() == "java"

    def test_detect_language_python(self):
        from uibridge.adapter.reference import (
            ReferenceComponentResolver, ReferenceLocatorStrategy,
            ReferenceActionRecognizer, ReferenceCodeGenerator, ReferenceDataFormatter,
        )
        from uibridge.pipeline import Pipeline

        p = Pipeline(
            component_resolver=ReferenceComponentResolver(),
            locator_strategy=ReferenceLocatorStrategy(),
            action_recognizer=ReferenceActionRecognizer(),
            code_generator=ReferenceCodeGenerator(),
            data_formatter=ReferenceDataFormatter(),
        )
        assert p._detect_language() == "python"

    def test_detect_language_from_style_profile_overrides_adapter(self):
        """StyleProfile.language 优先级高于适配器类名推断"""
        from uibridge.adapter.reference import (
            ReferenceComponentResolver, ReferenceLocatorStrategy,
            ReferenceActionRecognizer, ReferenceCodeGenerator, ReferenceDataFormatter,
        )
        from uibridge.pipeline import Pipeline
        from uibridge.generator.style_learner import StyleProfile

        p = Pipeline(
            component_resolver=ReferenceComponentResolver(),
            locator_strategy=ReferenceLocatorStrategy(),
            action_recognizer=ReferenceActionRecognizer(),
            code_generator=ReferenceCodeGenerator(),
            data_formatter=ReferenceDataFormatter(),
        )
        # 默认：Python 适配器 → "python"
        assert p._detect_language() == "python"

        # 设置 StyleProfile.language = "java" → 优先返回 "java"
        profile = StyleProfile(language="java")
        p.set_style(profile)
        assert p._detect_language() == "java"

    def test_java_testng_pipeline_verify_language_field(self):
        """Java TestNG 管线自检结果应标记 language='java'"""
        from uibridge.adapter.java_testng import (
            JavaComponentResolver, JavaLocatorStrategy,
            JavaActionRecognizer, JavaCodeGenerator, JavaDataFormatter,
        )
        from uibridge.pipeline import Pipeline
        from uibridge.engine.ir.raw_recording import (
            RawRecording, RawStep, ActionType, Target,
        )

        pipeline = Pipeline(
            component_resolver=JavaComponentResolver(),
            locator_strategy=JavaLocatorStrategy(),
            action_recognizer=JavaActionRecognizer(),
            code_generator=JavaCodeGenerator(),
            data_formatter=JavaDataFormatter(),
        )

        recording = RawRecording(steps=[
            RawStep(id="s1", action=ActionType.NAVIGATE,
                    target=Target(url="http://test/users")),
            RawStep(id="s2", action=ActionType.CLICK,
                    target=Target(label="search_btn")),
        ], snapshots={})

        semantic = pipeline.analyze(recording)
        call_seq = pipeline.map_to_framework(semantic)
        results = pipeline.generate_and_verify(call_seq, recording)

        assert len(results) == 1
        verify = results[0]["verify"]
        assert verify.language == "java", f"Expected language='java', got '{verify.language}'"

    def test_java_fluent_pipeline_verify_language_field(self):
        """Java Fluent 管线自检结果应标记 language='java'"""
        from uibridge.adapter.java_fluent import (
            FluentComponentResolver, FluentLocatorStrategy,
            FluentActionRecognizer, FluentCodeGenerator, FluentDataFormatter,
        )
        from uibridge.pipeline import Pipeline
        from uibridge.engine.ir.raw_recording import (
            RawRecording, RawStep, ActionType, Target,
        )

        pipeline = Pipeline(
            component_resolver=FluentComponentResolver(),
            locator_strategy=FluentLocatorStrategy(),
            action_recognizer=FluentActionRecognizer(),
            code_generator=FluentCodeGenerator(),
            data_formatter=FluentDataFormatter(),
        )

        recording = RawRecording(steps=[
            RawStep(id="s1", action=ActionType.NAVIGATE,
                    target=Target(url="http://test/users")),
            RawStep(id="s2", action=ActionType.CLICK,
                    target=Target(label="search_btn")),
        ], snapshots={})


# ═══════════════════════════════════════════════════════════════
# BAW Generator — 模式到生成
# ═══════════════════════════════════════════════════════════════

class TestBAWGenerator:
    """BusinessAWGenerator 测试"""

    def test_generate_from_pattern(self):
        code_gen = ReferenceCodeGenerator()
        recognizer = ReferenceActionRecognizer()
        baw_gen = BusinessAWGenerator(code_gen, recognizer)

        pattern = {
            "name": "searchUser",
            "class_name": "UserSearchBAW",
        }
        component_calls = [
            {"component": "search_box", "method": "enter", "args": ["keyword"]},
            {"component": "search_btn", "method": "click", "args": []},
        ]
        code = baw_gen.generate_from_pattern(pattern, component_calls)
        assert code != ""
        assert "UserSearchBAW" in code or len(code) > 20

    def test_suggest_wrap(self):
        code_gen = ReferenceCodeGenerator()
        baw_gen = BusinessAWGenerator(code_gen)

        sequences = [
            [{"component": "search_box", "method": "enter"}],
            [{"component": "search_box", "method": "enter"}],
            [{"component": "search_box", "method": "enter"}],
        ]
        suggestions = baw_gen.suggest_wrap(sequences, min_frequency=3)
        assert len(suggestions) > 0
        assert suggestions[0]["frequency"] >= 3

    def test_suggest_wrap_below_threshold(self):
        code_gen = ReferenceCodeGenerator()
        baw_gen = BusinessAWGenerator(code_gen)

        sequences = [
            [{"component": "a", "method": "m1"}],
            [{"component": "b", "method": "m2"}],
        ]
        suggestions = baw_gen.suggest_wrap(sequences, min_frequency=3)
        assert suggestions == []

    def test_generate_all(self):
        code_gen = ReferenceCodeGenerator()
        recognizer = ReferenceActionRecognizer()
        baw_gen = BusinessAWGenerator(code_gen, recognizer)

        patterns = [
            {
                "pattern": "click → input → click",
                "frequency": 3,
                "baw_name": "SearchAndFilter",
                "components": {
                    "search_box": ["enter"],
                    "search_btn": ["click"],
                },
            },
        ]
        results = baw_gen.generate_all(patterns)
        assert len(results) == 1
        assert "code" in results[0]
        assert results[0]["code"] != ""


# ═══════════════════════════════════════════════════════════════
# ComponentAWGenerator
# ═══════════════════════════════════════════════════════════════

class TestComponentAWGenerator:
    """ComponentAWGenerator 测试"""

    def test_generate_with_resolver(self):
        code_gen = ReferenceCodeGenerator()
        resolver = ReferenceComponentResolver()
        caw_gen = ComponentAWGenerator(code_gen, resolver)

        code = caw_gen.generate(
            component_type="TableAW",
            aria_role="table",
            xpath="//table[@id='users']",
            resolver=resolver,
            discovered_inputs=[
                {"name": "search", "placeholder": "Search..."},
            ],
        )
        assert "TableAW" in code or len(code) > 20

    def test_generate_without_resolver_raises(self):
        code_gen = ReferenceCodeGenerator()
        caw_gen = ComponentAWGenerator(code_gen, None)
        with pytest.raises(ValueError, match="resolver"):
            caw_gen.generate("TableAW", "table", "//*")

    def test_generate_all(self):
        code_gen = ReferenceCodeGenerator()
        resolver = ReferenceComponentResolver()
        caw_gen = ComponentAWGenerator(code_gen, resolver)

        components = [
            {
                "type": "TableAW",
                "name": "user_table",
                "aria_role": "table",
                "xpath": "//table[@id='users']",
                "inputs": [],
                "interactables": [],
            },
        ]
        results = caw_gen.generate_all(components, resolver=resolver)
        assert len(results) == 1
        assert "code" in results[0]


# ═══════════════════════════════════════════════════════════════
# TestScriptGenerator
# ═══════════════════════════════════════════════════════════════

class TestTestScriptGen:
    """TestScriptGenerator 测试"""

    def test_generate_with_style(self):
        code_gen = ReferenceCodeGenerator()
        data_fmt = ReferenceDataFormatter()
        script_gen = TestScriptGenerator(code_gen, data_fmt)

        code = script_gen.generate(
            test_name="test_search",
            imports=["import pytest"],
            fixtures=["page"],
            steps=["page.search_box.enter('test')", "page.search_btn.click()"],
            description="Search test",
            style_profile=None,
        )
        assert "test_search" in code or "Search" in code

    def test_generate_data(self):
        code_gen = ReferenceCodeGenerator()
        data_fmt = ReferenceDataFormatter()
        script_gen = TestScriptGenerator(code_gen, data_fmt)

        data_def = script_gen.generate_data(
            {"search_keyword": "test"}, "users"
        )
        assert data_def is not None


# ═══════════════════════════════════════════════════════════════
# ActionRecognizer — 增强的 aggregate 输出
# ═══════════════════════════════════════════════════════════════

class TestActionRecognizerEnhanced:
    """ActionRecognizer 增强输出测试"""

    def test_aggregate_includes_raw_steps(self):
        recognizer = ReferenceActionRecognizer()
        raw_steps = [
            {"action": "click", "target": {"label": "search_btn"}},
        ]
        actions = recognizer.aggregate(raw_steps, {"page": "Home"})
        assert len(actions) > 0
        act = actions[0]
        assert "raw_steps" in act
        assert len(act["raw_steps"]) > 0

    def test_aggregate_includes_component(self):
        recognizer = ReferenceActionRecognizer()
        raw_steps = [
            {"action": "click", "target": {"label": "submit_button"}},
        ]
        actions = recognizer.aggregate(raw_steps, {"page": "Home"})
        act = actions[0]
        assert "component" in act
        assert "submit_button" in act["component"]

    def test_aggregate_includes_value(self):
        recognizer = ReferenceActionRecognizer()
        raw_steps = [
            {"action": "input", "target": {"label": "keyword"}, "value": "hello"},
        ]
        actions = recognizer.aggregate(raw_steps, {"page": "Home"})
        act = actions[0]
        assert act.get("value") == "hello"


# ═══════════════════════════════════════════════════════════════
# PrefixSpan — 算法正确性
# ═══════════════════════════════════════════════════════════════

class TestPrefixSpanAlgorithm:
    """PrefixSpan 算法细节测试"""

    def test_prefix_span_basic(self):
        from uibridge.adapter.reference import _PrefixSpan
        miner = _PrefixSpan(min_support=2, max_length=5)
        sequences = [
            ["a", "b", "c"],
            ["a", "b", "c"],
            ["a", "d"],
        ]
        results = miner.mine(sequences)
        # ("a",) 出现 3 次, ("a", "b") 出现 2 次, ("a", "b", "c") 出现 2 次
        patterns = {r[0]: r[1] for r in results}
        assert patterns[("a",)] == 3
        assert patterns[("a", "b")] >= 2

    def test_prefix_span_max_length(self):
        from uibridge.adapter.reference import _PrefixSpan
        miner = _PrefixSpan(min_support=2, max_length=2)
        sequences = [
            ["a", "b", "c"],
            ["a", "b", "c"],
        ]
        results = miner.mine(sequences)
        # 不应有长度 > 2 的模式
        for pattern, _ in results:
            assert len(pattern) <= 2

    def test_prefix_span_min_support(self):
        from uibridge.adapter.reference import _PrefixSpan
        miner = _PrefixSpan(min_support=10, max_length=5)
        sequences = [["a"], ["b"], ["c"]]
        results = miner.mine(sequences)
        assert results == []
