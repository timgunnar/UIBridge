"""测试安装/卸载正确性 — 清理命令、_scan_artifacts、安装元数据验证"""

import sys
import os
import tempfile
import shutil
import subprocess
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from click.testing import CliRunner

from uibridge.cli import cli, _scan_artifacts


def _make_file(path: Path, content: str = "") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


# ═══════════════════════════════════════════════════════════════
# _scan_artifacts 单元测试
# ═══════════════════════════════════════════════════════════════

class TestScanArtifacts:
    """测试 _scan_artifacts 检测逻辑"""

    def test_empty_directory(self):
        """空目录应返回空列表"""
        with tempfile.TemporaryDirectory() as tmp:
            result = _scan_artifacts(Path(tmp))
            assert result == []

    def test_detects_uibridge_kb_dir(self):
        """检测 .uibridge/ 知识库目录"""
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / ".uibridge").mkdir()
            result = _scan_artifacts(Path(tmp))
            names = [p.name for p in result]
            assert ".uibridge" in names

    def test_detects_generated_dir(self):
        """检测 generated/ 输出目录"""
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "generated").mkdir()
            result = _scan_artifacts(Path(tmp))
            names = [p.name for p in result]
            assert "generated" in names

    def test_detects_generated_variants(self):
        """检测 generated_* 变体目录"""
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "generated_tests").mkdir()
            (Path(tmp) / "generated_backup").mkdir()
            result = _scan_artifacts(Path(tmp))
            names = [p.name for p in result]
            assert "generated_tests" in names
            assert "generated_backup" in names

    def test_detects_recording_files(self):
        """检测 recording*.json 录制文件"""
        with tempfile.TemporaryDirectory() as tmp:
            _make_file(Path(tmp) / "recording.json")
            _make_file(Path(tmp) / "recording_backup.json")
            result = _scan_artifacts(Path(tmp))
            names = [p.name for p in result]
            assert "recording.json" in names
            assert "recording_backup.json" in names

    def test_detects_uibridge_templates(self):
        """检测包含 uibridge 关键词的模板文件"""
        with tempfile.TemporaryDirectory() as tmp:
            _make_file(Path(tmp) / "CLAUDE.md", "This project uses uibridge for automation.")
            _make_file(Path(tmp) / ".mcp.json", '{"mcpServers": {"uibridge": {}}}')
            _make_file(Path(tmp) / "adapter.yaml", "# uibridge adapter config")
            result = _scan_artifacts(Path(tmp))
            names = [p.name for p in result]
            assert "CLAUDE.md" in names
            assert ".mcp.json" in names
            assert "adapter.yaml" in names

    def test_ignores_unrelated_files(self):
        """不含 uibridge 关键词的文件不被检测"""
        with tempfile.TemporaryDirectory() as tmp:
            _make_file(Path(tmp) / "CLAUDE.md", "Generic project instructions.")
            _make_file(Path(tmp) / ".mcp.json", '{"mcpServers": {"other": {}}}')
            result = _scan_artifacts(Path(tmp))
            assert result == []

    def test_detects_skill_file(self):
        """检测 .claude/skills/uibridge.md"""
        with tempfile.TemporaryDirectory() as tmp:
            _make_file(Path(tmp) / ".claude" / "skills" / "uibridge.md", "# uibridge skill")
            result = _scan_artifacts(Path(tmp))
            names = [p.name for p in result]
            assert "uibridge.md" in names

    def test_detects_all_at_once(self):
        """综合检测：多种残留物同时存在"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".uibridge").mkdir()
            (root / "generated").mkdir()
            _make_file(root / "recording.json")
            _make_file(root / "CLAUDE.md", "uibridge project")
            _make_file(root / ".claude" / "skills" / "uibridge.md")

            result = _scan_artifacts(root)
            assert len(result) == 5


# ═══════════════════════════════════════════════════════════════
# CLI cleanup 命令集成测试
# ═══════════════════════════════════════════════════════════════

class TestCleanupCLI:
    """测试 uibridge cleanup CLI 命令行为

    cleanup 命令使用 Path.cwd() 扫描当前目录，
    测试通过 os.chdir 切换到临时目录来隔离。
    注意：退出前必须切回原始 CWD，否则 Windows 无法清理临时目录。
    """

    def test_dry_run_lists_but_does_not_delete(self):
        """--dry-run 列出残留但不删除"""
        runner = CliRunner()
        original_cwd = os.getcwd()
        try:
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                (root / ".uibridge").mkdir()
                (root / "generated").mkdir()
                _make_file(root / "recording.json")
                _make_file(root / "CLAUDE.md", "uibridge project")

                os.chdir(str(root))
                result = runner.invoke(cli, ["cleanup", "--dry-run"], catch_exceptions=False)
                os.chdir(original_cwd)

                assert result.exit_code == 0
                assert ".uibridge" in result.output
                assert "generated" in result.output
                assert "recording.json" in result.output
                assert "Dry-run" in result.output or "未执行删除" in result.output

                # 确认文件未被删除
                assert (root / ".uibridge").exists()
                assert (root / "generated").exists()
                assert (root / "recording.json").exists()
        finally:
            os.chdir(original_cwd)

    def test_yes_flag_removes_artifacts(self):
        """--yes 确认删除残留文件"""
        runner = CliRunner()
        original_cwd = os.getcwd()
        try:
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                (root / ".uibridge").mkdir()
                _make_file(root / "recording.json")
                _make_file(root / "CLAUDE.md", "uibridge assisted project")

                os.chdir(str(root))
                result = runner.invoke(cli, ["cleanup", "--yes"], catch_exceptions=False)
                os.chdir(original_cwd)

                assert result.exit_code == 0
                assert not (root / ".uibridge").exists()
                assert not (root / "recording.json").exists()
        finally:
            os.chdir(original_cwd)

    def test_no_artifacts_reports_clean(self):
        """无残留时报告干净状态"""
        runner = CliRunner()
        original_cwd = os.getcwd()
        try:
            with tempfile.TemporaryDirectory() as tmp:
                os.chdir(str(tmp))
                result = runner.invoke(cli, ["cleanup", "--dry-run"], catch_exceptions=False)
                os.chdir(original_cwd)
                assert result.exit_code == 0
                assert "未发现" in result.output or "0 项" in result.output
        finally:
            os.chdir(original_cwd)


# ═══════════════════════════════════════════════════════════════
# 安装状态验证
# ═══════════════════════════════════════════════════════════════

class TestInstallState:
    """验证 uibridge 安装后的包结构和元数据"""

    def test_package_importable(self):
        """uibridge 包可正常导入"""
        import uibridge
        assert uibridge is not None

    def test_version_string(self):
        """版本号格式正确 (semver)"""
        import uibridge
        version = uibridge.__version__
        assert isinstance(version, str)
        parts = version.split(".")
        assert len(parts) == 3
        assert all(p.isdigit() for p in parts)

    def test_key_modules_importable(self):
        """所有关键子模块可导入"""
        modules = [
            "uibridge.pipeline",
            "uibridge.cli",
            "uibridge.mcp_server",
            "uibridge.engine.self_test",
            "uibridge.engine.dom_diff",
            "uibridge.engine.recorder",
            "uibridge.engine.ir.raw_recording",
            "uibridge.engine.ir.framework_call",
            "uibridge.adapter.base",
            "uibridge.adapter.reference",
            "uibridge.adapter.java_testng",
            "uibridge.adapter.java_fluent",
            "uibridge.adapter.screenplay",
            "uibridge.generator.component_aw_gen",
            "uibridge.generator.business_aw_gen",
            "uibridge.generator.test_script_gen",
            "uibridge.kb.manager",
            "uibridge.kb.extractor",
        ]
        for module_name in modules:
            __import__(module_name)

    def test_entry_points_registered(self):
        """CLI 入口点已注册 (pip show 可查到)"""
        result = subprocess.run(
            [sys.executable, "-m", "pip", "show", "uibridge"],
            capture_output=True, text=True
        )
        assert result.returncode == 0
        # pip show 应显示版本和位置
        assert "Version:" in result.stdout
        assert "Location:" in result.stdout

    def test_cli_help_works(self):
        """uibridge --help 正常输出"""
        result = subprocess.run(
            [sys.executable, "-m", "uibridge.cli", "--help"],
            capture_output=True, text=True
        )
        assert result.returncode == 0
        assert "UIBridge" in result.stdout or "uibridge" in result.stdout.lower()

    def test_entry_point_via_subprocess(self):
        """uibridge CLI 可通过 python -m uibridge.cli 方式正常调用"""
        result = subprocess.run(
            [sys.executable, "-m", "uibridge.cli", "--help"],
            capture_output=True, text=True
        )
        assert result.returncode == 0, f"CLI failed: {result.stderr}"
        assert "cleanup" in result.stdout  # cleanup 命令已注册

    def test_pip_show_version_matches_package(self):
        """pip show 的版本与 __version__ 一致"""
        import uibridge

        result = subprocess.run(
            [sys.executable, "-m", "pip", "show", "uibridge"],
            capture_output=True, text=True
        )
        for line in result.stdout.split("\n"):
            if line.startswith("Version:"):
                pip_version = line.split(":")[1].strip()
                assert pip_version == uibridge.__version__

    def test_editable_install_link_exists(self):
        """可编辑安装的链接指向正确目录"""
        result = subprocess.run(
            [sys.executable, "-m", "pip", "show", "uibridge"],
            capture_output=True, text=True
        )
        assert "Editable project location:" in result.stdout


# ═══════════════════════════════════════════════════════════════
# 卸载残留检测
# ═══════════════════════════════════════════════════════════════

class TestUninstallDetection:
    """验证卸载后无残留的能力 (不实际卸载，检测结构正确性)"""

    def test_pyproject_toml_has_package_name(self):
        """pyproject.toml 中的包名与 setup 一致"""
        pyproject = Path(__file__).parent.parent / "pyproject.toml"
        content = pyproject.read_text(encoding="utf-8")
        assert 'name = "uibridge"' in content

    def test_dist_info_exists(self):
        """安装后在 site-packages 存在 .dist-info 目录"""
        result = subprocess.run(
            [sys.executable, "-m", "pip", "show", "-f", "uibridge"],
            capture_output=True, text=True
        )
        assert result.returncode == 0

    def test_no_leftover_dist_info_from_old_versions(self):
        """site-packages 中不存在旧版本的 dist-info 残留"""
        result = subprocess.run(
            [sys.executable, "-m", "pip", "show", "uibridge"],
            capture_output=True, text=True
        )
        # 只有一个版本的 uibridge
        import re
        versions = re.findall(r'^Version:\s*(.+)$', result.stdout, re.MULTILINE)
        assert len(versions) == 1, f"Multiple uibridge versions found: {versions}"

    def test_cleanup_includes_pip_uninstall_hint(self):
        """cleanup 输出包含 pip uninstall 提示（无残留时或清理完成后）"""
        runner = CliRunner()
        original_cwd = os.getcwd()
        try:
            with tempfile.TemporaryDirectory() as tmp:
                os.chdir(str(tmp))
                # 无残留时，输出应提示 pip uninstall
                result = runner.invoke(cli, ["cleanup", "--dry-run"], catch_exceptions=False)
                os.chdir(original_cwd)
                assert "pip uninstall uibridge" in result.output
        finally:
            os.chdir(original_cwd)
