"""StyleLearner 测试 — learn(), learn_from_files(), _read_source(), 风格分析"""

import os
import sys
import tempfile
from pathlib import Path

import pytest

# Ensure uibridge is importable
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from uibridge.generator.style_learner import StyleLearner, StyleProfile


# ═══════════════════════════════════════════════════════════════
# Python 测试代码模板
# ═══════════════════════════════════════════════════════════════

PYTHON_TEST_SAMPLE = '''
"""测试示例 — TableAW 组件"""
import pytest
from project.aw import TableAW


class TestTableFiltering:
    """表格筛选功能测试"""

    @pytest.fixture
    def table_page(self):
        from pages.table_page import TablePage
        return TablePage()

    def test_filter_by_name(self, table_page):
        """按名称筛选"""
        table = TableAW(table_page.table_element)
        table.filter("name", "John")
        result = table.get_row_count()
        assert result > 0, "筛选后应有结果"

    def test_clear_filter(self, table_page):
        table = TableAW(table_page.table_element)
        table.clear_filter()
        assert table.get_row_count() > 0  # inline comment
'''

PYTHON_DIRECT_IMPORT_SAMPLE = '''
import unittest
import myapp


class TestMyApp(unittest.TestCase):

    def setUp(self):
        self.app = myapp.create_app()

    def test_addition(self):
        "测试加法"
        self.assertEqual(1 + 1, 2)

    def test_subtraction(self):
        self.assertTrue(2 - 1 == 1)
'''


# ═══════════════════════════════════════════════════════════════
# Java 测试代码模板
# ═══════════════════════════════════════════════════════════════

JAVA_TEST_SAMPLE = '''
package com.example.tests;

import org.testng.annotations.Test;
import org.testng.annotations.BeforeMethod;
import static org.testng.Assert.assertEquals;
import com.example.pages.TablePage;

public class TestTableFiltering extends BaseTest {

    private TablePage tablePage;

    @BeforeMethod
    public void setUp() {
        tablePage = new TablePage(driver);
    }

    @Test
    public void testFilterByName() {
        tablePage.filter("name", "John");
        int count = tablePage.getRowCount();
        assertEquals(count, 5, "筛选后行数应为5");
    }
}
'''


# ═══════════════════════════════════════════════════════════════
# _read_source
# ═══════════════════════════════════════════════════════════════

class TestReadSource:
    """_read_source — 源码读取与回退"""

    def test_read_existing_file(self, tmp_path):
        """读取已存在的 Python 文件"""
        test_file = tmp_path / "test_example.py"
        test_file.write_text(PYTHON_TEST_SAMPLE, encoding="utf-8")

        learner = StyleLearner()
        result = learner._read_source(str(test_file))
        assert result is not None
        assert "test_filter_by_name" in result

    def test_read_source_as_string(self):
        """路径不存在时将参数本身当作源码字符串"""
        learner = StyleLearner()
        result = learner._read_source(PYTHON_TEST_SAMPLE)
        assert result is not None
        assert "test_filter_by_name" in result

    def test_read_missing_file_returns_none(self):
        """不存在的文件且也不像源码时返回 None"""
        learner = StyleLearner()
        result = learner._read_source("/nonexistent/path/no_such_file.xyz")
        assert result is None

    def test_read_java_source_as_string(self):
        """Java 源码字符串识别"""
        learner = StyleLearner()
        result = learner._read_source(JAVA_TEST_SAMPLE)
        assert result is not None
        assert "TestTableFiltering" in result

    def test_read_binary_file(self, tmp_path):
        """二进制文件会报错（不是文件则回退到字符串检测）"""
        # 实际二进制文件读取 try/except 被 catch 了
        # 然后回退到字符串检测 — 二进制内容不含换行/class/package，应返回 None
        learner = StyleLearner()
        binary_data = bytes(range(256))
        result = learner._read_source(str(binary_data[:50]))
        assert result is None

    def test_empty_file(self, tmp_path):
        """空文件可读取"""
        test_file = tmp_path / "empty.py"
        test_file.write_text("", encoding="utf-8")

        learner = StyleLearner()
        result = learner._read_source(str(test_file))
        assert result == ""


# ═══════════════════════════════════════════════════════════════
# learn_from_files — Python
# ═══════════════════════════════════════════════════════════════

class TestLearnFromFilesPython:
    """learn_from_files Python 风格学习"""

    def test_single_python_file(self, tmp_path):
        """从单个 Python 文件学习"""
        test_file = tmp_path / "test_example.py"
        test_file.write_text(PYTHON_TEST_SAMPLE, encoding="utf-8")

        learner = StyleLearner()
        profile = learner.learn_from_files([str(test_file)])
        assert profile is not None
        assert profile.language == "python"
        assert profile.use_test_class is True
        # fixture_decorator: _most_common returns "" when all falsy, True when truthy
        assert profile.fixture_decorator, f"Expected truthy fixture_decorator, got {profile.fixture_decorator!r}"
        assert profile.test_method_prefix == "test_"

    def test_quote_style_double(self, tmp_path):
        """检测双引号风格"""
        test_file = tmp_path / "test_q.py"
        test_file.write_text('''x = "hello"; y = "world"; z = "again"\n''', encoding="utf-8")

        learner = StyleLearner()
        profile = learner.learn_from_files([str(test_file)])
        assert profile.quote_style == "double"

    def test_quote_style_single(self, tmp_path):
        """检测单引号风格"""
        test_file = tmp_path / "test_q.py"
        test_file.write_text("x = 'hello'; y = 'world'\n", encoding="utf-8")

        learner = StyleLearner()
        profile = learner.learn_from_files([str(test_file)])
        assert profile.quote_style == "single"

    def test_assert_style_pytest(self, tmp_path):
        """检测 pytest assert 风格"""
        test_file = tmp_path / "test_a.py"
        test_file.write_text("def test_x():\n    assert 1 == 1\n", encoding="utf-8")

        learner = StyleLearner()
        profile = learner.learn_from_files([str(test_file)])
        assert profile.assert_style == "pytest_assert"

    def test_detects_fixture_decorator(self, tmp_path):
        """检测 @pytest.fixture 装饰器"""
        test_file = tmp_path / "test_f.py"
        test_file.write_text('''import pytest\n@pytest.fixture\ndef my_fixture():\n    return {}\n''', encoding="utf-8")

        learner = StyleLearner()
        profile = learner.learn_from_files([str(test_file)])
        # @pytest.fixture detected as truthy (True from Counter)
        assert profile.fixture_decorator, f"Expected truthy fixture_decorator, got {profile.fixture_decorator!r}"

    def test_no_fixture_decorator(self, tmp_path):
        """无 fixture 装饰器时返回 False"""
        test_file = tmp_path / "test_nf.py"
        test_file.write_text("def test_x():\n    assert True\n", encoding="utf-8")

        learner = StyleLearner()
        profile = learner.learn_from_files([str(test_file)])
        # _most_common returns "" when all values are falsy (False gets filtered)
        assert not profile.fixture_decorator, f"Expected falsy fixture_decorator, got {profile.fixture_decorator!r}"

    def test_detects_docstrings(self, tmp_path):
        """检测文档字符串"""
        test_file = tmp_path / "test_d.py"
        test_file.write_text('def test_x():\n    """Docstring here."""\n    pass\n', encoding="utf-8")

        learner = StyleLearner()
        profile = learner.learn_from_files([str(test_file)])
        assert profile.use_docstrings is True

    def test_no_docstrings(self, tmp_path):
        """无文档字符串"""
        test_file = tmp_path / "test_nd.py"
        test_file.write_text("def test_x():\n    pass\n", encoding="utf-8")

        learner = StyleLearner()
        profile = learner.learn_from_files([str(test_file)])
        # _most_common returns "" when all values are falsy (False gets filtered)
        assert not profile.use_docstrings, f"Expected falsy use_docstrings, got {profile.use_docstrings!r}"


# ═══════════════════════════════════════════════════════════════
# learn_from_files — Java
# ═══════════════════════════════════════════════════════════════

class TestLearnFromFilesJava:
    """learn_from_files Java 风格学习"""

    def test_single_java_file(self, tmp_path):
        """从单个 Java 文件学习"""
        test_file = tmp_path / "TestTableFiltering.java"
        test_file.write_text(JAVA_TEST_SAMPLE, encoding="utf-8")

        learner = StyleLearner()
        profile = learner.learn_from_files([str(test_file)])
        assert profile is not None
        assert profile.language == "java"
        assert profile.use_test_class is True
        assert profile.test_annotation == "@Test"

    def test_java_assert_style_testng(self, tmp_path):
        """检测 TestNG 断言风格"""
        test_file = tmp_path / "TestNG.java"
        test_file.write_text('''import org.testng.Assert;
public class TestExample {
    @Test
    public void testX() {
        Assert.assertEquals(a, b);
        Assert.assertTrue(cond);
    }
}''', encoding="utf-8")

        learner = StyleLearner()
        profile = learner.learn_from_files([str(test_file)])
        assert profile.assert_style == "testng_assert"

    def test_java_package_detection(self, tmp_path):
        """检测 Java package 声明"""
        test_file = tmp_path / "TestPkg.java"
        test_file.write_text('''package com.mycompany.qa.tests;
public class TestPkg {
    @Test
    public void testSomething() {}
}''', encoding="utf-8")

        learner = StyleLearner()
        profile = learner.learn_from_files([str(test_file)])
        assert profile.package_name == "com.mycompany.qa.tests"

    def test_java_extends_detection(self, tmp_path):
        """检测 extends 声明"""
        test_file = tmp_path / "TestExt.java"
        test_file.write_text('''package tests;
public class TestExt extends BaseTest {
    @Test
    public void testX() {}
}''', encoding="utf-8")

        learner = StyleLearner()
        profile = learner.learn_from_files([str(test_file)])
        assert profile.extends_class == "BaseTest"

    def test_java_method_prefix_test(self, tmp_path):
        """检测 testXxx 方法前缀"""
        test_file = tmp_path / "TestPrefix.java"
        test_file.write_text('''public class TestPrefix {
    @Test
    public void testFilterByName() {}
    public void testClearFilter() {}
}''', encoding="utf-8")

        learner = StyleLearner()
        profile = learner.learn_from_files([str(test_file)])
        assert profile.test_method_prefix == "test"

    def test_java_class_prefix_test(self, tmp_path):
        """检测 TestXxx 类名前缀"""
        test_file = tmp_path / "TestPrefix.java"
        test_file.write_text('''public class TestPrefix {
    @Test
    public void testX() {}
}''', encoding="utf-8")

        learner = StyleLearner()
        profile = learner.learn_from_files([str(test_file)])
        assert profile.class_prefix == "Test"

    def test_java_variable_naming_camel(self, tmp_path):
        """检测 camelCase 变量命名"""
        test_file = tmp_path / "TestVar.java"
        test_file.write_text('''public class TestVar {
    @Test
    public void testX() {
        String userName = "john";
        int rowCount = 5;
    }
}''', encoding="utf-8")

        learner = StyleLearner()
        profile = learner.learn_from_files([str(test_file)])
        assert profile.variable_naming == "camelCase"


# ═══════════════════════════════════════════════════════════════
# learn() — 目录学习
# ═══════════════════════════════════════════════════════════════

class TestLearnDirectory:
    """learn() 目录扫描学习"""

    def test_learn_from_python_directory(self, tmp_path):
        """从包含 Python 测试的目录学习"""
        test_subdir = tmp_path / "tests"
        test_subdir.mkdir()
        (test_subdir / "test_one.py").write_text(PYTHON_TEST_SAMPLE, encoding="utf-8")
        (test_subdir / "test_two.py").write_text('''
def test_hello():
    """Say hello"""
    assert True
''', encoding="utf-8")

        learner = StyleLearner()
        profile = learner.learn(str(tmp_path))
        assert profile.language == "python"
        assert profile.test_method_prefix == "test_"

    def test_learn_from_java_directory(self, tmp_path):
        """从包含 Java 测试的目录学习"""
        test_subdir = tmp_path / "tests"
        test_subdir.mkdir()
        (test_subdir / "TestExample.java").write_text(JAVA_TEST_SAMPLE, encoding="utf-8")

        learner = StyleLearner()
        profile = learner.learn(str(tmp_path))
        assert profile.language == "java"

    def test_learn_empty_directory(self, tmp_path):
        """空目录返回默认 profile"""
        learner = StyleLearner()
        profile = learner.learn(str(tmp_path))
        assert isinstance(profile, StyleProfile)
        # 默认值
        assert profile.language == "python"
        assert profile.test_method_prefix == "test_"

    def test_learn_no_test_files(self, tmp_path):
        """没有测试文件的目录返回默认 profile"""
        src_dir = tmp_path / "src"
        src_dir.mkdir()
        (src_dir / "app.py").write_text("x = 1\n", encoding="utf-8")

        learner = StyleLearner()
        profile = learner.learn(str(tmp_path))
        assert isinstance(profile, StyleProfile)

    def test_learn_prefers_python_over_java(self, tmp_path):
        """同时存在 Python 和 Java 文件时优先 Python"""
        # Python 文件使用 test_* 前缀
        test_py = tmp_path / "tests" / "test_py.py"
        test_py.parent.mkdir(parents=True, exist_ok=True)
        test_py.write_text(PYTHON_TEST_SAMPLE, encoding="utf-8")

        test_java = tmp_path / "tests" / "TestJava.java"
        test_java.write_text(JAVA_TEST_SAMPLE, encoding="utf-8")

        learner = StyleLearner()
        profile = learner.learn(str(tmp_path))
        assert profile.language == "python"


# ═══════════════════════════════════════════════════════════════
# 边界情况
# ═══════════════════════════════════════════════════════════════

class TestStyleLearnerEdgeCases:
    """StyleLearner 边界情况"""

    def test_empty_file_list(self, tmp_path):
        """空文件列表"""
        learner = StyleLearner()
        profile = learner.learn_from_files([])
        assert isinstance(profile, StyleProfile)

    def test_syntax_error_python(self, tmp_path):
        """有语法错误的 Python 文件不崩溃"""
        test_file = tmp_path / "bad.py"
        test_file.write_text("def test_x(\n    # missing colon\n    pass\n", encoding="utf-8")

        learner = StyleLearner()
        profile = learner.learn_from_files([str(test_file)])
        assert profile is not None

    def test_non_test_python_files(self, tmp_path):
        """非测试 Python 文件也能分析"""
        test_file = tmp_path / "utils.py"
        test_file.write_text("# Utility functions\ndef helper(a, b):\n    return a + b\n", encoding="utf-8")

        learner = StyleLearner()
        profile = learner.learn_from_files([str(test_file)])
        assert profile.language == "python"

    def test_mixed_python_java_not_allowed(self, tmp_path):
        """learn_from_files 同时传入 Python 和 Java 以 Python 优先"""
        py_file = tmp_path / "test_a.py"
        py_file.write_text("def test_x():\n    assert True\n", encoding="utf-8")
        java_file = tmp_path / "TestA.java"
        java_file.write_text("public class TestA {}\n", encoding="utf-8")

        learner = StyleLearner()
        profile = learner.learn_from_files([str(py_file), str(java_file)])
        assert profile.language == "python"

    def test_multiple_files_averaging(self, tmp_path):
        """多个文件学习取平均值"""
        for i in range(3):
            f = tmp_path / f"test_{i}.py"
            f.write_text(f"def test_{i}():\n    assert {i} == {i}\n", encoding="utf-8")

        learner = StyleLearner()
        profile = learner.learn_from_files(
            [str(tmp_path / f"test_{i}.py") for i in range(3)]
        )
        assert profile is not None
        assert profile.language == "python"

    def test_direct_import_style_detection(self, tmp_path):
        """检测 import 分组风格 - from_heavy"""
        # 多数为 from ... import 风格
        test_file = tmp_path / "test_imports.py"
        test_file.write_text('''from foo import bar
from foo import baz
from foo import qux
import os
''', encoding="utf-8")

        learner = StyleLearner()
        profile = learner.learn_from_files([str(test_file)])
        assert profile.import_grouping == "from_heavy"

    def test_import_grouping_direct_heavy(self, tmp_path):
        """检测 import 分组风格 - direct_heavy"""
        test_file = tmp_path / "test_di.py"
        test_file.write_text('''import os
import sys
import json
from foo import bar
''', encoding="utf-8")

        learner = StyleLearner()
        profile = learner.learn_from_files([str(test_file)])
        assert profile.import_grouping == "direct_heavy"

    def test_docstring_style_triple_double(self, tmp_path):
        """检测三双引号文档字符串"""
        test_file = tmp_path / "test_ds.py"
        test_file.write_text('def test_x():\n    """Docstring."""\n    pass\n', encoding="utf-8")

        learner = StyleLearner()
        profile = learner.learn_from_files([str(test_file)])
        assert profile.docstring_style == "triple_double"

    def test_snake_case_variable_detection(self, tmp_path):
        """检测 snake_case 变量命名"""
        test_file = tmp_path / "test_var.py"
        test_file.write_text("def test_x():\n    my_value = 1\n    another_var = 2\n    assert True\n", encoding="utf-8")

        learner = StyleLearner()
        profile = learner.learn_from_files([str(test_file)])
        assert profile.variable_naming == "snake_case"

    def test_java_static_import_detection(self, tmp_path):
        """Java static import 检测"""
        test_file = tmp_path / "TestStatic.java"
        test_file.write_text('''import static org.testng.Assert.assertEquals;
import java.util.List;
public class TestStatic {
    @Test
    public void testX() {}
}''', encoding="utf-8")

        learner = StyleLearner()
        profile = learner.learn_from_files([str(test_file)])
        assert profile.import_grouping == "static_present"

    def test_java_no_static_import(self, tmp_path):
        """Java 无 static import"""
        test_file = tmp_path / "TestNoStatic.java"
        test_file.write_text('''import java.util.List;
public class TestNoStatic {
    @Test
    public void testX() {}
}''', encoding="utf-8")

        learner = StyleLearner()
        profile = learner.learn_from_files([str(test_file)])
        assert profile.import_grouping == "standard"
