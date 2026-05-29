"""CLI 入口 — uibridge 命令行工具"""

import logging
import sys
import json
from pathlib import Path

import click
from playwright.sync_api import sync_playwright

# Removed imports (modules deleted):
#   from .pipeline import Pipeline
#   from .adapter.loader import load_adapter
#   from .source_detection import SourceDetector
#   from .profile_manager import ProfileManager
from .kb.manager import KBManager
from .kb.extractor import KBExtractor

logger = logging.getLogger(__name__)


def _load_adapter_safe(adapter_config):
    """[STUB] 适配器加载已移除（adapter/ 目录已删除）。CLI 将在后续版本重写。"""
    raise NotImplementedError("Adapter loading removed. CLI rewrite planned.")


def _ensure_browser_or_die():
    """验证 Chromium 浏览器可用，不可用时打印错误并退出"""
    from . import check_browser_available
    available, info = check_browser_available("chromium")
    if not available:
        click.echo(f"[ERROR] 浏览器不可用: {info}", err=True)
        click.echo("请运行: playwright install chromium", err=True)
        import sys
        sys.exit(1)


# ═══════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════

@click.group()
@click.version_option(version="0.4.1")
def cli():
    """UIBridge — UI自动化测试框架知识翻译层"""


@cli.command()
@click.option("--url", default="about:blank", help="起始 URL")
@click.option("--output", "-o", default="recording.json", help="录制输出文件")
@click.option("--headed/--headless", default=True, help="是否显示浏览器窗口")
@click.option("--adapter-config", default=None, help="适配器配置文件路径")
def record(url: str, output: str, headed: bool, adapter_config: str):
    """[STUB] 录制浏览器操作。adapter/pipeline 已移除，CLI 将在后续版本重写。"""
    click.echo("[ERROR] record 命令暂不可用。适配器和 pipeline 已移除，CLI 重写计划中。", err=True)
    sys.exit(1)


@cli.command()
@click.option("--input", "-i", "input_file", default="recording.json", help="录制文件")
@click.option("--output-dir", "-o", default="generated", help="生成代码输出目录")
@click.option("--adapter-config", default=None, help="适配器配置文件路径")
def generate(input_file: str, output_dir: str, adapter_config: str):
    """[STUB] 从录制文件生成测试脚本。adapter/pipeline 已移除，CLI 将在后续版本重写。"""
    click.echo("[ERROR] generate 命令暂不可用。适配器和 pipeline 已移除，CLI 重写计划中。", err=True)
    sys.exit(1)


@cli.command()
@click.option("--url", required=True, help="待分析的页面 URL")
@click.option("--adapter-config", default=None, help="适配器配置文件路径")
def analyze(url: str, adapter_config: str):
    """[STUB] 分析页面。adapter/pipeline 已移除，CLI 将在后续版本重写。"""
    click.echo("[ERROR] analyze 命令暂不可用。适配器和 pipeline 已移除，CLI 重写计划中。", err=True)
    sys.exit(1)


@cli.command()
@click.option("--input", "-i", "input_file", default="recording.json", help="录制文件")
@click.option("--adapter-config", default=None, help="适配器配置文件路径")
def diff(input_file: str, adapter_config: str):
    """[STUB] 分析录制快照差异。adapter/pipeline 已移除，CLI 将在后续版本重写。"""
    click.echo("[ERROR] diff 命令暂不可用。适配器和 pipeline 已移除，CLI 重写计划中。", err=True)
    sys.exit(1)


@cli.command()
@click.option("--yes", "-y", is_flag=True, help="跳过确认，直接执行清理")
@click.option("--dry-run", is_flag=True, help="仅列出将被清理的文件，不执行")
def cleanup(yes: bool, dry_run: bool):
    """清理当前项目中所有 uibridge 生成的文件和目录

    检测并移除:
    - .uibridge/ 知识库目录
    - generated/ 生成代码目录
    - recording.json 录制文件
    - templates/ 中从 uibridge 复制的文件 (CLAUDE.md, .mcp.json, adapter.yaml)
    - .claude/skills/uibridge.md 技能文件
    - Python 环境中可编辑安装残留（site-packages + Scripts）

    使用 pip uninstall uibridge 卸载 Python 包本身。
    """
    cwd = Path.cwd()
    artifacts = _scan_artifacts(cwd)

    # 同时扫描系统级可编辑安装残留
    system_artifacts = _scan_system_artifacts()

    all_artifacts = artifacts + system_artifacts

    if not all_artifacts:
        click.echo("[OK] 未发现 uibridge 残留文件。")
        click.echo("卸载 Python 包: pip uninstall uibridge")
        return

    # 报告
    if artifacts:
        click.echo(f"\n项目残留 ({len(artifacts)} 项):\n")
        for item in artifacts:
            click.echo(f"  {item}")
    if system_artifacts:
        click.echo(f"\nPython 环境可编辑安装残留 ({len(system_artifacts)} 项):\n")
        for item in system_artifacts:
            click.echo(f"  {item}")

    total_size = sum(
        sum(f.stat().st_size for f in p.rglob("*") if f.is_file())
        if p.is_dir() else p.stat().st_size
        for p in all_artifacts
    )
    if total_size:
        click.echo(f"\n总计: ~{total_size / 1024:.1f} KB")

    if dry_run:
        click.echo("\n[Dry-run] 未执行删除。使用 --yes 确认清理。")
        return

    if not yes:
        click.confirm("\n确认删除以上所有文件?", abort=True)

    # 执行清理
    import shutil
    removed = 0
    for item in all_artifacts:
        try:
            if item.is_dir():
                shutil.rmtree(item)
            else:
                item.unlink()
            click.echo(f"  [OK] 已删除: {item}")
            removed += 1
        except OSError as e:
            click.echo(f"  [WARN] 删除失败: {item} ({e})")

    click.echo(f"\n[DONE] 已清理 {removed} 项。")
    if not system_artifacts:
        click.echo("卸载 Python 包: pip uninstall uibridge")


def _scan_artifacts(cwd: Path) -> list[Path]:
    """扫描项目目录，返回 uibridge 残留文件/目录列表"""
    artifacts = []

    # .uibridge/ 知识库目录
    kb_dir = cwd / ".uibridge"
    if kb_dir.exists():
        artifacts.append(kb_dir)

    # generated/ 及 generated_* 自定义输出目录
    gen_dir = cwd / "generated"
    if gen_dir.exists():
        artifacts.append(gen_dir)
    for d in cwd.glob("generated_*"):
        if d.is_dir():
            artifacts.append(d)

    # recording*.json
    for rec in cwd.glob("recording*.json"):
        if rec.is_file():
            artifacts.append(rec)

    # 根目录下的 uibridge 模板文件 (CLAUDE.md, .mcp.json, adapter.yaml)
    for fname in ["CLAUDE.md", ".mcp.json", "adapter.yaml"]:
        fpath = cwd / fname
        if fpath.exists():
            try:
                content = fpath.read_text("utf-8")
                if "uibridge" in content.lower():
                    artifacts.append(fpath)
            except Exception as e:
                logger.warning("Failed to read %s for artifact scan: %s", fpath, e)

    # .claude/skills/uibridge.md
    skill_file = cwd / ".claude" / "skills" / "uibridge.md"
    if skill_file.exists():
        artifacts.append(skill_file)

    return artifacts


def _scan_system_artifacts() -> list[Path]:
    """扫描 Python 环境中可编辑安装遗留的 uibridge 残留文件。

    仅当 uibridge 包已卸载但残留文件仍存在时才返回结果。
    如果 uibridge 仍可导入，则可编辑安装文件属于正常存在，不算残留。
    """
    from importlib.util import find_spec
    if find_spec("uibridge") is not None:
        return []

    artifacts = []

    try:
        import site
        site_packages = site.getsitepackages()
        for sp in site_packages:
            sp_path = Path(sp)
            if sp_path.exists():
                for f in sp_path.glob("__editable__.*uibridge*"):
                    artifacts.append(f)
                for f in sp_path.glob("__editable___*uibridge*"):
                    artifacts.append(f)
    except Exception:
        logger.warning("Failed to scan site-packages for editable install artifacts", exc_info=True)
        pass

    # Scripts 目录下的入口点
    try:
        scripts_dir = Path(sys.executable).parent / "Scripts"
        if scripts_dir.exists():
            for f in scripts_dir.glob("uibridge*"):
                artifacts.append(f)
    except Exception:
        logger.warning("Failed to scan Scripts directory for uibridge artifacts", exc_info=True)
        pass

    return artifacts


def main():
    cli()


if __name__ == "__main__":
    main()
