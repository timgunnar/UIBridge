"""KBExtractor — composition-based knowledge extractor."""

import logging
from pathlib import Path

from ._base import safe_relative_to
from ..python_extractor import PythonExtractor
from ..java_extractor import JavaExtractor
from ..profile_extractor import ProfileExtractor
from ..convention_miner import ConventionMiner
from ..aggregation_extractor import AggregationExtractor
from ..document_ingestor import DocumentIngestor
from ..item import KBItem

logger = logging.getLogger(__name__)


class KBExtractor:
    """Extracts framework knowledge from source code, runtime traces, and NL documents."""

    def __init__(self, project_root: str = "."):
        self.project_root = Path(project_root)
        self._python = PythonExtractor(project_root)
        self._java = JavaExtractor(project_root)
        self._profile = ProfileExtractor(project_root)
        self._conventions = ConventionMiner(project_root)
        self._aggregation = AggregationExtractor(
            project_root, java_extractor=self._java, convention_miner=self._conventions
        )
        self._documents = DocumentIngestor()

    # ── _java_available property (backward compat: tests set this directly) ──

    @property
    def _java_available(self):
        return self._java._java_available

    @_java_available.setter
    def _java_available(self, value):
        self._java._java_available = value

    # ── Public API ──

    # From PythonExtractor (legacy wrappers)
    def extract_from_component_aw(self, filepath: str) -> list[KBItem]:
        return self._python._legacy_extract_from_component_aw(filepath)

    def extract_from_page_file(self, filepath: str) -> list[KBItem]:
        return self._python._legacy_extract_from_page_file(filepath)

    def extract_from_test_script(self, filepath: str) -> list[KBItem]:
        return self._python._legacy_extract_from_test_script(filepath)

    # From JavaExtractor (legacy wrappers)
    def extract_from_java_file(self, filepath: str) -> list[KBItem]:
        return self._java._legacy_extract_from_java_file(filepath)

    def extract_from_java_test(self, filepath: str) -> list[KBItem]:
        return self._java._legacy_extract_from_java_test(filepath)

    # Runtime analysis (stays on coordinator)
    def extract_from_runtime_trace(self, component_type: str,
                                   method_traces: list[dict],
                                   page_url: str) -> list[KBItem]:
        """From runtime execution traces → validated XPath, locator strategies."""
        from ..item import Confidence, KnowledgeSource
        items = []
        for trace in method_traces:
            method_name = trace.get("method", "unknown")
            executed_ops = trace.get("executed_ops", [])
            xpaths = [op.get("locator", "") for op in executed_ops
                      if op.get("locator", "").startswith("xpath=")]
            items.append(KBItem(
                id=f"rt_{component_type}_{method_name}",
                category="components",
                key=f"runtime.{component_type}.{method_name}",
                value={
                    "component_type": component_type,
                    "method": method_name,
                    "validated_xpaths": xpaths,
                    "page_url": page_url,
                    "executed_ops": executed_ops,
                },
                confidence=Confidence(score=0.85, source=KnowledgeSource.RUNTIME_ANALYSIS),
                description=f"Runtime trace: {component_type}.{method_name}() → {len(xpaths)} XPath(s) validated",
                tags=[component_type, method_name, "runtime"],
            ))
        return items

    # From ProfileExtractor
    def profile_project(self, source_dirs: dict[str, str]):
        return self._profile.profile_project(source_dirs)

    # From AggregationExtractor
    def extract_aggregated(self, profile):
        return self._aggregation.extract_aggregated(profile)

    # From DocumentIngestor
    def extract_from_design_doc(self, text: str, source_name: str = "design_doc") -> list[KBItem]:
        return self._documents.extract_from_design_doc(text, source_name)

    def inject_convention(self, key: str, value: dict, description: str, source: str = "human") -> KBItem:
        return self._documents.inject_convention(key, value, description, source)

    # ── Internal delegation: Python extractor (called by KBManager, tests, etc.) ──

    def _legacy_extract_from_component_aw(self, filepath: str) -> list[KBItem]:
        return self._python._legacy_extract_from_component_aw(filepath)

    def _legacy_extract_from_page_file(self, filepath: str) -> list[KBItem]:
        return self._python._legacy_extract_from_page_file(filepath)

    def _legacy_extract_from_test_script(self, filepath: str) -> list[KBItem]:
        return self._python._legacy_extract_from_test_script(filepath)

    def _parse(self, path):
        return self._python._parse(path)

    def _find_class_name(self, tree):
        return self._python._find_class_name(tree)

    def _extract_xpath_patterns(self, tree):
        return self._python._extract_xpath_patterns(tree)

    def _extract_methods(self, tree):
        return self._python._extract_methods(tree)

    def _extract_feature_points(self, tree):
        return self._python._extract_feature_points(tree)

    def _extract_imports(self, tree):
        return self._python._extract_imports(tree)

    def _extract_fixture_names(self, tree):
        return self._python._extract_fixture_names(tree)

    def _detect_assertion_style(self, tree):
        return self._python._detect_assertion_style(tree)

    # ── Internal delegation: Java extractor ──

    def _legacy_extract_from_java_file(self, filepath: str) -> list[KBItem]:
        return self._java._legacy_extract_from_java_file(filepath)

    def _legacy_extract_from_java_test(self, filepath: str) -> list[KBItem]:
        return self._java._legacy_extract_from_java_test(filepath)

    def _check_javalang(self) -> bool:
        return self._java._check_javalang()

    def _parse_java(self, path):
        return self._java._parse_java(path)

    @staticmethod
    def _parse_java_regex(source: str):
        return JavaExtractor._parse_java_regex(source)

    def _find_java_class_name(self, tree):
        return self._java._find_java_class_name(tree)

    def _extract_java_base_class(self, tree):
        return self._java._extract_java_base_class(tree)

    def _extract_java_implements(self, tree):
        return self._java._extract_java_implements(tree)

    def _extract_java_package(self, tree):
        return self._java._extract_java_package(tree)

    def _extract_java_methods(self, tree):
        return self._java._extract_java_methods(tree)

    def _extract_java_annotations(self, tree):
        return self._java._extract_java_annotations(tree)

    def _extract_java_imports(self, tree):
        return self._java._extract_java_imports(tree)

    def _extract_java_locators(self, path, tree):
        return self._java._extract_java_locators(path, tree)

    @staticmethod
    def _parse_locator_annotation(raw_text: str):
        return JavaExtractor._parse_locator_annotation(raw_text)

    @staticmethod
    def _parse_locator_annotation_node(node):
        return JavaExtractor._parse_locator_annotation_node(node)

    @staticmethod
    def _is_tree_from_regex(tree):
        return JavaExtractor._is_tree_from_regex(tree)

    @classmethod
    def _infer_component_type(cls, class_name, base_class, implements, annotations):
        return JavaExtractor._infer_component_type(class_name, base_class, implements, annotations)

    @staticmethod
    def _compute_java_confidence(has_annotations, has_locators, has_base_class,
                                 has_implements, is_regex_fallback, has_only_class_name):
        return JavaExtractor._compute_java_confidence(
            has_annotations, has_locators, has_base_class,
            has_implements, is_regex_fallback, has_only_class_name)

    @staticmethod
    def _extract_java_naming_signature(class_name, methods):
        return JavaExtractor._extract_java_naming_signature(class_name, methods)

    # ── Internal delegation: Profile extractor ──

    def _profile_build_file(self):
        return self._profile._profile_build_file()

    def _profile_single_java(self, filepath):
        return self._profile._profile_single_java(filepath)

    def _profile_single_python(self, filepath):
        return self._profile._profile_single_python(filepath)

    def _is_ui_relevant_java(self, filepath, class_name, extends, annotations, package):
        return self._profile._is_ui_relevant_java(filepath, class_name, extends, annotations, package)

    def _infer_ui_packages(self, java_files, java_packages):
        return self._profile._infer_ui_packages(java_files, java_packages)

    def _infer_base_class_map(self, sample_data):
        return self._profile._infer_base_class_map(sample_data)

    def _infer_locator_priorities(self, sample_data):
        return self._profile._infer_locator_priorities(sample_data)

    def _infer_naming_from_sample(self, sample_data):
        return self._profile._infer_naming_from_sample(sample_data)

    def _compute_profiling_confidence(self, profile):
        return self._profile._compute_profiling_confidence(profile)

    def _infer_layer_structure(self, source_dirs, profile):
        return self._profile._infer_layer_structure(source_dirs, profile)

    def _infer_reference_directories(self, source_dirs, profile):
        return self._profile._infer_reference_directories(source_dirs, profile)

    def _infer_output_config(self, profile):
        return self._profile._infer_output_config(profile)

    def _infer_component_monitoring(self, profile):
        return self._profile._infer_component_monitoring(profile)

    # ── Internal delegation: Convention miner ──

    def _extract_naming_conventions(self, items: list[KBItem]) -> list[KBItem]:
        return self._conventions._extract_naming_conventions(items)

    @staticmethod
    def _classify_method_prefix(name: str) -> str:
        return ConventionMiner._classify_method_prefix(name)

    def _extract_operation_conventions(self, source_files):
        return self._conventions._extract_operation_conventions(source_files)

    def _extract_import_conventions(self, source_files):
        return self._conventions._extract_import_conventions(source_files)

    def _extract_locator_usage_conventions(self, source_files, profile):
        return self._conventions._extract_locator_usage_conventions(source_files, profile)

    def _extract_assertion_conventions(self, test_files):
        return self._conventions._extract_assertion_conventions(test_files)

    def _extract_patterns(self, test_files, profile):
        return self._conventions._extract_patterns(test_files, profile)

    # ── Internal delegation: Aggregation extractor ──

    def _quick_ui_check(self, content: str) -> bool:
        return self._aggregation._quick_ui_check(content)

    def _extract_page_index(self, page_files, profile):
        return self._aggregation._extract_page_index(page_files, profile)

    def _extract_single_ui_file(self, filepath, profile):
        return self._aggregation._extract_single_ui_file(filepath, profile)

    def _filter_ui_files(self, files, profile):
        return self._aggregation._filter_ui_files(files, profile)

    def _group_by_component_family(self, files, profile):
        return self._aggregation._group_by_component_family(files, profile)

    def _extract_component_family(self, family_name, files, profile):
        return self._aggregation._extract_component_family(family_name, files, profile)
