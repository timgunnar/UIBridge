#!/usr/bin/env python
"""项目健康检查脚本 — 验证 uibridge 项目基本状态"""

import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def run(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, cwd=str(PROJECT_ROOT), **kwargs)


def check_package_importable() -> bool:
    result = run([sys.executable, "-c", "import uibridge; print(uibridge.__version__)"])
    ok = result.returncode == 0
    print(f"  {'PASS' if ok else 'FAIL'}: uibridge importable")
    return ok


def check_tests_pass() -> bool:
    result = run([sys.executable, "-m", "pytest", "tests/", "-x", "--tb=short", "-q"])
    ok = result.returncode == 0
    print(f"  {'PASS' if ok else 'FAIL'}: tests pass ({'passed' if ok else 'failed'})")
    if not ok:
        print(f"    {result.stdout[-200:]}")
    return ok


def check_adapter_interfaces() -> bool:
    try:
        from uibridge.adapter.base import (
            ComponentResolver, LocatorStrategy, ActionRecognizer,
            CodeGenerator, DataFormatter,
        )
        ok = True
    except ImportError as e:
        ok = False
    print(f"  {'PASS' if ok else 'FAIL'}: adapter base interfaces")
    return ok


def check_adapter_registration() -> bool:
    import yaml
    ok = True
    for adapter_file in ["reference.py", "screenplay.py", "java_testng.py", "java_fluent.py"]:
        path = PROJECT_ROOT / "uibridge" / "adapter" / adapter_file
        ok = ok and path.exists()
    print(f"  {'PASS' if ok else 'FAIL'}: 4 adapters present")
    return ok


def main():
    print("uibridge project validation\n")
    results = [
        ("Package import", check_package_importable()),
        ("Adapter interfaces", check_adapter_interfaces()),
        ("Adapter files", check_adapter_registration()),
        ("Tests", check_tests_pass()),
    ]
    passed = sum(1 for _, ok in results if ok)
    total = len(results)
    print(f"\nResult: {passed}/{total} checks passed")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
