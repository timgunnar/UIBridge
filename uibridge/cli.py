"""CLI 入口 — uibridge 命令行工具"""

import sys
import json
from pathlib import Path

import click
import yaml
from playwright.sync_api import sync_playwright

from .pipeline import Pipeline
from .adapter.reference import (
    ReferenceComponentResolver,
    ReferenceLocatorStrategy,
    ReferenceActionRecognizer,
    ReferenceCodeGenerator,
    ReferenceDataFormatter,
)


# ═══════════════════════════════════════════════════════════════
# 适配器工厂
# ═══════════════════════════════════════════════════════════════

def load_adapter(adapter_config_path: str = None) -> tuple:
    """加载适配器配置，返回 5 个接口实例"""
    if adapter_config_path and Path(adapter_config_path).exists():
        config_path = Path(adapter_config_path)
        raw = config_path.read_text("utf-8")
        if config_path.suffix in (".yaml", ".yml"):
            config = yaml.safe_load(raw)
        else:
            config = json.loads(raw)
        adapters = config.get("adapter", {})
        components_config = adapters.get("components", {})
        if components_config:
            return _import_adapter_from_config(components_config)

    # 默认：参考实现
    return (
        ReferenceComponentResolver(),
        ReferenceLocatorStrategy(),
        ReferenceActionRecognizer(),
        ReferenceCodeGenerator(),
        ReferenceDataFormatter(),
    )


def _import_adapter_from_config(components_config: dict) -> tuple:
    import importlib

    def load(cls_path: str):
        module_path, class_name = cls_path.rsplit(".", 1)
        module = importlib.import_module(module_path)
        return getattr(module, class_name)()

    return (
        load(components_config.get("resolver", "uibridge.adapter.reference.ReferenceComponentResolver")),
        load(components_config.get("locator", "uibridge.adapter.reference.ReferenceLocatorStrategy")),
        load(components_config.get("recognizer", "uibridge.adapter.reference.ReferenceActionRecognizer")),
        load(components_config.get("generator", "uibridge.adapter.reference.ReferenceCodeGenerator")),
        load(components_config.get("data_formatter", "uibridge.adapter.reference.ReferenceDataFormatter")),
    )


# ═══════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════

@click.group()
@click.version_option(version="0.2.0")
def cli():
    """UIBridge — UI自动化测试框架知识翻译层"""


@cli.command()
@click.option("--url", default="about:blank", help="起始 URL")
@click.option("--output", "-o", default="recording.json", help="录制输出文件")
@click.option("--headed/--headless", default=True, help="是否显示浏览器窗口")
@click.option("--adapter-config", default=None, help="适配器配置文件路径")
def record(url: str, output: str, headed: bool, adapter_config: str):
    """录制浏览器操作，输出标准化录制文件"""
    resolver, locator, recognizer, code_gen, data_fmt = load_adapter(adapter_config)

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=not headed)
        context = browser.new_context(viewport={"width": 1280, "height": 800})
        page = context.new_page()
        page.goto(url)

        pipeline = Pipeline(resolver, locator, recognizer, code_gen, data_fmt)
        session = pipeline.record(page)

        click.echo("=" * 60)
        click.echo("[REC] 录制中... 在浏览器中操作，完成后按 Enter 结束")
        click.echo("=" * 60)
        input()

        recording = session.to_raw_recording()
        output_path = Path(output)
        output_path.write_text(
            json.dumps(recording.to_dict(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        click.echo(f"\n[OK] 录制完成: {len(recording.steps)} 个步骤 -> {output_path}")

        browser.close()


@cli.command()
@click.option("--input", "-i", "input_file", default="recording.json", help="录制文件")
@click.option("--output-dir", "-o", default="generated", help="生成代码输出目录")
@click.option("--adapter-config", default=None, help="适配器配置文件路径")
def generate(input_file: str, output_dir: str, adapter_config: str):
    """从录制文件生成测试脚本"""
    resolver, locator, recognizer, code_gen, data_fmt = load_adapter(adapter_config)

    # 读取录制
    from .engine.ir.raw_recording import RawRecording
    data = json.loads(Path(input_file).read_text("utf-8"))
    recording = RawRecording.from_dict(data)

    pipeline = Pipeline(resolver, locator, recognizer, code_gen, data_fmt)

    # 分析
    semantic = pipeline.analyze(recording)
    click.echo(f"[ANALYZE] 场景分析: {len(semantic.scenarios)} 个场景")

    # 框架映射
    call_seq = pipeline.map_to_framework(semantic)
    click.echo(f"[MAP] 框架映射: {len(call_seq.test_cases)} 个测试用例")

    # 生成 + 自检
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    results = pipeline.generate_and_verify(call_seq, recording)

    # 检测语言决定文件扩展名
    ext = ".java" if "java" in str(type(pipeline.code_generator)).lower() else ".py"

    passed = 0
    for result in results:
        test_file = out_dir / f"{result['test_name']}{ext}"
        test_file.write_text(result["code"], encoding="utf-8")

        if result["data_def"]:
            data_file = out_dir / result["data_def"].file_path
            data_file.parent.mkdir(parents=True, exist_ok=True)
            data_file.write_text(result["data_code"], encoding="utf-8")

        status_icon = "[OK]" if result["verify"].status == "passed" else "[WARN]"
        click.echo(f"  {status_icon} {result['test_name']} ({result['verify'].status})")
        if result["verify"].status != "passed":
            click.echo(f"     错误: {result['verify'].stderr[:200]}")
            passed += 0
        else:
            passed += 1

    click.echo(f"\n[DONE] 生成完成: {passed}/{len(results)} 通过自检 → {out_dir}")


@cli.command()
@click.option("--url", required=True, help="待分析的页面 URL")
@click.option("--adapter-config", default=None, help="适配器配置文件路径")
def analyze(url: str, adapter_config: str):
    """分析页面，发现组件并输出注册表"""
    resolver, locator, recognizer, code_gen, data_fmt = load_adapter(adapter_config)

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(url)
        page.wait_for_load_state("networkidle")

        pipeline = Pipeline(resolver, locator, recognizer, code_gen, data_fmt)
        components = pipeline.discover_components(page)

        click.echo(f"\n页面: {url}")
        click.echo(f"发现 {len(components)} 个组件:\n")
        for comp in components:
            click.echo(f"  [{comp['type']}] {comp['name']}")
            click.echo(f"    XPath: {comp['xpath']}")
            click.echo(f"    ARIA:  {comp['aria_role']}")
            if comp.get("inputs"):
                click.echo(f"    Inputs: {len(comp['inputs'])}")
                for inp in comp["inputs"][:5]:
                    click.echo(f"      - {inp.get('name', '?')} ({inp.get('type', 'text')})")
            click.echo()

        browser.close()


@cli.command()
@click.option("--input", "-i", "input_file", default="recording.json", help="录制文件")
@click.option("--adapter-config", default=None, help="适配器配置文件路径")
def diff(input_file: str, adapter_config: str):
    """分析录制快照差异，生成断言候选"""
    resolver, locator, recognizer, code_gen, data_fmt = load_adapter(adapter_config)

    from .engine.ir.raw_recording import RawRecording
    data = json.loads(Path(input_file).read_text("utf-8"))
    recording = RawRecording.from_dict(data)

    pipeline = Pipeline(resolver, locator, recognizer, code_gen, data_fmt)
    candidates = pipeline.diff_snapshots(recording)

    click.echo(f"\n断言候选 ({len(candidates)} 个):\n")
    for i, c in enumerate(candidates, 1):
        click.echo(f"  [{i}] {c}")


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

    使用 pip uninstall uibridge 卸载 Python 包本身。
    """
    cwd = Path.cwd()
    artifacts = _scan_artifacts(cwd)

    if not artifacts:
        click.echo("[OK] 未发现 uibridge 残留文件。")
        click.echo("\n卸载 Python 包: pip uninstall uibridge")
        return

    # 报告
    click.echo(f"\n发现 {len(artifacts)} 项 uibridge 残留:\n")
    for item in artifacts:
        click.echo(f"  {item}")

    total_size = sum(
        sum(f.stat().st_size for f in p.rglob("*") if f.is_file())
        if p.is_dir() else p.stat().st_size
        for p in artifacts
    )
    click.echo(f"\n总计: ~{total_size / 1024:.1f} KB")

    if dry_run:
        click.echo("\n[Dry-run] 未执行删除。使用 --yes 确认清理。")
        return

    if not yes:
        click.confirm("\n确认删除以上所有文件?", abort=True)

    # 执行清理
    import shutil
    removed = 0
    for item in artifacts:
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
            except Exception:
                pass

    # .claude/skills/uibridge.md
    skill_file = cwd / ".claude" / "skills" / "uibridge.md"
    if skill_file.exists():
        artifacts.append(skill_file)

    return artifacts


def main():
    cli()


if __name__ == "__main__":
    main()
