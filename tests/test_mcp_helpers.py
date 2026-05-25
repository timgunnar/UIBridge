"""MCP Server 辅助函数测试 — _validate_url, _sanitize_path, _load_adapter, SourceDetector"""

import json
import os
import sys
import tempfile
from pathlib import Path

import pytest
import yaml

# Ensure uibridge is importable
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from uibridge.mcp_server import (
    _validate_url,
    _sanitize_output_path,
    _sanitize_input_path,
    _load_adapter,
    _OUTPUT_BASE,
)
from uibridge.adapter.loader import load_adapter
from uibridge.kb.source_detection import SourceDetector


# ═══════════════════════════════════════════════════════════════
# _validate_url
# ═══════════════════════════════════════════════════════════════

class TestValidateURL:
    """URL 安全校验"""

    def test_accepts_http(self):
        """接受 http:// URL"""
        assert _validate_url("http://example.com") == "http://example.com"

    def test_accepts_https(self):
        """接受 https:// URL"""
        assert _validate_url("https://example.com/path") == "https://example.com/path"

    def test_accepts_about_blank(self):
        """接受 about:blank"""
        assert _validate_url("about:blank") == "about:blank"

    def test_rejects_empty(self):
        """拒绝空字符串"""
        with pytest.raises(ValueError, match="URL 不能为空"):
            _validate_url("")

    def test_rejects_whitespace_only(self):
        """拒绝纯空白"""
        with pytest.raises(ValueError, match="URL 不能为空"):
            _validate_url("   ")

    def test_rejects_javascript_protocol(self):
        """拒绝 javascript: 协议"""
        with pytest.raises(ValueError, match="禁止的 URL 协议"):
            _validate_url("javascript:alert(1)")

    def test_rejects_data_protocol(self):
        """拒绝 data: 协议"""
        with pytest.raises(ValueError, match="禁止的 URL 协议"):
            _validate_url("data:text/html,<script>alert(1)</script>")

    def test_rejects_vbscript_protocol(self):
        """拒绝 vbscript: 协议"""
        with pytest.raises(ValueError, match="禁止的 URL 协议"):
            _validate_url("vbscript:msgbox(1)")

    def test_rejects_file_protocol(self):
        """拒绝 file: 协议"""
        with pytest.raises(ValueError, match="禁止的 URL 协议"):
            _validate_url("file:///etc/passwd")

    def test_rejects_ftp(self):
        """拒绝 ftp:// 协议"""
        with pytest.raises(ValueError, match="URL 必须以 http:// 或 https:// 开头"):
            _validate_url("ftp://example.com")

    def test_strips_whitespace(self):
        """去除首尾空白"""
        assert _validate_url("  http://example.com  ") == "http://example.com"

    def test_case_insensitive_protocol_check(self):
        """协议检查大小写不敏感"""
        with pytest.raises(ValueError, match="禁止的 URL 协议"):
            _validate_url("JAVASCRIPT:void(0)")

    def test_normal_url_with_path_and_query(self):
        """接受带路径和查询参数的 URL"""
        url = "https://example.com/path/to/page?key=value&foo=bar"
        assert _validate_url(url) == url


# ═══════════════════════════════════════════════════════════════
# _sanitize_output_path / _sanitize_input_path
# ═══════════════════════════════════════════════════════════════

class TestSanitizeOutputPath:
    """输出路径安全化"""

    def test_relative_path_stays_in_output_base(self):
        """相对路径限制在 _OUTPUT_BASE 内"""
        result = _sanitize_output_path("test.json")
        assert result.parent == _OUTPUT_BASE or str(result).startswith(str(_OUTPUT_BASE))

    def test_path_with_subdir(self):
        """子目录路径"""
        result = _sanitize_output_path("subdir/output.json")
        assert "subdir" in str(result)

    def test_single_filename(self):
        """纯文件名"""
        result = _sanitize_output_path("recording.json")
        assert result.name == "recording.json"


class TestSanitizeInputPath:
    """输入路径解析"""

    def test_resolve_relative_path(self):
        """解析相对路径"""
        result = _sanitize_input_path("test.json")
        assert result.is_absolute()

    def test_keep_absolute_path(self):
        """保持绝对路径"""
        path = "/tmp/test.json" if sys.platform != "win32" else "C:/temp/test.json"
        result = _sanitize_input_path(path)
        assert result.is_absolute()


# ═══════════════════════════════════════════════════════════════
# _load_adapter
# ═══════════════════════════════════════════════════════════════

class TestLoadAdapterHelper:
    """_load_adapter — MCP Server 适配器加载"""

    def test_default_returns_five_components(self):
        """无参数返回 5 个组件"""
        result = _load_adapter()
        assert isinstance(result, tuple)
        assert len(result) == 5
        from uibridge.adapter.base import (
            ComponentResolver, LocatorStrategy, ActionRecognizer,
            CodeGenerator, DataFormatter,
        )
        resolver, locator, recognizer, code_gen, data_fmt = result
        assert isinstance(resolver, ComponentResolver)
        assert isinstance(locator, LocatorStrategy)
        assert isinstance(recognizer, ActionRecognizer)
        assert isinstance(code_gen, CodeGenerator)
        assert isinstance(data_fmt, DataFormatter)

    def test_none_config_returns_default(self):
        """None 配置返回参考实现"""
        result = _load_adapter(None)
        assert len(result) == 5

    def test_custom_config_minimal(self, tmp_path):
        """自定义 YAML 配置加载指定组件"""
        config_file = tmp_path / "adapter.yaml"
        config_file.write_text(yaml.dump({
            "adapter": {
                "components": {
                    "resolver": "uibridge.adapter.reference.ReferenceComponentResolver",
                    "locator": "uibridge.adapter.reference.ReferenceLocatorStrategy",
                    "recognizer": "uibridge.adapter.reference.ReferenceActionRecognizer",
                    "generator": "uibridge.adapter.reference.ReferenceCodeGenerator",
                    "data_formatter": "uibridge.adapter.reference.ReferenceDataFormatter",
                }
            }
        }), encoding="utf-8")

        result = _load_adapter(str(config_file))
        assert len(result) == 5

    def test_custom_config_json(self, tmp_path):
        """自定义 JSON 配置"""
        config_file = tmp_path / "adapter.json"
        config_file.write_text(json.dumps({
            "adapter": {
                "components": {
                    "resolver": "uibridge.adapter.reference.ReferenceComponentResolver",
                    "locator": "uibridge.adapter.reference.ReferenceLocatorStrategy",
                    "recognizer": "uibridge.adapter.reference.ReferenceActionRecognizer",
                    "generator": "uibridge.adapter.reference.ReferenceCodeGenerator",
                    "data_formatter": "uibridge.adapter.reference.ReferenceDataFormatter",
                }
            }
        }), encoding="utf-8")

        result = _load_adapter(str(config_file))
        assert len(result) == 5

    def test_invalid_config_path_falls_back(self):
        """不存在的配置文件回退到默认实现"""
        result = _load_adapter("nonexistent_config_file_xyz.yaml")
        assert len(result) == 5

    def test_delegates_to_load_adapter_module(self):
        """调用委托给 adapter.loader.load_adapter"""
        result = _load_adapter()
        expected = load_adapter()
        assert len(result) == len(expected)


# ═══════════════════════════════════════════════════════════════
# SourceDetector — _detect_source_dirs / _scan_java_dirs
# ═══════════════════════════════════════════════════════════════

class TestSourceDetectorJava:
    """SourceDetector Java 项目检测"""

    def test_scan_java_dirs_standard_layout(self, tmp_path):
        """标准 Maven 布局: src/main/java 和 src/test/java"""
        src_main = tmp_path / "src" / "main" / "java" / "com" / "example"
        src_main.mkdir(parents=True)
        (src_main / "MainPage.java").write_text("package com.example;")

        src_test = tmp_path / "src" / "test" / "java" / "com" / "example"
        src_test.mkdir(parents=True)
        (src_test / "TestMain.java").write_text("package com.example;")

        detector = SourceDetector(str(tmp_path))
        # 无 pom.xml，通过 scan_java_dirs 反推
        result = detector._scan_java_dirs(tmp_path)
        assert result is not None
        assert "pages" in result or "tests" in result

    def test_scan_java_dirs_no_java_files(self, tmp_path):
        """没有 .java 文件时返回 None"""
        src_main = tmp_path / "src" / "main" / "java"
        src_main.mkdir(parents=True)
        (src_main / "readme.txt").write_text("not java")

        detector = SourceDetector(str(tmp_path))
        result = detector._scan_java_dirs(tmp_path)
        assert result is None

    def test_scan_java_dirs_no_src(self, tmp_path):
        """没有 src/ 目录返回 None"""
        detector = SourceDetector(str(tmp_path))
        result = detector._scan_java_dirs(tmp_path)
        assert result is None

    def test_detect_maven_project(self, tmp_path):
        """检测 Maven 项目 (pom.xml 存在)"""
        pom = tmp_path / "pom.xml"
        pom.write_text("""<?xml version="1.0"?>
<project>
    <modelVersion>4.0.0</modelVersion>
    <groupId>com.example</groupId>
    <artifactId>test</artifactId>
</project>""")

        src_main = tmp_path / "src" / "main" / "java" / "com"
        src_main.mkdir(parents=True)
        (src_main / "App.java").write_text("package com;")

        detector = SourceDetector(str(tmp_path))
        result = detector.detect()
        assert "pages" in result
        assert "tests" in result

    def test_detect_maven_with_custom_source_dirs(self, tmp_path):
        """pom.xml 自定义 sourceDirectory"""
        pom = tmp_path / "pom.xml"
        pom.write_text("""<?xml version="1.0"?>
<project>
    <modelVersion>4.0.0</modelVersion>
    <build>
        <sourceDirectory>src/main/custom-java</sourceDirectory>
        <testSourceDirectory>src/test/custom-test</testSourceDirectory>
    </build>
</project>""")

        detector = SourceDetector(str(tmp_path))
        result = detector.detect()
        assert "pages" in result
        assert result["pages"] == "src/main/custom-java"

    def test_detect_python_project(self, tmp_path):
        """检测 Python 项目 (pyproject.toml 存在)"""
        (tmp_path / "pyproject.toml").write_text("[project]\nname='test'")
        pages_dir = tmp_path / "pages"
        pages_dir.mkdir()
        (pages_dir / "__init__.py").write_text("")
        (pages_dir / "login.py").write_text("class LoginPage: pass")
        tests_dir = tmp_path / "tests"
        tests_dir.mkdir()
        (tests_dir / "__init__.py").write_text("")
        (tests_dir / "test_login.py").write_text("def test_login(): pass")

        detector = SourceDetector(str(tmp_path))
        result = detector.detect()
        assert result.get("pages") == "pages"
        assert result.get("tests") == "tests"

    def test_detect_empty_project_returns_default(self, tmp_path):
        """空项目返回默认值"""
        detector = SourceDetector(str(tmp_path))
        result = detector.detect()
        # 兜底返回默认值
        assert isinstance(result, dict)
        assert "pages" in result or "tests" in result

    def test_detect_single_module_maven(self, tmp_path):
        """单模块 Maven 项目检测"""
        pom = tmp_path / "pom.xml"
        pom.write_text("""<?xml version="1.0"?>
<project><modelVersion>4.0.0</modelVersion></project>""")
        src_main = tmp_path / "src" / "main" / "java" / "com"
        src_main.mkdir(parents=True)
        (src_main / "App.java").write_text("package com;")

        src_test = tmp_path / "src" / "test" / "java" / "com"
        src_test.mkdir(parents=True)
        (src_test / "AppTest.java").write_text("package com;")

        detector = SourceDetector(str(tmp_path))
        result = detector.detect()
        assert result["pages"] == "src/main/java" or "src/main/java" in result["pages"]
        assert result["tests"] == "src/test/java" or "src/test/java" in result["tests"]


class TestSourceDetectorAWInference:
    """SourceDetector AW 目录推断"""

    def test_infer_aw_dir_from_standard_layout(self, tmp_path):
        """Maven 标准布局中推断 aw 目录"""
        src_main = tmp_path / "src" / "main" / "java" / "com"
        src_main.mkdir(parents=True)
        (src_main / "Page.java").write_text("package com;")
        aw_dir = tmp_path / "src" / "main" / "java" / "aw"
        aw_dir.mkdir(parents=True)
        (aw_dir / "TableAW.java").write_text("package com.aw;")

        detector = SourceDetector(str(tmp_path))
        result = detector._infer_aw_dir(tmp_path, "src/main/java/com")
        assert result is not None
        assert "aw" in result

    def test_infer_aw_dir_nonexistent_pages(self, tmp_path):
        """pages 目录不存在时返回 None"""
        detector = SourceDetector(str(tmp_path))
        result = detector._infer_aw_dir(tmp_path, "nonexistent/dir")
        assert result is None


class TestSourceDetectorCommonPrefix:
    """SourceDetector._common_prefix"""

    def test_single_path(self):
        """单个路径返回自身"""
        assert SourceDetector._common_prefix(["src/main/java"]) == "src/main/java"

    def test_two_paths_common_prefix(self):
        """两个路径找公共前缀"""
        result = SourceDetector._common_prefix([
            "src/main/java/com",
            "src/main/java/org",
        ])
        assert result == "src/main/java"

    def test_no_common_prefix(self):
        """无公共前缀返回空"""
        result = SourceDetector._common_prefix(["a/b", "c/d"])
        assert result == ""

    def test_empty_list(self):
        """空列表返回空"""
        result = SourceDetector._common_prefix([])
        assert result == ""


class TestSourceDetectorEdgeCases:
    """SourceDetector 边界情况"""

    def test_detect_with_aw_and_pages(self, tmp_path):
        """项目同时有 aw 和 pages 目录"""
        src_main = tmp_path / "src" / "main" / "java" / "com"
        src_main.mkdir(parents=True)
        (src_main / "Page.java").write_text("package com;")
        aw_dir = tmp_path / "src" / "main" / "java" / "aw"
        aw_dir.mkdir(parents=True)
        (aw_dir / "TableAW.java").write_text("package com.aw;")
        pytest_file = tmp_path / "src" / "test" / "java" / "com"
        pytest_file.mkdir(parents=True)
        (pytest_file / "TestPage.java").write_text("package com;")

        detector = SourceDetector(str(tmp_path))
        result = detector._scan_java_dirs(tmp_path)
        assert result is not None
        assert "component_aw" in result or "aw" in str(result.get("component_aw", ""))

    def test_empty_tmp_dir(self, tmp_path):
        """空目录检测不崩溃"""
        detector = SourceDetector(str(tmp_path))
        result = detector.detect()
        assert isinstance(result, dict)


# ═══════════════════════════════════════════════════════════════
# load_adapter (共享工厂)
# ═══════════════════════════════════════════════════════════════

class TestLoadAdapter:
    """load_adapter 共享工厂测试"""

    def test_default_returns_reference_impl(self):
        """无参数返回参考实现"""
        result = load_adapter()
        assert len(result) == 5

    def test_nonexistent_class_in_config(self, tmp_path):
        """配置引用不存在的类时应抛出 ImportError"""
        config_file = tmp_path / "bad_adapter.yaml"
        config_file.write_text(yaml.dump({
            "adapter": {
                "components": {
                    "resolver": "nonexistent.module.NonExistentClass",
                }
            }
        }), encoding="utf-8")

        with pytest.raises(ImportError, match="无法加载适配器组件"):
            load_adapter(str(config_file))

    def test_json_config(self, tmp_path):
        """JSON 格式配置"""
        config_file = tmp_path / "adapter.json"
        config_file.write_text(json.dumps({
            "adapter": {
                "components": {
                    "resolver": "uibridge.adapter.reference.ReferenceComponentResolver",
                }
            }
        }), encoding="utf-8")

        result = load_adapter(str(config_file))
        assert len(result) == 5  # 未指定的使用默认

    def test_components_with_defaults(self, tmp_path):
        """部分指定组件，其余回退默认"""
        config_file = tmp_path / "partial.yaml"
        config_file.write_text(yaml.dump({
            "adapter": {
                "components": {
                    "generator": "uibridge.adapter.reference.ReferenceCodeGenerator",
                }
            }
        }), encoding="utf-8")

        result = load_adapter(str(config_file))
        assert len(result) == 5
