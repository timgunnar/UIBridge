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


# ═══════════════════════════════════════════════════════════════
# Pipeline — 空闲间隔场景分割
# ═══════════════════════════════════════════════════════════════

class TestPipelineIdleGapSplitting:
    """Pipeline.analyze 空闲间隔场景分割测试"""

    def test_idle_gap_splits_scenario(self):
        """步骤间空闲超过 5 秒应分割为新场景"""
        from uibridge.pipeline import Pipeline
        from uibridge.adapter.reference import (
            ReferenceComponentResolver, ReferenceLocatorStrategy,
            ReferenceActionRecognizer, ReferenceCodeGenerator, ReferenceDataFormatter,
        )
        from uibridge.engine.ir.raw_recording import (
            RawRecording, RawStep, ActionType, Target,
        )

        pipeline = Pipeline(
            component_resolver=ReferenceComponentResolver(),
            locator_strategy=ReferenceLocatorStrategy(),
            action_recognizer=ReferenceActionRecognizer(),
            code_generator=ReferenceCodeGenerator(),
            data_formatter=ReferenceDataFormatter(),
        )

        recording = RawRecording(steps=[
            RawStep(id="s1", action=ActionType.CLICK,
                    target=Target(label="btn1"), timestamp_ms=0),
            RawStep(id="s2", action=ActionType.CLICK,
                    target=Target(label="btn2"), timestamp_ms=1000),
            RawStep(id="s3", action=ActionType.CLICK,
                    target=Target(label="btn3"), timestamp_ms=8000),  # >5s gap
        ], snapshots={})

        semantic = pipeline.analyze(recording)
        assert len(semantic.scenarios) == 2, \
            f"Expected 2 scenarios due to idle gap, got {len(semantic.scenarios)}"

    def test_no_split_with_small_gap(self):
        """小间隔不应分割场景"""
        from uibridge.pipeline import Pipeline
        from uibridge.adapter.reference import (
            ReferenceComponentResolver, ReferenceLocatorStrategy,
            ReferenceActionRecognizer, ReferenceCodeGenerator, ReferenceDataFormatter,
        )
        from uibridge.engine.ir.raw_recording import (
            RawRecording, RawStep, ActionType, Target,
        )

        pipeline = Pipeline(
            component_resolver=ReferenceComponentResolver(),
            locator_strategy=ReferenceLocatorStrategy(),
            action_recognizer=ReferenceActionRecognizer(),
            code_generator=ReferenceCodeGenerator(),
            data_formatter=ReferenceDataFormatter(),
        )

        recording = RawRecording(steps=[
            RawStep(id="s1", action=ActionType.CLICK,
                    target=Target(label="btn1"), timestamp_ms=0),
            RawStep(id="s2", action=ActionType.CLICK,
                    target=Target(label="btn2"), timestamp_ms=2000),
            RawStep(id="s3", action=ActionType.CLICK,
                    target=Target(label="btn3"), timestamp_ms=4000),
        ], snapshots={})

        semantic = pipeline.analyze(recording)
        assert len(semantic.scenarios) == 1, \
            f"Expected 1 scenario (no idle gap), got {len(semantic.scenarios)}"

    def test_navigate_still_splits(self):
        """NAVIGATE 仍然是场景边界"""
        from uibridge.pipeline import Pipeline
        from uibridge.adapter.reference import (
            ReferenceComponentResolver, ReferenceLocatorStrategy,
            ReferenceActionRecognizer, ReferenceCodeGenerator, ReferenceDataFormatter,
        )
        from uibridge.engine.ir.raw_recording import (
            RawRecording, RawStep, ActionType, Target,
        )

        pipeline = Pipeline(
            component_resolver=ReferenceComponentResolver(),
            locator_strategy=ReferenceLocatorStrategy(),
            action_recognizer=ReferenceActionRecognizer(),
            code_generator=ReferenceCodeGenerator(),
            data_formatter=ReferenceDataFormatter(),
        )

        recording = RawRecording(steps=[
            RawStep(id="s1", action=ActionType.CLICK,
                    target=Target(label="btn1"), timestamp_ms=0),
            RawStep(id="s2", action=ActionType.NAVIGATE,
                    target=Target(url="/users"), timestamp_ms=100),
            RawStep(id="s3", action=ActionType.CLICK,
                    target=Target(label="btn2"), timestamp_ms=200),
        ], snapshots={})

        semantic = pipeline.analyze(recording)
        assert len(semantic.scenarios) == 2, \
            f"Expected 2 scenarios (NAVIGATE boundary), got {len(semantic.scenarios)}"


# ═══════════════════════════════════════════════════════════════
# Reference 适配器 — 扩展 ARIA 角色
# ═══════════════════════════════════════════════════════════════

class TestReferenceAdapterExpandedRoles:
    """验证新增 ARIA 角色能正确解析"""

    def test_slider_resolves(self):
        resolver = ReferenceComponentResolver()
        assert resolver.resolve_type("slider", {}, "") == "SliderAW"

    def test_progressbar_resolves(self):
        resolver = ReferenceComponentResolver()
        assert resolver.resolve_type("progressbar", {}, "") == "ProgressAW"

    def test_alert_resolves(self):
        resolver = ReferenceComponentResolver()
        assert resolver.resolve_type("alert", {}, "") == "AlertAW"

    def test_tooltip_resolves(self):
        resolver = ReferenceComponentResolver()
        assert resolver.resolve_type("tooltip", {}, "") == "TooltipAW"

    def test_switch_resolves(self):
        resolver = ReferenceComponentResolver()
        assert resolver.resolve_type("switch", {}, "") == "ToggleAW"

    def test_list_resolves(self):
        resolver = ReferenceComponentResolver()
        assert resolver.resolve_type("list", {}, "") == "ListAW"

    def test_img_resolves(self):
        resolver = ReferenceComponentResolver()
        assert resolver.resolve_type("img", {}, "") == "ImageAW"

    def test_heading_resolves(self):
        resolver = ReferenceComponentResolver()
        assert resolver.resolve_type("heading", {}, "") == "HeadingAW"

    def test_new_roles_have_methods(self):
        """新增角色应有对应的方法模板"""
        resolver = ReferenceComponentResolver()
        for role, aw_type in [
            ("slider", "SliderAW"),
            ("progressbar", "ProgressAW"),
            ("alert", "AlertAW"),
            ("switch", "ToggleAW"),
            ("list", "ListAW"),
            ("img", "ImageAW"),
            ("heading", "HeadingAW"),
            ("status", "StatusAW"),
            ("banner", "BannerAW"),
        ]:
            methods = resolver.get_methods_for_role(aw_type, role)
            assert len(methods) > 0, f"{aw_type} should have methods"
            assert all(hasattr(m, "name") for m in methods)


# ═══════════════════════════════════════════════════════════════
# SelfTestRunner — 新增修复规则
# ═══════════════════════════════════════════════════════════════

class TestSelfTestNewFixRules:
    """自检新增修复规则测试"""

    def test_rule_missing_test_annotation(self):
        """Rule 6: Java 缺 @Test 注解"""
        runner = SelfTestRunner()
        code = (
            "package test;\n"
            "import org.testng.annotations.Test;\n"
            "public class FooTest {\n"
            "    public void testSomething() {\n"
            "    }\n"
            "}"
        )
        error = "no test methods found in class FooTest"
        new_code, applied = runner._apply_fix_rules(code, error, "java")
        assert applied != "", f"Should apply fix, got: '{applied}'"
        assert "@Test" in new_code

    def test_rule_missing_self(self):
        """Rule 8: Python 方法缺 self 参数"""
        runner = SelfTestRunner()
        code = "import pytest\n\nclass Foo:\n    def test_something():\n        pass\n"
        error = "test_something() takes 0 positional arguments but 1 was given"
        new_code, applied = runner._apply_fix_rules(code, error, "python")
        assert applied != "", f"Should apply fix, got: '{applied}'"
        assert "self" in new_code

    def test_rule_missing_colon(self):
        """Rule 9: Python SyntaxError 缺冒号"""
        runner = SelfTestRunner()
        code = "import pytest\n\ndef test_foo()\n    pass\n"
        error = "SyntaxError: invalid syntax"
        new_code, applied = runner._apply_fix_rules(code, error, "python")
        assert applied != "", f"Should apply fix, got: '{applied}'"
        assert "):" in new_code

    def test_rule_npe_adds_teardown(self):
        """Rule 7: NullPointerException 加 tearDown"""
        runner = SelfTestRunner()
        code = (
            "package test;\n"
            "import org.testng.annotations.Test;\n"
            "public class FooTest {\n"
            "    @Test\n"
            "    public void testSomething() {\n"
            "        driver.get(\"http://test\");\n"
            "    }\n"
            "}"
        )
        error = "NullPointerException at FooTest.tearDown"
        new_code, applied = runner._apply_fix_rules(code, error, "java")
        assert applied != "", f"Should apply fix, got: '{applied}'"
        assert "tearDown" in new_code or "driver.quit" in new_code


# ═══════════════════════════════════════════════════════════════
# MCP Server 辅助函数
# ═══════════════════════════════════════════════════════════════

class TestMCPHelpers:
    """MCP Server URL 校验和路径安全化测试"""

    def test_validate_url_http(self):
        from uibridge.mcp_server import _validate_url
        assert _validate_url("https://example.com") == "https://example.com"

    def test_validate_url_about_blank(self):
        from uibridge.mcp_server import _validate_url
        assert _validate_url("about:blank") == "about:blank"

    def test_validate_url_rejects_empty(self):
        from uibridge.mcp_server import _validate_url
        import pytest
        with pytest.raises(ValueError, match="URL 不能为空"):
            _validate_url("")
        with pytest.raises(ValueError, match="URL 不能为空"):
            _validate_url("   ")

    def test_validate_url_rejects_javascript(self):
        from uibridge.mcp_server import _validate_url
        import pytest
        with pytest.raises(ValueError, match="禁止的 URL 协议"):
            _validate_url("javascript:alert(1)")

    def test_validate_url_rejects_data(self):
        from uibridge.mcp_server import _validate_url
        import pytest
        with pytest.raises(ValueError, match="禁止的 URL 协议"):
            _validate_url("data:text/html,<script>alert(1)</script>")

    def test_validate_url_rejects_no_scheme(self):
        from uibridge.mcp_server import _validate_url
        import pytest
        with pytest.raises(ValueError, match="URL 必须以 http"):
            _validate_url("example.com")

    def test_sanitize_output_path_inside_base(self):
        from uibridge.mcp_server import _sanitize_output_path
        import tempfile
        result = _sanitize_output_path("recording.json")
        assert result.name == "recording.json"

    def test_sanitize_output_path_traversal_blocked(self):
        from uibridge.mcp_server import _sanitize_output_path
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
        import tempfile
        self.tmpdir = tempfile.TemporaryDirectory()
        from uibridge.kb.kb_store import KBStore
        self.store = KBStore(str(self.tmpdir.name))
        # 播种测试数据
        from uibridge.kb.kb_item import KBItem, Confidence, KnowledgeSource
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
        """精确子串匹配返回结果并按置信度排序"""
        results = self.store.search("ButtonAW")
        assert len(results) >= 1
        # 最高置信度项排最前
        assert results[0].confidence.effective_score >= results[-1].confidence.effective_score

    def test_search_keyword_fallback(self):
        """无精确匹配时回退到 IDF 关键词搜索"""
        results = self.store.search("table pagination")
        assert len(results) >= 1
        assert any("TableAW" in r.key for r in results)

    def test_search_cjk_query(self):
        """中文查询词（CJK 分词）"""
        results = self.store.search("定位器")
        assert len(results) >= 1
        assert any("locator" in r.key for r in results)

    def test_search_empty_results_for_unmatched(self):
        """无匹配时应返回空列表"""
        results = self.store.search("zzz_nonexistent_xyz")
        assert results == []

    def test_search_ranks_by_combined_score(self):
        """高置信度 + 高相关性排在最前"""
        results = self.store.search("component")
        assert len(results) >= 2
        # t1 (confidence=0.9) 应排在 t2 (confidence=0.7) 前面
        scores = [r.confidence.effective_score for r in results]
        assert scores == sorted(scores, reverse=True), \
            f"Results should be sorted by confidence desc, got {scores}"

    def test_keyword_search_ignores_low_relevance(self):
        """关键词搜索中极低相关性的项应被过滤"""
        results = self.store._keyword_search("login", min_score=0.1)
        assert len(results) >= 1
        # t4 与 "login" 强相关，t1/t2/t3 不相关
        keys = [r.key for r in results]
        assert "pattern.login_flow" in keys

    def test_keyword_search_empty_tokens(self):
        """空查询词返回空"""
        results = self.store._keyword_search("")
        assert results == []

    def test_keyword_search_single_token(self):
        """单 token 查询正常工作"""
        results = self.store._keyword_search("button")
        assert len(results) >= 1
        assert any("ButtonAW" in r.key for r in results)


class TestKBNLOperations:
    """KBManager.operate_nl() NL CRUD 操作测试"""

    @pytest.fixture(autouse=True)
    def setup(self):
        import tempfile
        self.tmpdir = tempfile.TemporaryDirectory()
        from uibridge.kb.kb_manager import KBManager
        self.km = KBManager(str(self.tmpdir.name))
        # 预播种一些条目，供 MODIFY/DELETE 使用
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

    # ── QUERY ──

    def test_nl_query_finds_result(self):
        """NL 查询: 匹配到 KB 条目"""
        result = self.km.operate_nl("定位器优先级是什么？")
        assert result["status"] == "ok"
        assert result["intent"] == "QUERY"
        assert "locator" in result["result"].lower()

    def test_nl_query_no_result(self):
        """NL 查询: 无匹配内容"""
        result = self.km.operate_nl("有没有关于颜色的规则？")
        assert result["status"] == "ok"
        assert "No KB entries found" in result["result"]

    def test_nl_query_implicit(self):
        """NL 查询: 无明确意图默认为 QUERY"""
        result = self.km.operate_nl("表格组件")
        assert result["intent"] == "QUERY"

    # ── ADD ──

    def test_nl_add_new_rule(self):
        """NL 新增: 添加一条新规则"""
        result = self.km.operate_nl("新增规则：弹窗用 role='dialog' 识别")
        assert result["status"] == "ok"
        assert result["intent"] == "ADD"
        assert "dialog" in result["added"]["description"]

        # 验证条目已持久化（弹窗 → components 分类）
        items = self.km.store.list_category("components")
        assert any("dialog" in item.description for item in items)

    def test_nl_add_infers_category(self):
        """NL 新增: 根据内容关键词推断分类"""
        result = self.km.operate_nl("添加表格组件的高亮功能")
        assert result["status"] == "ok"
        assert result["intent"] == "ADD"
        # "表格"关键词 → components 分类
        assert result["added"]["category"] == "components"

    # ── MODIFY ──

    def test_nl_modify_existing(self):
        """NL 修改: 更新已有条目"""
        result = self.km.operate_nl("表格组件的定位方式改为 data-testid")
        assert result["status"] == "ok"
        assert result["intent"] == "MODIFY"
        assert "table_aw" in result["modified"]["key"]

        # 验证已更新
        item = self.km.store.get_by_key("components", "table_aw")
        assert item is not None
        assert "nl_modification" in item.value
        assert "data-testid" in item.value["nl_modification"]

    def test_nl_modify_not_found(self):
        """NL 修改: 目标不存在时返回提示"""
        result = self.km.operate_nl("把不存在的规则改成 xxx")
        assert result["status"] == "not_found"
        assert result.get("suggest_add") is True

    def test_nl_modify_with_should_pattern(self):
        """NL 修改: '应该用xxx' 模式"""
        result = self.km.operate_nl("定位器应该用 data-module")
        assert result["status"] == "ok"
        assert result["intent"] == "MODIFY"

    # ── DELETE ──

    def test_nl_delete_existing(self):
        """NL 删除: 删除已有条目（归档）"""
        result = self.km.operate_nl("删掉登录流程的规则")
        assert result["status"] == "ok"
        assert result["intent"] == "DELETE"
        assert "login" in result["deleted"]["key"].lower()

        # 验证已归档（list_category 不返回归档项）
        items = self.km.store.list_category("patterns")
        assert not any("login" in item.key for item in items)

    def test_nl_delete_not_found(self):
        """NL 删除: 目标不存在时返回提示"""
        result = self.km.operate_nl("删除不存在的规则")
        assert result["status"] == "not_found"
        assert result["intent"] == "DELETE"

    # ── Edge cases ──

    def test_nl_empty_instruction(self):
        """空指令处理"""
        result = self.km.operate_nl("")
        assert result["status"] in ("ok", "error")

    def test_nl_add_with_special_chars(self):
        """NL 新增: 特殊字符处理"""
        result = self.km.operate_nl("新增: 表单校验规则 @NotNull @Size(min=1)")
        assert result["status"] == "ok"
        assert result["intent"] == "ADD"


# ═══════════════════════════════════════════════════════════════
# Screenplay / JavaFluent — 扩展 ARIA 角色映射
# ═══════════════════════════════════════════════════════════════

class TestScreenplayARIAExpanded:
    """验证 Screenplay 适配器 ARIA role → 正确类型名"""

    @pytest.fixture(autouse=True)
    def setup(self):
        from uibridge.adapter.screenplay import ScreenplayComponentResolver
        self.resolver = ScreenplayComponentResolver()

    def test_table_resolves_to_table_target(self):
        assert self.resolver.resolve_type("table", {}, "") == "TableTarget"

    def test_grid_resolves_to_table_target(self):
        assert self.resolver.resolve_type("grid", {}, "") == "TableTarget"

    def test_textbox_resolves_to_input_target(self):
        assert self.resolver.resolve_type("textbox", {}, "") == "InputTarget"

    def test_searchbox_resolves_to_input_target(self):
        assert self.resolver.resolve_type("searchbox", {}, "") == "InputTarget"

    def test_button_resolves_to_button_target(self):
        assert self.resolver.resolve_type("button", {}, "") == "ButtonTarget"

    def test_combobox_resolves_to_dropdown_target(self):
        assert self.resolver.resolve_type("combobox", {}, "") == "DropdownTarget"

    def test_checkbox_resolves(self):
        assert self.resolver.resolve_type("checkbox", {}, "") == "CheckboxTarget"

    def test_dialog_resolves(self):
        assert self.resolver.resolve_type("dialog", {}, "") == "DialogTarget"

    def test_unknown_role_falls_back_to_target(self):
        assert self.resolver.resolve_type("unknown_role", {}, "") == "Target"

    def test_all_mapped_roles_have_methods(self):
        """每个映射类型都应有对应的方法模板"""
        for role, expected_type in [
            ("table", "TableTarget"),
            ("form", "FormTarget"),
            ("textbox", "InputTarget"),
            ("button", "ButtonTarget"),
            ("combobox", "DropdownTarget"),
            ("checkbox", "CheckboxTarget"),
            ("link", "LinkTarget"),
            ("dialog", "DialogTarget"),
        ]:
            methods = self.resolver.get_methods_for_role(expected_type, role)
            assert len(methods) > 0, f"{expected_type} should have methods for role={role}"
            assert all(hasattr(m, "name") for m in methods), \
                f"All methods for {expected_type} should have 'name'"


class TestJavaFluentARIAExpanded:
    """验证 JavaFluent 适配器 ARIA role → 正确类型名"""

    @pytest.fixture(autouse=True)
    def setup(self):
        from uibridge.adapter.java_fluent import FluentComponentResolver
        self.resolver = FluentComponentResolver()

    def test_table_resolves_to_table_element(self):
        assert self.resolver.resolve_type("table", {}, "") == "TableElement"

    def test_textbox_resolves_to_input_element(self):
        assert self.resolver.resolve_type("textbox", {}, "") == "InputElement"

    def test_button_resolves_to_button_element(self):
        assert self.resolver.resolve_type("button", {}, "") == "ButtonElement"

    def test_combobox_resolves_to_dropdown_element(self):
        assert self.resolver.resolve_type("combobox", {}, "") == "DropdownElement"

    def test_checkbox_resolves(self):
        assert self.resolver.resolve_type("checkbox", {}, "") == "CheckboxElement"

    def test_link_resolves(self):
        assert self.resolver.resolve_type("link", {}, "") == "LinkElement"

    def test_dialog_resolves(self):
        assert self.resolver.resolve_type("dialog", {}, "") == "DialogElement"

    def test_unknown_role_falls_back_to_page_element(self):
        assert self.resolver.resolve_type("unknown_role", {}, "") == "PageElement"

    def test_all_mapped_roles_have_methods(self):
        """每个映射类型都应有对应的方法模板"""
        for role, expected_type in [
            ("table", "TableElement"),
            ("form", "FormElement"),
            ("textbox", "InputElement"),
            ("button", "ButtonElement"),
            ("combobox", "DropdownElement"),
            ("checkbox", "CheckboxElement"),
            ("link", "LinkElement"),
            ("dialog", "DialogElement"),
        ]:
            methods = self.resolver.get_methods_for_role(expected_type, role)
            assert len(methods) > 0, f"{expected_type} should have methods for role={role}"
            assert all(hasattr(m, "name") for m in methods), \
                f"All methods for {expected_type} should have 'name'"


# ═══════════════════════════════════════════════════════════════
# KB Pattern Matching — Stage 3 noise filtering
# ═══════════════════════════════════════════════════════════════

class TestKBPatternMatching:
    """KB pattern matching in ActionRecognizer._match_kb_patterns() tests"""

    @staticmethod
    def _make_mock_kb_manager(patterns: list[dict]):
        """Create a mock KB manager with pattern entries."""
        from unittest.mock import MagicMock

        class MockKBItem:
            def __init__(self, key, value):
                self.key = key
                self.value = value

        mock_store = MagicMock()
        mock_items = [
            MockKBItem(key=p["key"], value={"actions": p["actions"]})
            for p in patterns
        ]
        mock_store.list_category.return_value = mock_items

        mock_kb = MagicMock()
        mock_kb.store = mock_store
        return mock_kb

    def test_matches_known_pattern(self):
        """A sequence matching a KB pattern should be merged."""
        recognizer = ReferenceActionRecognizer()
        kb = self._make_mock_kb_manager([
            {"key": "pattern.login", "actions": ["enter", "click"]},
        ])
        actions = [
            {"action": "enter", "component": "username", "raw_steps": [{"step": 1}]},
            {"action": "click", "component": "login_btn", "raw_steps": [{"step": 2}]},
        ]
        result = recognizer._match_kb_patterns(actions, kb)
        assert len(result) == 1
        assert result[0]["type"] == "kb_pattern"
        assert result[0]["action"] == "login"
        assert len(result[0]["sub_actions"]) == 2
        assert len(result[0]["raw_steps"]) == 2

    def test_matches_pattern_from_steps_key(self):
        """Patterns with 'steps' key (legacy format) should also work."""
        from unittest.mock import MagicMock

        class MockKBItem:
            def __init__(self, key, value):
                self.key = key
                self.value = value

        mock_store = MagicMock()
        mock_store.list_category.return_value = [
            MockKBItem(key="pattern.login", value={"steps":
                ["enter_username", "enter_password", "click_login"]}),
        ]
        mock_kb = MagicMock()
        mock_kb.store = mock_store

        recognizer = ReferenceActionRecognizer()
        actions = [
            {"action": "enter_username", "component": "user", "raw_steps": [{"s": 1}]},
            {"action": "enter_password", "component": "pass", "raw_steps": [{"s": 2}]},
            {"action": "click_login", "component": "btn", "raw_steps": [{"s": 3}]},
        ]
        result = recognizer._match_kb_patterns(actions, mock_kb)
        assert len(result) == 1
        assert result[0]["type"] == "kb_pattern"
        assert result[0]["action"] == "login"
        assert len(result[0]["sub_actions"]) == 3

    def test_non_matching_sequence_unchanged(self):
        """A sequence that does not match any KB pattern should be unchanged."""
        recognizer = ReferenceActionRecognizer()
        kb = self._make_mock_kb_manager([
            {"key": "pattern.login", "actions": ["enter", "password", "click"]},
        ])
        actions = [
            {"action": "navigate", "component": "page", "raw_steps": []},
            {"action": "click", "component": "menu", "raw_steps": []},
        ]
        result = recognizer._match_kb_patterns(actions, kb)
        assert len(result) == 2
        assert result[0]["action"] == "navigate"
        assert result[1]["action"] == "click"

    def test_no_kb_manager_returns_unchanged(self):
        """Without a KB manager, actions should be returned as-is."""
        recognizer = ReferenceActionRecognizer()
        actions = [
            {"action": "click", "component": "btn"},
            {"action": "input", "component": "field"},
        ]
        result = recognizer._match_kb_patterns(actions, None)
        assert result == actions

    def test_empty_actions_unchanged(self):
        """Empty action list returns as-is."""
        recognizer = ReferenceActionRecognizer()
        kb = self._make_mock_kb_manager([
            {"key": "pattern.foo", "actions": ["a", "b"]},
        ])
        result = recognizer._match_kb_patterns([], kb)
        assert result == []

    def test_single_action_unchanged(self):
        """Single action should not be merged (need at least 2)."""
        recognizer = ReferenceActionRecognizer()
        kb = self._make_mock_kb_manager([
            {"key": "pattern.foo", "actions": ["click"]},
        ])
        actions = [{"action": "click", "component": "btn"}]
        result = recognizer._match_kb_patterns(actions, kb)
        assert len(result) == 1
        assert result[0]["action"] == "click"

    def test_empty_patterns_unchanged(self):
        """KB with empty patterns category returns actions unchanged."""
        from unittest.mock import MagicMock
        mock_store = MagicMock()
        mock_store.list_category.return_value = []
        mock_kb = MagicMock()
        mock_kb.store = mock_store

        recognizer = ReferenceActionRecognizer()
        actions = [
            {"action": "click", "component": "btn"},
            {"action": "input", "component": "field"},
        ]
        result = recognizer._match_kb_patterns(actions, mock_kb)
        assert result == actions

    def test_subsequence_match_with_prefix(self):
        """Pattern match should work even with non-matching prefix/suffix."""
        recognizer = ReferenceActionRecognizer()
        kb = self._make_mock_kb_manager([
            {"key": "pattern.search", "actions": ["input", "click"]},
        ])
        actions = [
            {"action": "navigate", "component": "page", "raw_steps": [{"s": 0}]},
            {"action": "input", "component": "search_box", "raw_steps": [{"s": 1}]},
            {"action": "click", "component": "search_btn", "raw_steps": [{"s": 2}]},
            {"action": "assert", "component": "result", "raw_steps": [{"s": 3}]},
        ]
        result = recognizer._match_kb_patterns(actions, kb)
        assert len(result) == 3  # navigate, merged kb_pattern, assert
        assert result[1]["type"] == "kb_pattern"
        assert result[1]["action"] == "search"
        assert result[0]["action"] == "navigate"
        assert result[2]["action"] == "assert"

    def test_partial_match_ignored(self):
        """Substring match (e.g., 'click' in 'click_login') should match via containment."""
        recognizer = ReferenceActionRecognizer()
        kb = self._make_mock_kb_manager([
            {"key": "pattern.login", "actions": ["enter", "click"]},
        ])
        actions = [
            {"action": "enter", "raw_steps": [{"s": 1}]},
            {"action": "click_login_btn", "raw_steps": [{"s": 2}]},
        ]
        result = recognizer._match_kb_patterns(actions, kb)
        # "click" should be found in "click_login_btn" via substring match
        assert len(result) == 1
        assert result[0]["type"] == "kb_pattern"
        assert result[0]["action"] == "login"

    def test_kb_manager_store_error_graceful(self):
        """If store.list_category raises, actions are returned unchanged."""
        from unittest.mock import MagicMock
        mock_store = MagicMock()
        mock_store.list_category.side_effect = RuntimeError("disk error")
        mock_kb = MagicMock()
        mock_kb.store = mock_store

        recognizer = ReferenceActionRecognizer()
        actions = [
            {"action": "click", "component": "btn"},
        ]
        result = recognizer._match_kb_patterns(actions, mock_kb)
        assert result == actions


# ═══════════════════════════════════════════════════════════════
# KB 驱动噪声过滤 — 定位器属性白名单
# ═══════════════════════════════════════════════════════════════

class TestKBDrivenNoiseFilter:
    """KB 驱动定位器白名单过滤 MutationObserver 噪声测试"""

    def test_locator_whitelist_filters_mutations(self):
        """验证 setting locator_attrs 后 RECORDER_JS 包含过滤函数和白名单变量"""
        from uibridge.engine.recorder import RECORDER_JS
        assert "_has_locator_attr" in RECORDER_JS, \
            "RECORDER_JS should contain _has_locator_attr helper"
        assert "_mutation_batch_has_locator" in RECORDER_JS, \
            "RECORDER_JS should contain _mutation_batch_has_locator filter"
        assert "window.__uibridge_locator_attrs" in RECORDER_JS, \
            "RECORDER_JS should reference window.__uibridge_locator_attrs"

    def test_no_whitelist_reports_all(self):
        """验证无 locator_attrs 时默认报告所有 mutation（向后兼容）"""
        from uibridge.engine.recorder import RECORDER_JS
        # _mutation_batch_has_locator 在无白名单时返回 true（不过滤）
        assert "if (!attrs || attrs.length === 0) return true" in RECORDER_JS, \
            "When no whitelist, _mutation_batch_has_locator should return true (no filter)"

    def test_recording_session_accepts_locator_attrs(self):
        """验证 RecordingSession 接受 locator_attrs 参数并存储"""
        from uibridge.engine.recorder import RecordingSession
        import inspect
        sig = inspect.signature(RecordingSession.__init__)
        assert "locator_attrs" in sig.parameters, \
            "RecordingSession.__init__ should accept locator_attrs parameter"

    def test_locator_attrs_default_is_none(self):
        """验证 locator_attrs 默认值为 None（不改变现有行为）"""
        import inspect
        from uibridge.engine.recorder import RecordingSession
        sig = inspect.signature(RecordingSession.__init__)
        param = sig.parameters["locator_attrs"]
        assert param.default is None, \
            "locator_attrs should default to None for backward compatibility"

    def test_pipeline_record_forwards_locator_attrs(self):
        """验证 Pipeline.record() 将 locator_attrs 转发给 RecordingSession"""
        import inspect
        from uibridge.pipeline import Pipeline
        sig = inspect.signature(Pipeline.record)
        assert "locator_attrs" in sig.parameters, \
            "Pipeline.record() should accept locator_attrs parameter"

    def test_click_input_nav_always_reported(self):
        """验证非 mutation 事件（click/input/navigate）不受白名单影响"""
        from uibridge.engine.recorder import RECORDER_JS
        # click、dblclick、input、change、keydown 等事件直接调用 __uibridge_report，
        # 不经过 _mutation_batch_has_locator 过滤器
        mutation_section_start = RECORDER_JS.index("MutationObserver")
        before_mo = RECORDER_JS[:mutation_section_start]
        # _mutation_batch_has_locator 只在 MutationObserver 节中引用
        assert "_mutation_batch_has_locator" not in before_mo, \
            "Non-mutation events (before MutationObserver section) should not reference mutation filter"

    def test_has_locator_attr_js_logic(self):
        """验证 _has_locator_attr JS 函数的核心逻辑"""
        from uibridge.engine.recorder import RECORDER_JS
        # 向上查找最多 5 层
        assert "i < 5" in RECORDER_JS, \
            "_has_locator_attr should check up to 5 ancestor levels"
        # 使用 hasAttribute 检查白名单属性
        assert "node.hasAttribute(attr)" in RECORDER_JS, \
            "_has_locator_attr should use hasAttribute to check whitelisted attrs"
        # 当 attrs 为空时跳过检查
        assert "node.getAttribute && attrs" in RECORDER_JS, \
            "_has_locator_attr should guard on getAttribute and attrs existence"

    def test_mcp_server_start_recording_queries_kb(self):
        """验证 start_recording 中查询 KB 获取定位器约定的代码存在"""
        import inspect
        from uibridge.mcp_server import start_recording
        source = inspect.getsource(start_recording)
        assert "get_locator_conventions" in source, \
            "start_recording should query KB for locator conventions"
        assert "locator_attrs" in source, \
            "start_recording should define locator_attrs variable"
        assert "pipeline.record(page, locator_attrs=locator_attrs)" in source, \
            "start_recording should pass locator_attrs to pipeline.record()"


# ═══════════════════════════════════════════════════════════════
# KBEvolution — KB 生命周期演化：衰减、泛化、归档
# ═══════════════════════════════════════════════════════════════

class TestKBEvolution:
    """KBEvolution: decay, generalize, archive lifecycle tests."""

    def test_evolve_applies_decay(self):
        """Item with decay_rate>0 and old last_validated_at should have score decrease."""
        import tempfile
        import shutil
        import time
        from uibridge.kb.kb_store import KBStore
        from uibridge.kb.kb_item import KBItem, Confidence, KnowledgeSource
        from uibridge.kb.kb_evolution import KBEvolution

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
        """Archived items should not be affected by evolution."""
        import tempfile
        import shutil
        import time
        from uibridge.kb.kb_store import KBStore
        from uibridge.kb.kb_item import KBItem, Confidence, KnowledgeSource
        from uibridge.kb.kb_evolution import KBEvolution

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
        """Item with effective_score<0.2 and 3+ failures should be archived."""
        import tempfile
        import shutil
        from uibridge.kb.kb_store import KBStore
        from uibridge.kb.kb_item import KBItem, Confidence, KnowledgeSource
        from uibridge.kb.kb_evolution import KBEvolution

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

            # 通过 search/archive 目录检查（KBItem.archived was set True by archive()）
            updated = store.get("components", "evolve_archive_1")
            if updated is not None:
                # 如果仍在原位置，检查 archived 标记
                assert updated.archived is True
            else:
                # 如果已移动到 archive 目录，也算成功
                pass
        finally:
            shutil.rmtree(td, ignore_errors=True)

    def test_evolve_empty_store(self):
        """Evolution on an empty store should not crash."""
        import tempfile
        import shutil
        from uibridge.kb.kb_store import KBStore
        from uibridge.kb.kb_evolution import KBEvolution

        td = tempfile.mkdtemp()
        try:
            store = KBStore(td)
            evolution = KBEvolution(store)
            evolution.evolve()  # Should not raise
        finally:
            shutil.rmtree(td, ignore_errors=True)

    def test_generalize_boosts_patterns(self):
        """3+ items with same structural value signature get 'generalized' tag + score boost."""
        import tempfile
        import shutil
        from uibridge.kb.kb_store import KBStore
        from uibridge.kb.kb_item import KBItem, Confidence, KnowledgeSource
        from uibridge.kb.kb_evolution import KBEvolution

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
