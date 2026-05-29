"""UIRelevanceFilter — 多信号 UI 文件相关性检测。

组合 scanner primitives 的五维信号独立判定文件是否属于 UI 层。
单信号可能是巧合（DTO 碰巧在 pages/ 目录下），多信号同时命中才是真 UI 文件。

原则：
- scanner/ 内部实现，不依赖 kb/
- 每个文件读一次内容，5 个信号并行检查
- 至少 2 个独立信号命中才认定为 UI 相关
"""

import enum
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Union

from .primitives.file_scan import FileScanner, FileClass
from .primitives.annotations import AnnotationExtractor
from .primitives.locators import LocatorExtractor
from .primitives.inheritance import InheritanceAnalyzer

logger = logging.getLogger(__name__)

# ── 命名信号常量 ──

_UI_CLASS_SUFFIXES = frozenset({
    "page", "screen", "view", "aw", "component", "widget", "test", "spec"
})
_UI_CLASS_PREFIXES = frozenset({"test"})

# 补充注解：AnnotationExtractor._classify 归入 "custom" 类别但仍是强 UI 信号
_SUPPLEMENTARY_ANNOTATIONS_RE = __import__("re").compile(
    r'@(Page|Component|Step|PageObject|Screen|Widget)\b', __import__("re").IGNORECASE
)

# UI 基类关键词
_UI_BASE_KEYWORDS = frozenset({
    "page", "component", "aw", "widget", "screen",
    "basepage", "basecomponent", "pageobject",
})

_SIGNAL_COUNT = 5


# ── 枚举和数据类型 ──

class UISignal(enum.Enum):
    """UI 相关性的独立信号维度。"""
    PATH = "path"              # FileScanner.classify() → AW/PAGE/TEST
    INHERITANCE = "inheritance" # extends/implements UI 基类
    ANNOTATION = "annotation"   # @FindBy / @Test / @Component 等
    LOCATOR = "locator"         # 使用了定位器 API
    NAMING = "naming"           # 类名匹配 UI 命名模式


@dataclass
class UIRelevanceScore:
    """单个文件的 UI 相关性评分结果。

    Attributes:
        path: 文件路径
        relevance: "HIGH" | "MEDIUM" | "LOW" | "NONE"
        signals: 命中的信号列表
        confidence: len(signals) / 5
        details: 每个信号的详情字典
    """
    path: Path
    relevance: str
    signals: list  # list[UISignal]
    confidence: float
    details: dict  # {signal_name: detail}

    def __repr__(self) -> str:
        return (f"UIRelevanceScore({self.path.name!r}, {self.relevance}, "
                f"signals={len(self.signals)}, conf={self.confidence:.2f})")


# ── 过滤器类 ──

class UIRelevanceFilter:
    """多信号 UI 文件相关性过滤器。

    对每个源文件在 5 个独立维度上打分：
    PATH（目录位置）、NAMING（命名约定）、INHERITANCE（UI 基类继承）、
    ANNOTATION（UI 注解）、LOCATOR（定位器使用）。

    低于 2 个信号的文件视为噪声，排除。

    Usage:
        f = UIRelevanceFilter("/path/to/project")
        ui_files = f.filter(all_files, min_signals=2)
        for score in f.score_files(all_files):
            print(score.relevance, score.path.name)
    """

    def __init__(self, project_root: Union[str, Path]):
        self.project_root = Path(project_root)
        self._file_scanner = FileScanner(str(project_root))
        self._annotation_extractor = AnnotationExtractor(use_ast=False)
        self._locator_extractor = LocatorExtractor()
        self._inheritance_analyzer = InheritanceAnalyzer(use_ast=False)

    # ── 信号检查器（各返回 (命中bool, 详情)） ──

    def _check_path_signal(self, path: Path) -> tuple[bool, str]:
        """PATH 信号：FileScanner.classify() 判定为 AW/PAGE/TEST。"""
        fc = self._file_scanner.classify(path)
        hit = fc in (FileClass.AW, FileClass.PAGE, FileClass.TEST)
        return hit, fc

    def _check_naming_signal(self, path: Path) -> tuple[bool, dict]:
        """NAMING 信号：文件名以 UI 后缀/前缀匹配。"""
        stem = path.stem.lower()
        matched_suffixes = [
            s for s in _UI_CLASS_SUFFIXES
            if stem.endswith(s) and len(stem) > len(s)
        ]
        matched_prefixes = [
            p for p in _UI_CLASS_PREFIXES
            if stem.startswith(p) and len(stem) > len(p)
        ]
        match_info = {
            "stem": path.stem,
            "suffixes": matched_suffixes,
            "prefixes": matched_prefixes,
        }
        hit = bool(matched_suffixes or matched_prefixes)
        return hit, match_info

    def _check_inheritance_signal(self, path: Path, content: str) -> tuple[bool, list[str]]:
        """INHERITANCE 信号：extends/implements UI 基类。

        用 InheritanceAnalyzer._analyze_with_regex 提取父类名，
        再检查是否包含 UI 关键词。
        """
        node = self._inheritance_analyzer._analyze_with_regex(
            str(path), content, path.suffix
        )
        if node is None:
            return False, []

        all_bases = node.extends_list + node.implements_list
        matched = [
            base for base in all_bases
            if any(kw in base.lower() for kw in _UI_BASE_KEYWORDS)
        ]
        return bool(matched), matched

    def _check_annotation_signal(self, path: Path, content: str) -> tuple[bool, list[str]]:
        """ANNOTATION 信号：UI 相关注解或装饰器。

        两步检查：
        1. AnnotationExtractor 归类为 test/locator/framework 的注解
        2. 补充正则：@Page / @Component / @Step 等被归入 custom 但仍属 UI 信号
        """
        annotations = self._annotation_extractor._analyze_with_regex(
            str(path), content, path.suffix
        )

        matched = []
        for ann in annotations:
            if ann.category in ("test", "locator", "framework"):
                matched.append(ann.name)

        # 补充：annotation extractor 未识别为 UI 相关但实际是强信号的注解
        for m in _SUPPLEMENTARY_ANNOTATIONS_RE.finditer(content):
            name = m.group(1)
            if name not in matched:
                matched.append(name)

        return bool(matched), matched

    def _check_locator_signal(self, path: Path, content: str) -> tuple[bool, list[str]]:
        """LOCATOR 信号：使用了元素定位器 API。

        用 LocatorExtractor 的内部方法按语言分派。
        """
        if path.suffix == ".java":
            locators = self._locator_extractor._extract_java_locators(
                str(path), content
            )
        elif path.suffix == ".py":
            locators = self._locator_extractor._extract_python_locators(
                str(path), content
            )
        else:
            return False, []

        strategies = list(dict.fromkeys(loc.strategy for loc in locators))
        return bool(locators), strategies

    # ── 核心方法 ──

    def score_file(self, path: Path) -> UIRelevanceScore:
        """对单个文件进行多维度 UI 相关性评分。

        读一次文件内容，跑全部 5 个信号检查，返回完整评分结果。
        """
        signals: list = []
        details: dict = {}

        # PATH 信号（无需内容）
        path_hit, path_detail = self._check_path_signal(path)
        if path_hit:
            signals.append(UISignal.PATH)
        details["path"] = path_detail

        # NAMING 信号（无需内容）
        naming_hit, naming_detail = self._check_naming_signal(path)
        if naming_hit:
            signals.append(UISignal.NAMING)
        details["naming"] = naming_detail

        # 内容依赖的信号：读一次文件
        content = None
        try:
            content = path.read_text("utf-8", errors="replace")
        except Exception:
            logger.debug("Cannot read %s, skipping content-based signals", path)

        if content is not None:
            inh_hit, inh_detail = self._check_inheritance_signal(path, content)
            if inh_hit:
                signals.append(UISignal.INHERITANCE)
            details["inheritance"] = inh_detail

            ann_hit, ann_detail = self._check_annotation_signal(path, content)
            if ann_hit:
                signals.append(UISignal.ANNOTATION)
            details["annotation"] = ann_detail

            loc_hit, loc_detail = self._check_locator_signal(path, content)
            if loc_hit:
                signals.append(UISignal.LOCATOR)
            details["locator"] = loc_detail
        else:
            details["inheritance"] = []
            details["annotation"] = []
            details["locator"] = []

        # 计算相关性等级
        count = len(signals)
        if count == 0:
            relevance = "NONE"
        elif count == 1:
            relevance = "LOW"
        elif count == 2:
            relevance = "MEDIUM"
        else:
            relevance = "HIGH"

        confidence = count / _SIGNAL_COUNT

        return UIRelevanceScore(
            path=path,
            relevance=relevance,
            signals=signals,
            confidence=confidence,
            details=details,
        )

    def score_files(self, files: list[Path]) -> list[UIRelevanceScore]:
        """批量评分，按置信度降序排列。"""
        scores = [self.score_file(f) for f in files]
        scores.sort(key=lambda s: (-s.confidence, s.path.name))
        return scores

    def filter(self, files: list[Path], min_signals: int = 2) -> list[Path]:
        """过滤：只保留信号数 >= min_signals 的文件。"""
        result = []
        for f in files:
            score = self.score_file(f)
            if len(score.signals) >= min_signals:
                result.append(f)
        return result
