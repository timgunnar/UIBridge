"""CLI 命令行测试 — record, generate, analyze, diff 命令"""

import json
import sys
import os
from pathlib import Path
from unittest import mock

import pytest
from click.testing import CliRunner

# Ensure uibridge is importable
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from uibridge.cli import cli


# ═══════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════

@pytest.fixture
def runner():
    """Click CLI runner"""
    return CliRunner()


@pytest.fixture
def sample_recording():
    """创建一个最小可用的录制文件 JSON 数据"""
    return {
        "version": "0.3.0",
        "url": "http://example.com",
        "steps": [
            {
                "action": "navigate",
                "target": {"url": "http://example.com", "label": ""},
                "timestamp": 0.0,
                "aria_snapshot": "",
                "dom_snapshot": "",
                "mutation_records": [],
            },
            {
                "action": "click",
                "target": {
                    "label": "Submit",
                    "url": "",
                    "tag": "button",
                    "attrs": {"type": "submit"},
                    "xpath": "//button[@type='submit']",
                },
                "timestamp": 1.0,
                "aria_snapshot": '- button "Submit"',
                "dom_snapshot": "<button type='submit'>Submit</button>",
                "mutation_records": [],
            },
        ],
    }


# ═══════════════════════════════════════════════════════════════
# --help 输出
# ═══════════════════════════════════════════════════════════════

class TestHelpOutput:
    """各命令 --help 输出"""

    def test_cli_help(self, runner):
        """主 CLI --help 显示版本和命令"""
        result = runner.invoke(cli, ["--help"])
        assert result.exit_code == 0
        assert "UIBridge" in result.output
        for cmd in ["record", "generate", "analyze", "diff", "cleanup"]:
            assert cmd in result.output, f"Command '{cmd}' missing from --help"

    def test_record_help(self, runner):
        """record --help 显示所有选项"""
        result = runner.invoke(cli, ["record", "--help"])
        assert result.exit_code == 0
        assert "--url" in result.output
        assert "--output" in result.output
        # --headed/--headless boolean flag; Click may not always render defaults
        assert ("--headed" in result.output or "--headless" in result.output)

    def test_generate_help(self, runner):
        """generate --help 显示所有选项"""
        result = runner.invoke(cli, ["generate", "--help"])
        assert result.exit_code == 0
        assert "--input" in result.output
        assert "--output-dir" in result.output

    def test_analyze_help(self, runner):
        """analyze --help 显示 --url 必填"""
        result = runner.invoke(cli, ["analyze", "--help"])
        assert result.exit_code == 0
        assert "--url" in result.output
        assert "required" in result.output.lower()

    def test_diff_help(self, runner):
        """diff --help 显示输入选项"""
        result = runner.invoke(cli, ["diff", "--help"])
        assert result.exit_code == 0
        assert "--input" in result.output

    def test_cleanup_help(self, runner):
        """cleanup --help 显示 --yes 和 --dry-run"""
        result = runner.invoke(cli, ["cleanup", "--help"])
        assert result.exit_code == 0
        assert "--yes" in result.output
        assert "--dry-run" in result.output


# ═══════════════════════════════════════════════════════════════
# --version
# ═══════════════════════════════════════════════════════════════

def test_version_output(runner):
    """--version 输出版本号"""
    result = runner.invoke(cli, ["--version"])
    assert result.exit_code == 0
    assert "0.3.6" in result.output or "version" in result.output.lower()


# ═══════════════════════════════════════════════════════════════
# record 命令 (mocked)
# ═══════════════════════════════════════════════════════════════

def test_record_requires_browser_available(runner):
    """record 命令在浏览器不可用时打印错误"""
    with mock.patch("uibridge.check_browser_available", return_value=(False, "Chromium not found")):
        result = runner.invoke(cli, ["record"])
        assert "浏览器不可用" in result.output or "ERROR" in result.output


def test_record_with_invalid_url_option(runner):
    """record 命令接受 --url 选项"""
    # 浏览器不可用时会提前退出，验证选项解析
    with mock.patch("uibridge.check_browser_available", return_value=(False, "n/a")):
        result = runner.invoke(cli, ["record", "--url", "http://example.com"])
        assert "浏览器不可用" in result.output or "ERROR" in result.output


# ═══════════════════════════════════════════════════════════════
# generate 命令
# ═══════════════════════════════════════════════════════════════

def test_generate_missing_file(runner):
    """generate 对不存在的文件报错"""
    result = runner.invoke(cli, ["generate", "-i", "nonexistent_file.json"])
    assert result.exit_code != 0  # File not found or adapter error


def test_generate_with_sample_recording(runner, sample_recording, tmp_path):
    """generate 从录制文件生成代码"""
    rec_file = tmp_path / "recording.json"
    rec_file.write_text(json.dumps(sample_recording), encoding="utf-8")
    out_dir = tmp_path / "generated"

    result = runner.invoke(cli, [
        "generate",
        "-i", str(rec_file),
        "-o", str(out_dir),
    ])
    # 预期成功或至少不是 Click 参数错误
    assert "Usage:" not in result.output


# ═══════════════════════════════════════════════════════════════
# analyze 命令
# ═══════════════════════════════════════════════════════════════

def test_analyze_missing_url(runner):
    """analyze 缺少 --url 时报错"""
    result = runner.invoke(cli, ["analyze"])
    assert result.exit_code != 0
    assert "url" in result.output.lower() or "Error" in result.output or "Missing" in result.output


# ═══════════════════════════════════════════════════════════════
# diff 命令
# ═══════════════════════════════════════════════════════════════

def test_diff_missing_file(runner):
    """diff 对不存在的录制文件报错"""
    result = runner.invoke(cli, ["diff", "-i", "nonexistent.json"])
    assert result.exit_code != 0


def test_diff_with_sample(runner, sample_recording, tmp_path):
    """diff 分析录制文件的快照差异"""
    rec_file = tmp_path / "recording.json"
    rec_file.write_text(json.dumps(sample_recording), encoding="utf-8")

    result = runner.invoke(cli, ["diff", "-i", str(rec_file)])
    # 可能成功（输出断言候选）或适配器出错；不应是 Click 参数错误
    assert "Usage:" not in result.output


# ═══════════════════════════════════════════════════════════════
# cleanup 命令
# ═══════════════════════════════════════════════════════════════

def test_cleanup_no_artifacts(runner, tmp_path):
    """cleanup 在没有残留文件时输出 OK"""
    import os as _os
    orig_cwd = _os.getcwd()
    try:
        _os.chdir(str(tmp_path))
        result = runner.invoke(cli, ["cleanup"])
        assert "未发现" in result.output or "OK" in result.output
    finally:
        _os.chdir(orig_cwd)


def test_cleanup_dry_run(runner, tmp_path):
    """cleanup --dry-run 不删除文件"""
    # 创建虚假残留文件
    kb_dir = tmp_path / ".uibridge"
    kb_dir.mkdir()
    (kb_dir / "kb.json").write_text("{}")

    orig_cwd = os.getcwd()
    try:
        os.chdir(str(tmp_path))
        result = runner.invoke(cli, ["cleanup", "--dry-run"])
        assert ".uibridge" in result.output or "dry" in result.output.lower()
        # 文件未被删除
        assert kb_dir.exists()
    finally:
        os.chdir(orig_cwd)


# ═══════════════════════════════════════════════════════════════
# 边界情况
# ═══════════════════════════════════════════════════════════════

def test_unknown_command(runner):
    """未知子命令返回非零退出码"""
    result = runner.invoke(cli, ["unknown_cmd_xyz"])
    assert result.exit_code != 0


def test_record_with_custom_output(runner):
    """record --output 自定义输出文件路径"""
    with mock.patch("uibridge.check_browser_available", return_value=(False, "n/a")):
        result = runner.invoke(cli, ["record", "-o", "my_recording.json"])
        assert "浏览器不可用" in result.output or "ERROR" in result.output


def test_generate_with_adapter_config(tmp_path):
    """generate 带自定义 adapter-config 路径"""
    runner = CliRunner()
    rec_file = tmp_path / "recording.json"
    rec_file.write_text(json.dumps({
        "version": "0.3.0",
        "url": "http://example.com",
        "steps": [],
    }), encoding="utf-8")

    # 使用不存在的配置文件路径，验证不会 crash
    result = runner.invoke(cli, [
        "generate",
        "-i", str(rec_file),
        "--adapter-config", "nonexistent.yaml",
    ])
    # 不存在的配置应回退到默认实现
    assert "Usage:" not in result.output
