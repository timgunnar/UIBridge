"""ProfileManager — 画像生命周期管理"""

import re
from pathlib import Path
from typing import Optional
import logging

logger = logging.getLogger(__name__)

from .profile import FrameworkProfile, ProfileField
from .profile_store import ProfileStore
from .kb.extractor import KBExtractor
from .kb.source_detection import SourceDetector


class ProfileManager:
    """管理画像的完整生命周期：播种 → 确认 → 更新 → 文档增强。

    画像独立于 KB，是 uibridge 运行时的唯一配置源。

    可通过 _extractor / _auto_detect_dirs 注入依赖以消除与 KB 模块的
    循环引用。不注入时 seed_phase1() 和 reprofile() 内部懒加载 KB。
    """

    def __init__(self, project_root: str = ".", *,
                 _extractor=None,
                 _auto_detect_dirs=None):
        self.project_root = Path(project_root)
        self.store = ProfileStore(project_root)
        self._extractor = _extractor
        self._auto_detect_dirs = _auto_detect_dirs

    # ══════════════════════════════════════════════════════════
    # Seed
    # ══════════════════════════════════════════════════════════

    def seed_phase1(self, source_dirs: dict[str, str] | None = None,
                    force_reprofile: bool = False) -> FrameworkProfile:
        """Phase 1: 生成或加载项目画像。

        Args:
            source_dirs: {"pages": "src/...", "tests": "src/...", ...}
                         不传则自动检测。
            force_reprofile: 即使已有画像也强制重新生成。

        Returns:
            FrameworkProfile（新生成或已缓存的）。
        """
        if not force_reprofile:
            existing = self.store.load()
            if existing is not None:
                return existing

        if source_dirs is None:
            if self._auto_detect_dirs:
                source_dirs = self._auto_detect_dirs()
            else:
                source_dirs = SourceDetector(str(self.project_root)).detect()

        if self._extractor:
            extractor = self._extractor
        else:
            extractor = KBExtractor(str(self.project_root))

        profile = extractor.profile_project(source_dirs)
        self.store.save(profile)
        return profile

    # ══════════════════════════════════════════════════════════
    # Query
    # ══════════════════════════════════════════════════════════

    def get_profile(self) -> Optional[FrameworkProfile]:
        """获取当前项目画像，不存在则返回 None。"""
        return self.store.load()

    # ══════════════════════════════════════════════════════════
    # Evolve
    # ══════════════════════════════════════════════════════════

    def reprofile(self, overrides: Optional[dict] = None) -> FrameworkProfile:
        """强制重新画像，可选合并覆盖字段。

        Args:
            overrides: {"base_classes": {"MyBase": "container"}, ...}

        Returns:
            更新后的 FrameworkProfile。
        """
        if self._auto_detect_dirs:
            source_dirs = self._auto_detect_dirs()
        else:
            source_dirs = SourceDetector(str(self.project_root)).detect()

        if self._extractor:
            extractor = self._extractor
        else:
            extractor = KBExtractor(str(self.project_root))

        profile = extractor.profile_project(source_dirs)

        if overrides:
            for field_name, value in overrides.items():
                if hasattr(profile, field_name):
                    pf = getattr(profile, field_name)
                    if isinstance(pf, ProfileField):
                        if isinstance(pf.value, dict) and isinstance(value, dict):
                            pf.value.update(value)
                        elif isinstance(pf.value, list) and isinstance(value, list):
                            pf.value = list(set(pf.value + value))
                        else:
                            pf.value = value
                        pf.source = "human_dialogue"
                        pf.confidence = 0.95
                    else:
                        setattr(profile, field_name, value)
            profile.updated_by = "reprofile_with_overrides"

        self.store.save(profile)
        return profile

    def update_profile(self, field: str, value,
                       source: str = "human_dialogue") -> FrameworkProfile:
        """NL 对话后更新单个画像字段，提升置信度。

        Args:
            field: ProfileField 属性名
            value: 新值（dict → merge，其它 → replace）
            source: "human_dialogue" | "document" | "runtime"

        Returns:
            更新后的 FrameworkProfile。

        Raises:
            ValueError: 字段不存在或不是 ProfileField 类型。
        """
        profile = self.store.load()
        if profile is None:
            profile = self.seed_phase1()

        if not hasattr(profile, field):
            raise ValueError(f"FrameworkProfile has no field '{field}'")

        pf = getattr(profile, field)
        if not isinstance(pf, ProfileField):
            raise ValueError(f"'{field}' is not a ProfileField (got {type(pf).__name__})")

        if isinstance(pf.value, dict) and isinstance(value, dict):
            pf.value.update(value)
        else:
            pf.value = value

        pf.source = source
        pf.confidence = max(pf.confidence, 0.90 if source == "human_dialogue" else 0.85)
        profile.updated_by = source
        profile.version += 1

        self.store.save(profile)
        return profile

    def confirm_profile(self, threshold: float = 0.7) -> dict:
        """Phase 1 后调用，返回低置信度字段列表供用户确认。

        Returns:
            {"status": "needs_confirmation" | "all_confirmed" | "no_profile",
             "low_confidence_fields": [...], "profile_confidence": 0.55}
        """
        profile = self.store.load()
        if profile is None:
            return {"status": "no_profile",
                    "message": "画像不存在。请先运行 seed_phase1() 生成画像。"}

        low_fields = []
        profile_field_names = [
            "ui_packages", "base_classes", "annotations",
            "locator_priorities", "naming_conventions", "source_dirs",
            "layer_structure", "reference_directories",
            "output_config", "component_monitoring",
        ]

        for name in profile_field_names:
            pf = getattr(profile, name, None)
            if not isinstance(pf, ProfileField):
                continue
            if pf.confidence < threshold:
                low_fields.append({
                    "field": name,
                    "confidence": pf.confidence,
                    "value": pf.value,
                    "source": pf.source,
                    "description": pf.description,
                })

        if not low_fields:
            return {"status": "all_confirmed",
                    "profile_confidence": profile.profiling_confidence}

        return {
            "status": "needs_confirmation",
            "low_confidence_fields": low_fields,
            "profile_confidence": profile.profiling_confidence,
        }

    def enhance_profile_from_document(self, text: str) -> FrameworkProfile:
        """从文档提取画像信息并合并到现有画像。

        解析：基类声明、定位器优先级、命名约定、源码目录。

        Args:
            text: 文档文本内容

        Returns:
            合并更新后的 FrameworkProfile。
        """
        profile = self.store.load()
        if profile is None:
            profile = self.seed_phase1()

        base_classes = self._extract_base_classes(text)
        if base_classes:
            if isinstance(profile.base_classes.value, dict):
                profile.base_classes.value.update(base_classes)
            else:
                profile.base_classes.value = base_classes
            profile.base_classes.source = "document"
            profile.base_classes.confidence = max(profile.base_classes.confidence, 0.85)

        locators = self._extract_locator_priorities(text)
        if locators:
            profile.locator_priorities.value = locators
            profile.locator_priorities.source = "document"
            profile.locator_priorities.confidence = max(profile.locator_priorities.confidence, 0.85)

        naming = self._extract_naming(text)
        if naming:
            if isinstance(profile.naming_conventions.value, dict):
                profile.naming_conventions.value.update(naming)
            else:
                profile.naming_conventions.value = naming
            profile.naming_conventions.source = "document"
            profile.naming_conventions.confidence = max(profile.naming_conventions.confidence, 0.85)

        src_dirs = self._extract_source_dirs(text)
        if src_dirs:
            if isinstance(profile.source_dirs.value, dict):
                profile.source_dirs.value.update(src_dirs)
            else:
                profile.source_dirs.value = src_dirs
            profile.source_dirs.source = "document"
            profile.source_dirs.confidence = max(profile.source_dirs.confidence, 0.85)

        profile.updated_by = "document"
        profile.version += 1
        self.store.save(profile)
        return profile

    # ── Helpers ────────────────────────────────────────

    @staticmethod
    def _extract_base_classes(text: str) -> dict[str, str]:
        result = {}
        patterns = [
            re.compile(r'基类[是为]?\s*[：:]\s*(\w+)', re.IGNORECASE),
            re.compile(r'(?:extends|继承)\s+(\w+)', re.IGNORECASE),
            re.compile(r'(\w+(?:Base|Abstract)\w*)\s*[→→]\s*(\w+)', re.IGNORECASE),
            re.compile(r'(\w+)\s*(?:是|为|作为)\s*(?:所有)?\s*(\w+)\s*(?:的)?\s*基类', re.IGNORECASE),
        ]
        for pat in patterns:
            for m in pat.finditer(text):
                groups = m.groups()
                if len(groups) == 2:
                    result[groups[0]] = groups[1]
                elif len(groups) == 1:
                    result[groups[0]] = "base"
        return result

    @staticmethod
    def _extract_locator_priorities(text: str) -> list[str]:
        patterns = [
            re.compile(r'(?:定位|locator)\s*优先级\s*[：:]\s*(.+)', re.IGNORECASE),
            re.compile(r'优先\s*(?:使用|用)\s*(.+?)(?:定位|作为|$)', re.IGNORECASE),
            re.compile(r'locator\s*(?:priority|order)\s*[：:]\s*(.+)', re.IGNORECASE),
        ]
        for pat in patterns:
            m = pat.search(text)
            if m:
                items = re.split(r'[>→,，\s]+', m.group(1))
                result = [i.strip() for i in items if i.strip()]
                if result:
                    return result
        return []

    @staticmethod
    def _extract_naming(text: str) -> dict[str, str]:
        result = {}
        patterns = [
            re.compile(r'(?:类名|class)\s*(?:以|用)\s*(\w+)\s*(?:结尾|后缀|ending)', re.IGNORECASE),
            re.compile(r'(?:命名|naming)\s*(?:规范|约定|convention)\s*[：:]\s*(.+)', re.IGNORECASE),
            re.compile(r'(\w+)\s*(?:后缀|suffix)\s*(?:表示|代表)\s*(\w+)', re.IGNORECASE),
        ]
        for pat in patterns:
            for m in pat.finditer(text):
                groups = m.groups()
                if len(groups) == 2:
                    result[groups[0]] = groups[1]
                elif len(groups) == 1:
                    result["naming_rule"] = groups[0]
        return result

    @staticmethod
    def _extract_source_dirs(text: str) -> dict[str, str]:
        result = {}
        patterns = [
            re.compile(r'(?:组件|component)\s*(?:目录|代码|路径)\s*(?:在|位于)\s*[：:]?\s*([\w/\\.-]+)', re.IGNORECASE),
            re.compile(r'(?:页面|page)\s*(?:目录|代码|路径)\s*(?:在|位于)\s*[：:]?\s*([\w/\\.-]+)', re.IGNORECASE),
            re.compile(r'(?:源码|source)\s*(?:目录|路径)\s*[：:]\s*([\w/\\.-]+)', re.IGNORECASE),
        ]
        labels = ["components", "pages", "source"]
        for i, pat in enumerate(patterns):
            m = pat.search(text)
            if m:
                result[labels[i]] = m.group(1)
        return result
