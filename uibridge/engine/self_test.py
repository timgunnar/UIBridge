"""自检引擎 — 生成脚本后立即执行验证。支持 pytest (Python) 和 mvn test (Java)。"""

import tempfile
import subprocess
import time
import os
from pathlib import Path
from dataclasses import dataclass


@dataclass
class SelfTestResult:
    status: str  # passed / failed
    confidence: float = 0.0
    stdout: str = ""
    stderr: str = ""
    duration_ms: int = 0
    fix_suggestion: str = ""
    language: str = "python"


class SelfTestRunner:
    """执行生成的测试脚本验证可执行性。支持 Python (pytest) 和 Java (mvn test)。"""

    def __init__(self, timeout: int = 60):
        self.timeout = timeout

    def run(self, code: str, test_name: str, language: str = "python",
            project_dir: str = "") -> SelfTestResult:
        """运行自检，根据语言选择执行器"""
        if language == "java":
            return self._run_java(code, test_name, project_dir)
        return self._run_python(code, test_name)

    def _run_python(self, code: str, test_name: str) -> SelfTestResult:
        start = time.time()
        tmp_file = Path(tempfile.gettempdir()) / f"uibridge_gen_{test_name}.py"
        tmp_file.write_text(code, encoding="utf-8")

        try:
            proc = subprocess.run(
                ["pytest", str(tmp_file), "-v", "--tb=short", "--no-header"],
                capture_output=True, text=True, timeout=self.timeout,
                encoding="utf-8", errors="replace",
            )
            stdout = proc.stdout
            stderr = proc.stderr
            passed = proc.returncode == 0
        except subprocess.TimeoutExpired:
            passed = False
            stdout = ""
            stderr = f"Test timed out after {self.timeout}s"
        except FileNotFoundError:
            passed = False
            stdout = ""
            stderr = "pytest not found. Install with: pip install pytest"

        elapsed = int((time.time() - start) * 1000)
        result = SelfTestResult(
            status="passed" if passed else "failed",
            confidence=0.95 if passed else 0.0,
            stdout=stdout,
            stderr=stderr,
            duration_ms=elapsed,
            language="python",
        )
        if not passed:
            result.fix_suggestion = self._analyze_failure_python(stdout, stderr)
        tmp_file.unlink(missing_ok=True)
        return result

    def _run_java(self, code: str, test_name: str, project_dir: str = "") -> SelfTestResult:
        """通过 mvn test 或 javac+java 执行 Java 测试"""
        start = time.time()

        if project_dir and Path(project_dir, "pom.xml").exists():
            # Maven 项目：写入 src/test/java 后使用 mvn test -Dtest=...
            return self._run_maven_test(code, test_name, project_dir, start)
        else:
            # 无 Maven 项目：写入临时目录，javac 编译后 java 执行
            return self._run_java_direct(code, test_name, start)

    def _run_maven_test(self, code: str, test_name: str,
                        project_dir: str, start: float) -> SelfTestResult:
        project_path = Path(project_dir)
        test_dir = project_path / "src" / "test" / "java"
        test_dir.mkdir(parents=True, exist_ok=True)

        test_file = test_dir / f"{test_name}.java"
        test_file.write_text(code, encoding="utf-8")

        try:
            proc = subprocess.run(
                ["mvn", "test", f"-Dtest={test_name}", "-q"],
                capture_output=True, text=True, timeout=self.timeout,
                cwd=str(project_path),
                encoding="utf-8", errors="replace",
            )
            passed = proc.returncode == 0
            stdout = proc.stdout
            stderr = proc.stderr
        except subprocess.TimeoutExpired:
            passed = False
            stdout = ""
            stderr = f"Maven test timed out after {self.timeout}s"
        except FileNotFoundError:
            passed = False
            stdout = ""
            stderr = "mvn not found. Install Maven or ensure it is on PATH."

        elapsed = int((time.time() - start) * 1000)
        result = SelfTestResult(
            status="passed" if passed else "failed",
            confidence=0.95 if passed else 0.0,
            stdout=stdout,
            stderr=stderr,
            duration_ms=elapsed,
            language="java",
        )
        if not passed:
            result.fix_suggestion = self._analyze_failure_java(stdout, stderr)
        test_file.unlink(missing_ok=True)
        return result

    def _run_java_direct(self, code: str, test_name: str, start: float) -> SelfTestResult:
        """使用 javac 编译 + java 运行 TestNG 测试（无需 Maven）"""
        tmp_dir = Path(tempfile.gettempdir()) / f"uibridge_java_{test_name}"
        tmp_dir.mkdir(parents=True, exist_ok=True)
        test_file = tmp_dir / f"{test_name}.java"
        test_file.write_text(code, encoding="utf-8")

        passed = False
        stdout = ""
        stderr = ""

        try:
            # 1. 编译
            compile_proc = subprocess.run(
                ["javac", str(test_file)],
                capture_output=True, text=True, timeout=30,
                encoding="utf-8", errors="replace",
            )
            if compile_proc.returncode != 0:
                stderr = f"Compilation failed:\n{compile_proc.stderr}"
            else:
                # 2. 执行：java -cp <tmp_dir> org.testng.TestNG -testclass <test_name>
                classpath = str(tmp_dir)
                run_proc = subprocess.run(
                    ["java", "-cp", classpath, "org.testng.TestNG", "-testclass", test_name],
                    capture_output=True, text=True, timeout=self.timeout,
                    encoding="utf-8", errors="replace",
                )
                stdout = run_proc.stdout
                if run_proc.returncode == 0:
                    passed = True
                else:
                    stderr = run_proc.stderr or run_proc.stdout
        except FileNotFoundError as e:
            missing = "javac" if "javac" in str(e) else "java" if "java" in str(e) else "TestNG"
            stderr = f"{missing} not found. Install JDK and TestNG JAR, or use mvn test path."
        except subprocess.TimeoutExpired:
            stderr = f"Test execution timed out ({self.timeout}s)."

        elapsed = int((time.time() - start) * 1000)
        result = SelfTestResult(
            status="passed" if passed else "failed",
            confidence=0.95 if passed else 0.0,
            stdout=stdout,
            stderr=stderr,
            duration_ms=elapsed,
            language="java",
        )
        if not passed:
            result.fix_suggestion = self._analyze_failure_java(stdout, stderr)

        import shutil
        shutil.rmtree(tmp_dir, ignore_errors=True)
        return result

    # ── 自动修复尝试 ────────────────────────────

    def fix_and_retry(self, code: str, test_name: str, error_text: str,
                      language: str = "python", project_dir: str = "",
                      max_retries: int = 3) -> dict:
        """根据错误信息尝试自动修复代码，最多重试 max_retries 次。

        返回: {"fixed_code": str, "passed": bool, "attempts": int, "fix_log": [str]}
        这是路线图 P1 "自检失败 LLM 自动修复闭环" 的确定性实现。
        """
        fixed_code = code
        fix_log = []
        for attempt in range(max_retries):
            new_code, applied = self._apply_fix_rules(
                fixed_code, error_text, language
            )
            if not applied:
                break  # 没有可应用的修复规则
            fixed_code = new_code
            fix_log.append(f"Attempt {attempt+1}: {applied}")
            result = self.run(fixed_code, test_name, language, project_dir)
            if result.status == "passed":
                return {"fixed_code": fixed_code, "passed": True,
                        "attempts": attempt + 1, "fix_log": fix_log}
            error_text = result.stderr + "\n" + result.stdout
        return {"fixed_code": fixed_code, "passed": False,
                "attempts": max_retries, "fix_log": fix_log}

    def _apply_fix_rules(self, code: str, error_text: str, language: str) -> tuple[str, str]:
        """应用一条修复规则。返回 (新代码, 修复描述) 或 (原代码, "")。"""
        import re
        combined = error_text

        # Rule 1: Missing imports (Python)
        if language == "python":
            if "ModuleNotFoundError" in combined or "No module named" in combined:
                mod = re.search(r"No module named '(\w+)'", combined)
                if mod:
                    module = mod.group(1)
                    fix_line = f"from {module} import {module.title()}"
                    if fix_line not in code:
                        return (fix_line + "\n" + code, f"added import for {module}")

            if "NameError" in combined:
                name = re.search(r"name '(\w+)' is not defined", combined)
                if name and name.group(1) == "pytest":
                    return (code.replace("pytest\n", "import pytest\n"),
                            "fixed pytest import")

        # Rule 2: Java compilation — missing imports
        if language == "java":
            if "cannot find symbol" in combined:
                sym_match = re.search(r"symbol:\s*(?:class|variable|method)\s+(\w+)", combined)
                if sym_match:
                    sym = sym_match.group(1)
                    # 常见 Selenium / TestNG import
                    known_imports = {
                        "WebDriver": "import org.openqa.selenium.WebDriver;",
                        "ChromeDriver": "import org.openqa.selenium.chrome.ChromeDriver;",
                        "FirefoxDriver": "import org.openqa.selenium.firefox.FirefoxDriver;",
                        "By": "import org.openqa.selenium.By;",
                        "WebElement": "import org.openqa.selenium.WebElement;",
                        "FindBy": "import org.openqa.selenium.support.FindBy;",
                        "PageFactory": "import org.openqa.selenium.support.PageFactory;",
                        "Test": "import org.junit.jupiter.api.Test;",
                        "BeforeEach": "import org.junit.jupiter.api.BeforeEach;",
                        "AfterEach": "import org.junit.jupiter.api.AfterEach;",
                        "BeforeMethod": "import org.testng.annotations.BeforeMethod;",
                        "AfterMethod": "import org.testng.annotations.AfterMethod;",
                        "Assert": "import org.testng.Assert;",
                        "assertThat": "import static org.assertj.core.api.Assertions.assertThat;",
                    }
                    if sym in known_imports:
                        pkg_line = code.split("\n")[0] if code.startswith("package") else ""
                        if pkg_line:
                            rest = code[len(pkg_line) + 1:]
                            return (pkg_line + "\n\n" + known_imports[sym] + "\n" + rest,
                                    f"added import {sym}")
                        return (known_imports[sym] + "\n" + code,
                                f"added import {sym}")

        # Rule 3: Java — missing package declaration
        if language == "java" and "does not exist" in combined.lower():
            pkg = re.search(r"package\s+(\S+)\s+does not exist", combined, re.IGNORECASE)
            if pkg:
                # Remove or fix the broken package declaration
                target = pkg.group(1)
                new_code = re.sub(r'^package\s+' + re.escape(target) + r'\s*;\s*\n',
                                  '', code, flags=re.MULTILINE)
                if new_code != code:
                    return (new_code, f"removed broken package {target}")

        # Rule 4: Python — bad indentation in class body
        if language == "python" and "IndentationError" in combined:
            lines = code.split("\n")
            fixed_lines = []
            for line in lines:
                if line.startswith("    ") or line.startswith("\t") or line == "":
                    fixed_lines.append(line)
                elif line.strip():
                    fixed_lines.append("    " + line)
                else:
                    fixed_lines.append(line)
            new_code = "\n".join(fixed_lines)
            if new_code != code:
                return (new_code, "fixed indentation")

        # Rule 5: Generic — try adding a standard test framework import
        if language == "python" and "pytest" not in code and "import pytest" not in code:
            return ("import pytest\n\n" + code, "added pytest import")

        return (code, "")

    # ── 失败分析 ────────────────────────────────

    def _analyze_failure_python(self, stdout: str, stderr: str) -> str:
        """解析 pytest 输出，提供针对性修复建议。

        从 traceback 中提取错误类型、文件名、行号和具体错误消息，
        给出可直接操作的修复方向。
        """
        import re
        error_text = stderr + "\n" + stdout
        suggestions = []

        # 提取具体错误类型和消息
        err_match = re.search(r'(?:E\s+)?(\w+(?:Error|Exception|Warning)):\s*(.+)', error_text)
        error_type = err_match.group(1) if err_match else ""
        error_msg = err_match.group(2).strip() if err_match else ""

        # 提取文件名和行号
        file_match = re.search(r'File "([^"]+)", line (\d+)', error_text)
        src_file = file_match.group(1) if file_match else ""
        src_line = file_match.group(2) if file_match else ""

        if error_type == "ModuleNotFoundError":
            module = error_msg.split("'")[1] if "'" in error_msg else error_msg
            suggestions.append(f"缺少模块 {module} — 检查该组件的 AW 文件是否存在，或 import 路径是否正确")

        elif error_type == "ImportError":
            suggestions.append(f"导入失败: {error_msg} — 检查 import 语句中的模块路径和类名")

        elif error_type == "NameError":
            name = error_msg.split("'")[1] if "'" in error_msg else error_msg
            suggestions.append(f"变量 '{name}' 未定义 — 检查 fixture 或页面对象名称是否与生成代码一致")

        elif error_type == "AttributeError":
            suggestions.append(f"属性错误: {error_msg} — 检查生成的 AW 方法调用是否正确，组件是否有此方法")

        elif error_type == "AssertionError":
            suggestions.append(f"断言失败 — 检查预期值是否与实际页面内容匹配")

        elif error_type == "TypeError":
            suggestions.append(f"类型错误: {error_msg} — 检查方法参数类型和数量是否匹配")

        elif error_type == "TimeoutError" or "Timeout" in error_text:
            suggestions.append("测试超时 — 检查页面加载时间、XPath 定位器是否有效")

        if src_file and src_line:
            suggestions.insert(0, f"错误位置: {src_file}:{src_line}")

        if not suggestions:
            suggestions.append("请审查生成的脚本和完整错误日志")

        return "; ".join(suggestions)

    def _analyze_failure_java(self, stdout: str, stderr: str) -> str:
        """解析 javac 编译错误，提供针对性修复建议。

        支持标准 javac 错误格式 (file:line: error: message) 和 Maven 输出。
        """
        import re
        error_text = stderr + "\n" + stdout
        suggestions = []

        # 解析 javac 行格式: path:line: error: message
        javac_pattern = re.findall(
            r'([^:\s]+\.java):(\d+):\s*(error|warning):\s*(.+)',
            error_text
        )
        for file_path, line_no, level, msg in javac_pattern:
            suggestions.append(f"{file_path}:{line_no}: {msg.strip()}")

        if not javac_pattern:
            # Fallback to keyword matching
            if "cannot find symbol" in error_text:
                sym_match = re.search(r"symbol:\s*(.+)", error_text)
                loc_match = re.search(r"location:\s*(.+)", error_text)
                if sym_match:
                    sym = sym_match.group(1).strip()
                    suggestions.append(f"找不到符号 {sym} — 检查 import 语句、类名拼写和包路径")
                else:
                    suggestions.append("找不到符号 — 检查 import 语句和类引用是否正确")

            if "package" in error_text.lower() and "does not exist" in error_text:
                pkg = re.search(r'package\s+(\S+)\s+does not exist', error_text)
                if pkg:
                    suggestions.append(f"包 {pkg.group(1)} 不存在 — 检查 package 声明或添加 Maven 依赖")
                else:
                    suggestions.append("包不存在 — 检查 package 声明或依赖配置")

            if "unmappable character" in error_text:
                suggestions.append("编码问题 — 确保源文件使用 UTF-8 编码，或使用 ASCII 兼容字符")

            if "incompatible types" in error_text:
                suggestions.append("类型不兼容 — 检查方法参数类型和返回值类型是否匹配")

            if "cannot override" in error_text:
                suggestions.append("方法覆盖错误 — 检查父类方法签名是否与子类一致")

            if "has protected access" in error_text or "has private access" in error_text:
                suggestions.append("访问权限错误 — 检查方法或字段的访问修饰符")

        if not suggestions:
            suggestions.append("检查生成的 Java 代码和完整编译错误信息")

        return "; ".join(suggestions[:5])  # 最多 5 条建议
