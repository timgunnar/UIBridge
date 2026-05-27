"""Java extractor — legacy Java extractors, AST helpers, and type inference."""

import logging
import re
import warnings
from pathlib import Path
from typing import Optional

from .extractor._base import safe_relative_to
from .item import KBItem, Confidence, KnowledgeSource

# Compiled regex for Java source parsing (hot path — called per file during KB seeding)
_JAVA_SINGLE_COMMENT_RE = re.compile(r'//[^\n]*')
_JAVA_BLOCK_COMMENT_RE = re.compile(r'/\*.*?\*/', re.DOTALL)
_JAVA_PACKAGE_RE = re.compile(r'package\s+([\w.]+)\s*;')
_JAVA_IMPORT_RE = re.compile(r'import\s+(static\s+)?([\w.*]+)\s*;')
_JAVA_CLASS_RE = re.compile(
    r'class\s+(\w+)(?:\s+extends\s+(\w+))?(?:\s+implements\s+([\w\s,]+?))?\s*\{'
)
_JAVA_ANNOTATION_RE = re.compile(r'@(\w+)\s*(?:\([^)]*\))?')
_JAVA_METHOD_RE = re.compile(
    r'(?:public|private|protected|static|\s)+\s+(\w+(?:<[^>]+>)?)\s+(\w+)\s*\('
)
_JAVA_LOCATOR_ANNOTATION_RE = re.compile(
    r'@(?:FindBy|DataModule|DataTestId|AndroidFindBy|iOSFindBy)'
    r'\s*\(([^)]*(?:\([^)]*\)[^)]*)*)\)',
    re.DOTALL
)
_JAVA_STRATEGY_RE = re.compile(
    r'(id|xpath|css|name|className|tagName|linkText|partialLinkText'
    r'|accessibility|uiAutomator|classChain|predicate)'
    r'\s*=\s*"((?:[^"\\]|\\.)*)"'
)
_JAVA_HOW_USING_RE = re.compile(
    r'how\s*=\s*\w+\.(\w+)\s*,\s*using\s*=\s*"([^"]*)"'
)

logger = logging.getLogger(__name__)


class JavaExtractor:
    """Legacy Java extractors, Java AST parsing, and component type inference."""

    # ── Component Type Inference ──────────────────────

    # 基类名 → 组件类型映射
    _BASE_CLASS_TYPE_MAP = {
        "table": ["Table", "BaseTable", "TableWidget", "GridPanel", "DataGrid",
                   "DataTable", "AbstractTable", "TableComponent"],
        "form": ["Form", "BaseForm", "EditForm", "FormPanel", "AbstractForm",
                  "FormWidget", "DetailForm"],
        "dialog": ["Dialog", "Modal", "BaseDialog", "DialogPanel", "ModalWindow",
                    "AbstractDialog", "Popup"],
        "search": ["SearchBox", "SearchInput", "SearchField", "SearchBar",
                    "SearchWidget", "QueryInput"],
        "button": ["Button", "BaseButton", "Btn", "ActionButton", "IconButton"],
        "dropdown": ["Dropdown", "ComboBox", "Select", "BaseDropdown", "DropDownList",
                      "SelectBox", "MultiSelect", "ChoiceBox"],
        "input": ["Input", "BaseInput", "TextField", "TextInput", "TextBox",
                   "NumberInput", "PasswordField", "TextArea"],
        "menu": ["Menu", "BaseMenu", "ContextMenu", "NavMenu", "Sidebar", "Navigation"],
        "tree": ["Tree", "BaseTree", "TreeView", "TreePanel", "TreeNode"],
        "tab": ["Tab", "BaseTab", "TabPanel", "TabWidget", "TabView", "TabBar"],
        "list": ["List", "BaseList", "ListView", "ListPanel", "ListWidget"],
        "link": ["Link", "BaseLink", "HyperLink", "Anchor"],
        "checkbox": ["CheckBox", "Check", "BaseCheckBox", "Toggle", "Switch"],
        "label": ["Label", "BaseLabel", "TextLabel", "StaticText"],
        "image": ["Image", "BaseImage", "ImageView", "Icon", "Picture"],
        "calendar": ["Calendar", "DatePicker", "BaseCalendar", "DateTimePicker",
                      "DateField", "TimePicker"],
    }

    def __init__(self, project_root: str):
        self.project_root = Path(project_root)
        self._java_available = None  # 延迟检测

    def _check_javalang(self) -> bool:
        """检测 javalang 是否可用，缓存结果。"""
        if self._java_available is None:
            try:
                import javalang  # noqa: F401
                self._java_available = True
            except ImportError:
                self._java_available = False
        return self._java_available

    # ── Java Static Analysis (confidence 0.6-0.8) ──────

    def _legacy_extract_from_java_file(self, filepath: str) -> list[KBItem]:
        """Parse a .java file → KB items for class, methods, annotations, inheritance,
        component type, locators, and conventions."""
        warnings.warn(
            "_legacy_extract_from_java_file is deprecated, use extract_aggregated() instead",
            DeprecationWarning, stacklevel=2)
        path = Path(filepath)
        if not path.exists():
            return []

        tree = self._parse_java(path)
        if not tree:
            return []

        items = []
        class_name = self._find_java_class_name(tree)
        if not class_name:
            return []

        methods = self._extract_java_methods(tree)
        annotations = self._extract_java_annotations(tree)
        package = self._extract_java_package(tree)
        base_class = self._extract_java_base_class(tree)
        implements = self._extract_java_implements(tree)
        locators = self._extract_java_locators(path, tree)
        is_regex = self._is_tree_from_regex(tree)

        # 推断组件类型
        component_type = self._infer_component_type(class_name, base_class, implements, annotations)

        # 确定分类
        if component_type:
            item_type = "components"
        elif "component" in str(path).lower() or "element" in str(path).lower() or "widget" in str(path).lower():
            item_type = "components"
        else:
            item_type = "pages"

        full_class = f"{package}.{class_name}" if package else class_name

        # 差异化置信度
        confidence = self._compute_java_confidence(
            has_annotations=bool(annotations),
            has_locators=bool(locators),
            has_base_class=bool(base_class),
            has_implements=bool(implements),
            is_regex_fallback=is_regex,
            has_only_class_name=not methods and not annotations,
        )

        # 构建 value dict
        value = {
            "class_name": class_name,
            "package": package,
            "methods": methods,
            "annotations": annotations,
            "source_file": safe_relative_to(path, self.project_root),
        }
        if base_class:
            value["base_class"] = base_class
        if implements:
            value["implements"] = implements
        if locators:
            value["locators"] = locators
        if component_type:
            value["component_type"] = component_type

        # 命名约定（从类名和方法名推断）
        naming_sig = self._extract_java_naming_signature(class_name, methods)
        if naming_sig:
            value["naming"] = naming_sig

        items.append(KBItem(
            id=f"java_{class_name.lower()}",
            category=item_type,
            key=f"java.{full_class}",
            value=value,
            confidence=confidence,
            description=f"Java class: {full_class} with {len(methods)} methods"
                        + (f", base: {base_class}" if base_class else "")
                        + (f", type: {component_type}" if component_type else ""),
            tags=[class_name, "java", item_type.rstrip('s')]
                 + ([component_type] if component_type else []),
            source_file=safe_relative_to(path, self.project_root),
        ))

        return items

    def _legacy_extract_from_java_test(self, filepath: str) -> list[KBItem]:
        """Parse a Java test file → KB items for style conventions."""
        warnings.warn(
            "_legacy_extract_from_java_test is deprecated, use extract_aggregated() instead",
            DeprecationWarning, stacklevel=2)
        path = Path(filepath)
        if not path.exists():
            return []

        tree = self._parse_java(path)
        if not tree:
            return []

        items = []
        class_name = self._find_java_class_name(tree)
        package = self._extract_java_package(tree)
        imports = self._extract_java_imports(tree)
        annotations = self._extract_java_annotations(tree)

        if class_name:
            items.append(KBItem(
                id=f"java_style_{class_name.lower()}",
                category="conventions",
                key=f"java.style.{class_name}",
                value={
                    "class_name": class_name,
                    "package": package,
                    "imports": imports,
                    "annotations": annotations,
                    "source_file": safe_relative_to(path, self.project_root),
                },
                confidence=Confidence(score=0.6, source=KnowledgeSource.STATIC_ANALYSIS),
                description=f"Java test style from {class_name}",
                tags=[class_name, "java", "test", "style"],
                source_file=safe_relative_to(path, self.project_root),
            ))

        return items

    # ── Java AST Helpers ──────────────────────────────

    def _parse_java(self, path: Path):
        """Parse Java file using javalang. Falls back to regex for Java 17+ syntax.

        Returns:
            - javalang AST tree on success
            - dict with regex-extracted info on javalang failure (Java 17+ fallback)
            - None if both approaches fail
        """
        source = None
        try:
            source = path.read_text(encoding="utf-8")
        except Exception:
            logger.warning("Failed to read Java source file: %s", path, exc_info=True)
            return None

        # 尝试 javalang
        if self._check_javalang():
            try:
                import javalang
                return javalang.parse.parse(source)
            except ImportError:
                self._java_available = False
            except Exception:
                logger.warning("javalang parse failed, falling back to regex", exc_info=True)
                pass  # 解析失败 → 尝试 regex 回退

        # Java 17+ regex 回退
        return self._parse_java_regex(source)

    @staticmethod
    def _parse_java_regex(source: str) -> dict | None:
        """Regex fallback for Java files that javalang can't parse (e.g. Java 17+).

        Extracts: class name, base class, package, imports, annotations, method names.
        Returns a dict keyed by extraction type, or None if nothing found.
        """
        result = {}

        # 移除单行注释和块注释，避免干扰
        cleaned = _JAVA_SINGLE_COMMENT_RE.sub('', source)
        cleaned = _JAVA_BLOCK_COMMENT_RE.sub('', cleaned)

        # 1. package
        pkg_match = _JAVA_PACKAGE_RE.search(cleaned)
        if pkg_match:
            result["package"] = pkg_match.group(1)

        # 2. imports
        imports = _JAVA_IMPORT_RE.findall(cleaned)
        if imports:
            result["imports"] = [imp[1] for imp in imports]

        # 3. class name + extends + implements
        class_match = _JAVA_CLASS_RE.search(cleaned)
        if class_match:
            result["class_name"] = class_match.group(1)
            if class_match.group(2):
                result["base_class"] = class_match.group(2)
            if class_match.group(3):
                implements = [i.strip() for i in class_match.group(3).split(",") if i.strip()]
                if implements:
                    result["implements"] = implements
        else:
            return None

        # 4. annotations (class-level and field-level)
        annotations = _JAVA_ANNOTATION_RE.findall(cleaned)
        if annotations:
            result["annotations"] = list(set(annotations))

        # 5. method names
        methods = _JAVA_METHOD_RE.findall(cleaned)
        if methods:
            result["methods"] = [
                {"name": m[1], "returns": m[0], "params": [], "modifiers": []}
                for m in methods
                if m[1] not in ("if", "while", "for", "switch", "catch", "synchronized")
            ]

        # 6. locator annotations (Selenium/Appium style)
        locator_annotations = _JAVA_LOCATOR_ANNOTATION_RE.findall(cleaned)
        if locator_annotations:
            result["locator_annotations"] = locator_annotations

        return result if result else None

    def _find_java_class_name(self, tree) -> Optional[str]:
        """Extract class name from javalang AST or regex dict."""
        if tree is None:
            return None
        # Regex fallback dict
        if isinstance(tree, dict):
            return tree.get("class_name")
        # javalang AST
        try:
            for path_node, node in tree:
                if hasattr(node, 'name') and type(node).__name__ == 'ClassDeclaration':
                    return node.name
        except Exception as e:
            logger.debug("Error finding Java class name: %s", e)
        return None

    def _extract_java_base_class(self, tree) -> Optional[str]:
        """Extract base class name from javalang AST or regex dict."""
        if tree is None:
            return None
        # Regex fallback dict
        if isinstance(tree, dict):
            return tree.get("base_class")
        # javalang AST: find ClassDeclaration → extends
        try:
            for path_node, node in tree:
                if type(node).__name__ == 'ClassDeclaration':
                    if hasattr(node, 'extends') and node.extends:
                        return node.extends.name
        except Exception:
            logger.warning("Failed to walk javalang AST for base class", exc_info=True)
            pass
        return None

    def _extract_java_implements(self, tree) -> list[str]:
        """Extract implemented interfaces from javalang AST or regex dict."""
        if tree is None:
            return []
        # Regex fallback dict
        if isinstance(tree, dict):
            return tree.get("implements", [])
        # javalang AST
        try:
            for path_node, node in tree:
                if type(node).__name__ == 'ClassDeclaration':
                    if hasattr(node, 'implements') and node.implements:
                        return [i.name for i in node.implements]
        except Exception:
            logger.warning("Failed to walk javalang AST for implements", exc_info=True)
            pass
        return []

    def _extract_java_package(self, tree) -> str:
        """Extract package from javalang AST or regex dict."""
        if tree is None:
            return ""
        # Regex fallback dict
        if isinstance(tree, dict):
            return tree.get("package", "")
        # javalang AST
        try:
            if hasattr(tree, 'package') and tree.package:
                return tree.package.name
        except Exception as e:
            logger.debug("Error extracting Java package: %s", e)
        return ""

    def _extract_java_methods(self, tree) -> list[dict]:
        """Extract methods from javalang AST or regex dict."""
        if tree is None:
            return []
        # Regex fallback dict
        if isinstance(tree, dict):
            return tree.get("methods", [])
        # javalang AST
        methods = []
        try:
            for path_node, node in tree:
                if type(node).__name__ == 'MethodDeclaration':
                    params = []
                    for p in node.parameters:
                        params.append({"name": p.name, "type": p.type.name if hasattr(p.type, 'name') else str(p.type)})
                    returns = node.return_type.name if node.return_type and hasattr(node.return_type, 'name') else "void"
                    methods.append({
                        "name": node.name,
                        "params": params,
                        "returns": returns,
                        "modifiers": list(node.modifiers) if node.modifiers else [],
                    })
        except Exception as e:
            logger.debug("Error extracting Java methods: %s", e)
        return methods

    def _extract_java_annotations(self, tree) -> list[str]:
        """Extract annotations from javalang AST or regex dict."""
        if tree is None:
            return []
        # Regex fallback dict
        if isinstance(tree, dict):
            return tree.get("annotations", [])
        # javalang AST
        annotations = []
        try:
            for path_node, node in tree:
                if type(node).__name__ == 'Annotation':
                    annotations.append(node.name)
        except Exception as e:
            logger.debug("Error extracting Java annotations: %s", e)
        return list(set(annotations))

    def _extract_java_imports(self, tree) -> list[str]:
        """Extract imports from javalang AST or regex dict."""
        if tree is None:
            return []
        # Regex fallback dict
        if isinstance(tree, dict):
            return tree.get("imports", [])
        # javalang AST
        imports = []
        try:
            if hasattr(tree, 'imports') and tree.imports:
                for imp in tree.imports:
                    imports.append(imp.path)
        except Exception as e:
            logger.debug("Error extracting Java imports: %s", e)
        return imports

    def _extract_java_locators(self, path: Path, tree) -> list[dict]:
        """Extract element locator annotations (@FindBy, @DataModule, etc.).

        Parses both javalang AST annotation values and regex-extracted raw strings.
        Returns list of {"strategy": str, "value": str} dicts.
        """
        locators = []
        source = None

        # Regex fallback: raw annotation text from dict
        if isinstance(tree, dict) and "locator_annotations" in tree:
            for raw in tree["locator_annotations"]:
                parsed = self._parse_locator_annotation(raw)
                if parsed:
                    locators.append(parsed)
            return locators

        # javalang AST: walk for annotations
        if tree is not None and not isinstance(tree, dict):
            try:
                for path_node, node in tree:
                    if type(node).__name__ == 'Annotation':
                        if node.name in ("FindBy", "DataModule", "DataTestId",
                                         "AndroidFindBy", "iOSFindBy"):
                            parsed = self._parse_locator_annotation_node(node)
                            if parsed:
                                locators.append(parsed)
            except Exception as e:
                logger.debug("Error extracting Java locators from AST: %s", e)

        # Fallback: regex on raw source
        if not locators:
            try:
                if source is None:
                    source = path.read_text(encoding="utf-8")
            except Exception:
                logger.warning("Failed to read Java source for regex locator fallback: %s", path, exc_info=True)
                pass
            if source:
                raw_annotations = _JAVA_LOCATOR_ANNOTATION_RE.findall(source)
                for raw in raw_annotations:
                    parsed = self._parse_locator_annotation(raw)
                    if parsed:
                        locators.append(parsed)

        return locators

    @staticmethod
    def _parse_locator_annotation(raw_text: str) -> dict | None:
        """Parse a locator annotation's key=value pairs from raw text like:
        'id = "search-box"' or 'xpath = "//div[@data-module=\\"table\\"]"'
        """
        strategy = None
        # 匹配 strategy = "value" 模式
        strategy_match = _JAVA_STRATEGY_RE.search(raw_text)
        if strategy_match:
            strategy = strategy_match.group(1)
            value = strategy_match.group(2)
            return {"strategy": strategy, "value": value}

        # 匹配 how = ...  using = "value" 模式 (Selenium 旧风格)
        how_match = _JAVA_HOW_USING_RE.search(raw_text)
        if how_match:
            return {"strategy": how_match.group(1).lower(), "value": how_match.group(2)}

        return None

    @staticmethod
    def _parse_locator_annotation_node(node) -> dict | None:
        """Parse a javalang Annotation node for locator info."""
        if not hasattr(node, 'element') or not node.element:
            return None
        try:
            elements = node.element if isinstance(node.element, list) else [node.element]
            result = {}
            for elem in elements:
                if hasattr(elem, 'name') and hasattr(elem, 'value'):
                    result[elem.name] = str(elem.value).strip('"')
            strategy = result.get("id") or result.get("xpath") or result.get("css") or \
                       result.get("name") or result.get("className") or result.get("tagName") or \
                       result.get("linkText") or result.get("partialLinkText")
            if strategy:
                # Determine which key was used
                for key in ("id", "xpath", "css", "name", "className", "tagName",
                            "linkText", "partialLinkText", "accessibility"):
                    if key in result:
                        return {"strategy": result.get("how", key), "value": result[key]}
        except Exception:
            logger.warning("Failed to parse locator annotation node", exc_info=True)
            pass
        return None

    @staticmethod
    def _is_tree_from_regex(tree) -> bool:
        """Check if the tree object came from regex fallback (is a dict)."""
        return isinstance(tree, dict)

    @classmethod
    def _infer_component_type(cls, class_name: str, base_class: str | None,
                              implements: list[str] | None,
                              annotations: list[str] | None) -> str | None:
        """Infer component type from base class name, class name suffix, and annotations.

        Returns a component type string like "table", "form", "dialog", etc., or None.
        """
        candidates = []

        # 1. 从基类名推断
        if base_class:
            for ctype, names in cls._BASE_CLASS_TYPE_MAP.items():
                if any(base_class == n or base_class.endswith(n) for n in names):
                    candidates.append((ctype, 3))  # 高权重

        # 2. 从类名后缀推断
        for ctype, names in cls._BASE_CLASS_TYPE_MAP.items():
            for n in names:
                if class_name.endswith(n) or class_name == n:
                    candidates.append((ctype, 2))  # 中权重
                    break

        # 3. 从 implements 推断
        if implements:
            for iface in implements:
                for ctype, names in cls._BASE_CLASS_TYPE_MAP.items():
                    # 接口名通常包含 HasXxx, IsXxx 等模式
                    iface_clean = iface.replace("Has", "").replace("Is", "").replace("I", "")
                    if any(iface_clean == n or iface_clean.endswith(n) for n in names):
                        candidates.append((ctype, 2))

        # 4. 从注解推断
        if annotations:
            annotation_hints = {
                "table": ["TableComponent", "GridComponent"],
                "form": ["FormComponent", "FormField"],
                "dialog": ["DialogBox", "ModalDialog"],
                "button": ["ActionButton", "Clickable"],
                "dropdown": ["Dropdown", "Selectable"],
                "search": ["Searchable", "SearchField"],
            }
            for ctype, hints in annotation_hints.items():
                if any(a in hints for a in annotations):
                    candidates.append((ctype, 1))  # 低权重

        if not candidates:
            return None

        # 按权重排序，返回权重最高的
        candidates.sort(key=lambda x: -x[1])
        return candidates[0][0]

    @staticmethod
    def _compute_java_confidence(has_annotations: bool, has_locators: bool,
                                 has_base_class: bool, has_implements: bool,
                                 is_regex_fallback: bool,
                                 has_only_class_name: bool) -> Confidence:
        """Compute differentiated confidence score for Java extraction.

        - Explicit annotations + locators → 0.80
        - Clear inheritance (extends) → 0.75
        - Regex fallback with some info → 0.55
        - Only class name extracted → 0.50
        """
        if has_only_class_name:
            return Confidence(score=0.5, source=KnowledgeSource.STATIC_ANALYSIS)

        if is_regex_fallback:
            return Confidence(score=0.55, source=KnowledgeSource.STATIC_ANALYSIS)

        if has_annotations and has_locators:
            return Confidence(score=0.80, source=KnowledgeSource.STATIC_ANALYSIS)

        if has_base_class or has_implements:
            return Confidence(score=0.75, source=KnowledgeSource.STATIC_ANALYSIS)

        if has_annotations:
            return Confidence(score=0.70, source=KnowledgeSource.STATIC_ANALYSIS)

        return Confidence(score=0.65, source=KnowledgeSource.STATIC_ANALYSIS)

    @staticmethod
    def _extract_java_naming_signature(class_name: str, methods: list[dict]) -> dict | None:
        """Extract naming convention patterns from class name and method names.

        Detects conventions like: class suffix "AW"/"Page"/"Widget",
        method prefixes "get"/"is"/"click", field style "camelCase"/"snake_case".
        """
        naming = {}

        # 类名后缀检测
        class_suffixes = ["AW", "Page", "Widget", "Panel", "Element", "Component",
                          "View", "Controller", "Helper", "Util", "Service"]
        for suffix in class_suffixes:
            if class_name.endswith(suffix):
                naming["class_suffix"] = suffix
                break

        # 方法名前缀检测
        if methods:
            prefix_counts = {}
            for m in methods:
                name = m.get("name", "")
                # 检测 getXxx, isXxx, clickXxx, enterXxx, setXxx, findXxx
                for prefix in ["get", "is", "click", "enter", "set", "find", "has",
                               "select", "type", "wait", "verify", "check", "open",
                               "close", "navigate", "hover"]:
                    if name.startswith(prefix) and len(name) > len(prefix) and name[len(prefix)].isupper():
                        prefix_counts[prefix] = prefix_counts.get(prefix, 0) + 1

            # 取最常见的前缀
            if prefix_counts:
                most_common = max(prefix_counts, key=prefix_counts.get)
                naming["method_prefix"] = most_common

            # 检测方法名风格: camelCase vs snake_case
            camel_count = sum(1 for m in methods if "_" not in m.get("name", ""))
            snake_count = sum(1 for m in methods if "_" in m.get("name", ""))
            if camel_count > snake_count:
                naming["field_style"] = "camelCase"
            elif snake_count > 0:
                naming["field_style"] = "snake_case"

        return naming if naming else None
