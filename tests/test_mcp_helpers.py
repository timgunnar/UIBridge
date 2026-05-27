"""MCP Server 辅助函数测试 — _validate_url, _sanitize_path"""

import os
import sys
from pathlib import Path

import pytest

# Ensure uibridge is importable
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from uibridge.mcp.helpers import (
    _validate_url,
    _sanitize_output_path,
    _sanitize_input_path,
    _OUTPUT_BASE,
)


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

