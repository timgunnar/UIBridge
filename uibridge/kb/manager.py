"""KBManager — lifecycle management: seed → query → feedback → evolve"""

import re
import time
from pathlib import Path
from typing import Optional
import logging

logger = logging.getLogger(__name__)

from .item import KBItem, Confidence, KnowledgeSource
from .store import KBStore
from .extractor import KBExtractor
from .evolution import KBEvolution
from .freshness import FreshnessMonitor
# source_detection and profile moved to scanner/ in v0.4.0


class KBManager:
    """Manages the full KB lifecycle with confidence scoring and NL interaction."""

    def __init__(self, project_root: str = ".", profile_manager=None, audit_logger=None):
        self.project_root = Path(project_root)
        self.store = KBStore(project_root)
        self.extractor = KBExtractor(project_root)
        self._profile_manager = profile_manager
        self.audit_logger = audit_logger

    # ══════════════════════════════════════════════════════════
    # Seed Phase
    # ══════════════════════════════════════════════════════════

    def seed_from_static_analysis(self, source_dirs: dict[str, str],
                                   filter_ui: bool = True) -> list[KBItem]:
        """Bulk seed KB from static analysis of source directories.

        source_dirs: {"component_aw": "aaw/", "pages": "pages/", "tests": "tests/"}

        自动检测 Python (.py) 和 Java (.java) 文件并使用对应的提取器。
        filter_ui=True 时，先用 UIRelevanceFilter 排除非 UI 文件（DTO/Util/Config 等噪声）。
        """
        seeded = []

        ui_filter = None
        if filter_ui:
            from uibridge.scanner.filter import UIRelevanceFilter
            ui_filter = UIRelevanceFilter(self.project_root)

        for category, dir_path in source_dirs.items():
            target_dir = self.project_root / dir_path
            if not target_dir.exists():
                continue

            # 优先 Python，其次 Java
            py_files = list(target_dir.glob("**/*.py"))
            java_files = list(target_dir.glob("**/*.java"))

            # Pre-filter to UI-relevant files only
            if ui_filter:
                py_files = ui_filter.filter(py_files, min_signals=2)
                java_files = ui_filter.filter(java_files, min_signals=2)

            if py_files:
                for path in py_files:
                    if category == "component_aw":
                        items = self.extractor._legacy_extract_from_component_aw(str(path))
                    elif category == "pages":
                        items = self.extractor._legacy_extract_from_page_file(str(path))
                    elif category == "tests":
                        items = self.extractor._legacy_extract_from_test_script(str(path))
                    else:
                        continue
                    for item in items:
                        self.store.save(item)
                        seeded.append(item)

            if java_files:
                for path in java_files:
                    if category == "tests":
                        items = self.extractor._legacy_extract_from_java_test(str(path))
                    else:
                        items = self.extractor._legacy_extract_from_java_file(str(path))
                    for item in items:
                        self.store.save(item)
                        seeded.append(item)

        # 批量分析：命名约定提取（在所有文件处理完毕后）
        if seeded:
            naming_items = self.extractor._extract_naming_conventions(seeded)
            for item in naming_items:
                self.store.save(item)

        return seeded

    def auto_detect_source_dirs(self) -> dict[str, str]:
        """[STUB v0.4.0] SourceDetector deleted. Returns empty dict.

        Source detection moved to scanner/ module.
        """
        return {}

    def auto_seed(self) -> list[KBItem]:
        """自动播种 KB：优先两阶段聚合，回退传统逐文件扫描。

        策略：
        1. 尝试 seed_two_phase() — 产出 ~50-200 个聚合 KBItem
        2. 若 profiling_confidence < 0.3 或 Phase 2 产出为空，回退旧方法

        阈值按聚合模型计算：max(5, total // 100)。
        """
        existing = self.store.list_all()
        threshold = self._compute_auto_seed_threshold()
        if len(existing) >= threshold:
            return []

        # 优先两阶段
        try:
            items = self.seed_two_phase()
            if items:
                return items
        except Exception:
            logger.warning("Two-phase seed failed, falling back to static analysis", exc_info=True)
            pass

        # 回退传统方法
        source_dirs = self.auto_detect_source_dirs()
        return self.seed_from_static_analysis(source_dirs)

    def _compute_auto_seed_threshold(self) -> int:
        """按项目源文件数量动态计算播种阈值（聚合模型）。

        聚合后预期产出 ~50-200 条，阈值相应降低：max(5, total // 100)。
        大项目（15000 文件）→ 阈值 150，小项目（500 文件）→ 阈值 5。
        """
        java_count = 0
        py_count = 0
        try:
            java_count = len(list(self.project_root.glob("**/*.java")))
        except Exception:
            logger.warning("Failed to count Java files for auto-seed threshold", exc_info=True)
            pass
        try:
            py_count = len(list(self.project_root.glob("**/*.py")))
        except Exception:
            logger.warning("Failed to count Python files for auto-seed threshold", exc_info=True)
            pass
        total = java_count + py_count
        return max(5, total // 100)

    def seed_two_phase(self, profile: "FrameworkProfile | None" = None,
                       force_reprofile: bool = False) -> list[KBItem]:
        """两阶段聚合播种：Phase 1 画像 → Phase 2 聚合提取。

        Phase 1 委托 ProfileManager.seed_phase1()，
        Phase 2 使用 KBExtractor.extract_aggregated()。

        Args:
            profile: 预生成的 FrameworkProfile。若为 None 且
                     self._profile_manager 已注入，则内部调用 Phase 1。
            force_reprofile: 即使已有 profile.yaml 也强制重新画像

        Returns:
            聚合后的 KBItem 列表（~50-200 条）。
            若 profiling_confidence < 0.3 返回空列表（触发回退）。
        """
        # Phase 1: 画像（使用注入的 profile 或委托 ProfileManager）
        if profile is None:
            if self._profile_manager:
                source_dirs = self.auto_detect_source_dirs()
                profile = self._profile_manager.seed_phase1(source_dirs, force_reprofile)
            else:
                return []

        if profile.profiling_confidence < 0.3:
            return []

        # Phase 2: 聚合提取
        items = self.extractor.extract_aggregated(profile)
        if not items:
            return []

        saved = []
        for item in items:
            self.store.merge_or_save(item)
            saved.append(item)

        return saved

    # ══════════════════════════════════════════════════════════
    # Component Freshness Monitoring
    # ══════════════════════════════════════════════════════════

    def check_component_freshness(self) -> list[dict]:
        """遍历监控组件，对比 KB 快照与源码，返回差异报告。"""
        monitor = FreshnessMonitor(self.store, self._profile_manager,
                                   str(self.project_root))
        return monitor.check_component_freshness()

    def seed_from_runtime(self, component_type: str, method_traces: list[dict],
                          page_url: str) -> list[KBItem]:
        """Seed from runtime execution traces."""
        items = self.extractor.extract_from_runtime_trace(component_type, method_traces, page_url)
        for item in items:
            existing = self.store.get_by_key(item.category, item.key)
            if existing:
                # Merge: update confidence and add new xpaths
                existing.value.update(item.value)
                existing.confidence.score = max(existing.confidence.score, item.confidence.score)
                existing.confidence.source = item.confidence.source
                existing.version += 1
                self.store.save(existing)
            else:
                self.store.save(item)
        return items

    def seed_from_document(self, text: str, source_name: str = "design_doc") -> list[KBItem]:
        """Seed from NL design document."""
        items = self.extractor.extract_from_design_doc(text, source_name)
        for item in items:
            self.store.save(item)
        return items

    def inject(self, category: str, key: str, value: dict, description: str) -> KBItem:
        """Direct human injection of a KB entry."""
        if not isinstance(value, dict):
            raise TypeError(f"inject() value 参数必须是 dict，收到 {type(value).__name__}")
        if not isinstance(category, str) or not category:
            raise ValueError("category 必须是非空字符串")
        if not isinstance(key, str) or not key:
            raise ValueError("key 必须是非空字符串")
        item = self.extractor.inject_convention(key, value, description)
        item.category = category
        item.id = f"human_{category}_{key.replace('.', '_')}"
        self.store.save(item)
        return item

    # ══════════════════════════════════════════════════════════
    # Query Phase
    # ══════════════════════════════════════════════════════════

    def query(self, query_text: str, min_confidence: float = 0.4) -> list[KBItem]:
        """Search KB with NL text query."""
        results = self.store.search(query_text)
        return [r for r in results if r.confidence.effective_score >= min_confidence]

    def get_component_type(self, aria_role: str, dom_attrs: dict) -> Optional[dict]:
        """Query KB: what component type maps to this ARIA role?"""
        # First try exact match on data-module
        data_module = dom_attrs.get("data-module", "")
        if data_module:
            for item in self.store.list_category("components"):
                patterns = item.value.get("xpath_patterns", [])
                for p in patterns:
                    if data_module in p:
                        return {"type": item.value.get("class_name", "UnknownAW"), "kb_item": item}

        # Then try ARIA role mapping from conventions
        for item in self.store.list_category("conventions"):
            mappings = item.value.get("component_type_mappings", [])
            if isinstance(mappings, list):
                pass  # need structured mapping
            if item.key == "convention.component_types":
                role_map = item.value.get("aria_role_map", {})
                if aria_role in role_map:
                    return {"type": role_map[aria_role], "kb_item": item}

        return None

    def get_locator_conventions(self) -> dict:
        """Query KB: what locator strategies are configured?"""
        for item in self.store.list_category("conventions"):
            if item.key == "convention.locator_priority":
                return item.value
        return {}

    def get_naming_rules(self) -> list[str]:
        """Query KB: what naming conventions exist?"""
        for item in self.store.list_category("conventions"):
            if item.key == "convention.naming":
                return item.value.get("naming_rules", [])
        return []

    def get_pattern(self, pattern_key: str) -> Optional[dict]:
        """Query KB: get a specific pattern."""
        for item in self.store.list_category("patterns"):
            if item.key == pattern_key:
                return item.value
        return None

    # ══════════════════════════════════════════════════════════
    # Feedback Phase
    # ══════════════════════════════════════════════════════════

    def record_self_test_result(self, item_id: str, category: str, passed: bool):
        """Update confidence based on self-test result."""
        item = self.store.get(category, item_id)
        if item:
            if passed:
                item.confidence.record_pass()
            else:
                item.confidence.record_failure()
            self.store.save(item)

    def correct(self, category: str, item_id: str, corrections: dict,
                nl_note: str = "") -> KBItem:
        """Apply human correction to a KB item via NL feedback."""
        item = self.store.get(category, item_id)
        if not item:
            raise KeyError(f"KB item not found: {category}/{item_id}")

        before = {"value": item.value.copy(), "description": item.description}
        item.value.update(corrections)
        item.confidence.manual_override = corrections.get("confidence_override",
                                                          item.confidence.effective_score)
        item.description = nl_note or item.description
        item.version += 1
        item.tags.append("corrected")
        self.store.save(item)
        if self.audit_logger:
            self.audit_logger.log(
                "kb.modify", f"{category}/{item_id}",
                before, {"value": item.value, "description": item.description},
                source="structured_tool", note=nl_note,
            )
        return item

    # ══════════════════════════════════════════════════════════
    # Evolve Phase
    # ══════════════════════════════════════════════════════════

    def evolve(self):
        """Run KB evolution cycle: decay, generalize, archive."""
        KBEvolution(self.store).evolve()

    # ══════════════════════════════════════════════════════════
    # NL Interaction
    # ══════════════════════════════════════════════════════════

    def query_nl(self, question: str) -> str:
        """Answer a NL question about the KB. Returns a text summary."""
        results = self.query(question, min_confidence=0.3)
        if not results:
            return f"No KB entries found matching: '{question}'"

        lines = [f"Found {len(results)} relevant KB entries for: '{question}'\n"]
        for item in results[:5]:
            conf = item.confidence.effective_score
            lines.append(
                f"- [{item.category}] {item.key}: {item.description} "
                f"(confidence: {conf:.2f})"
            )
        return "\n".join(lines)

    # ── NL Intent Patterns ──────────────────────────

    _INTENT_PATTERNS = [
        (re.compile(r'(?:删[除掉]|移除|去掉|清理)\s*(?:那个|这个|所有|掉)?\s*(.+)'), "DELETE"),
        (re.compile(r'(.+?)\s*(?:改为|改成)\s*(.+)'), "MODIFY"),
        (re.compile(r'(.+?)(?:应该|必须|需要|可以)\s*(?:用|使用)\s*(.+)'), "MODIFY"),
        (re.compile(r'(?:修改|更改?|调整|更新|设置)\s*(?:那个|这个)?\s*(.+)'), "MODIFY"),
        (re.compile(r'(?:新增|添加|加一[条个]|增加|创建)\s*(?:规则[:：]?\s*|一[条个]新(?:的)?\s*)?(.+)'), "ADD"),
        # PROFILE intent: 画像相关操作
        (re.compile(r'(?:我们|项目)(?:的)?(?:UI\s*)?(?:基类|base\s*class)[是为]\s*(.+)', re.IGNORECASE), "PROFILE"),
        (re.compile(r'(?:定位器?|locator)\s*优先级[是为]?\s*(.+)', re.IGNORECASE), "PROFILE"),
        (re.compile(r'(?:组件|component)\s*(?:目录|包|package)[是在为]\s*(.+)', re.IGNORECASE), "PROFILE"),
        (re.compile(r'(?:重新)?(?:画像|profile|profiling)', re.IGNORECASE), "PROFILE"),
    ]

    _CATEGORY_KEYWORDS = {
        "conventions": ["约定", "规范", "惯例", "定位", "优先级", "命名", "包名", "导入",
                       "断言", "convention", "priority", "locator", "naming"],
        "components": ["组件", "component", "aw", "target", "element", "元素",
                       "表格", "输入框", "按钮", "下拉", "弹窗", "菜单", "树",
                       "table", "input", "button", "dropdown", "dialog", "menu"],
        "patterns": ["模式", "pattern", "流程", "序列", "模板", "pattern", "template"],
        "pages": ["页面", "page", "url", "路由", "导航"],
    }

    def _parse_intent(self, instruction: str) -> dict:
        """Parse NL instruction into intent + parameters."""
        text = instruction.strip()

        for pattern, intent in self._INTENT_PATTERNS:
            m = pattern.match(text)
            if m:
                if intent == "DELETE":
                    return {"intent": "DELETE", "target": m.group(1).strip()}
                elif intent == "ADD":
                    return {"intent": "ADD", "content": m.group(1).strip()}
                elif intent == "MODIFY":
                    groups = m.groups()
                    if len(groups) == 2:
                        return {"intent": "MODIFY", "target": groups[0].strip(),
                                "new_value": groups[1].strip()}
                    else:
                        return {"intent": "MODIFY", "target": groups[0].strip()}
                elif intent == "PROFILE":
                    groups = m.groups()
                    content = groups[0].strip() if groups else ""
                    # Guard: if content is a question word or text ends with ?, treat as QUERY
                    if re.search(r'[?？]$', text) or re.match(r'^(什么|哪些|怎么|如何|有没有|是什么|多少)', content):
                        break  # fall through to QUERY detection below
                    return {"intent": "PROFILE", "content": content,
                            "raw": text}

        # Check for question patterns → QUERY
        if re.search(r'[?？]|什么|哪些|怎么|如何|有没有|是什么|查', text):
            return {"intent": "QUERY", "question": text}

        # Fallback: treat as QUERY
        return {"intent": "QUERY", "question": text}

    def _infer_category(self, text: str) -> str:
        """Infer KB category from NL content keywords."""
        text_lower = text.lower()
        best_category = "conventions"
        best_score = 0
        for cat, keywords in self._CATEGORY_KEYWORDS.items():
            score = sum(1 for kw in keywords if kw in text_lower)
            if score > best_score:
                best_score = score
                best_category = cat
        return best_category

    def _handle_profile_intent(self, parsed: dict) -> dict:
        """处理 PROFILE 意图：更新画像字段或触发重新画像。"""
        content = parsed.get("content", "")
        raw = parsed.get("raw", "")

        # "重新画像" / "reprofile" → 强制重新画像
        if re.search(r'(?:重新|re-?)\s*(?:画像|profile|profiling)', raw, re.IGNORECASE):
            if not self._profile_manager:
                return {"status": "error", "intent": "PROFILE",
                        "message": "ProfileManager 未注入，无法执行画像操作。"}
            profile = self._profile_manager.reprofile()
            return {"status": "ok", "intent": "PROFILE",
                    "message": f"已重新画像，置信度: {profile.profiling_confidence:.2f}",
                    "profile_confidence": profile.profiling_confidence}

        # 基类相关
        if re.search(r'基类|base\s*class', raw, re.IGNORECASE):
            base_map = {}
            parts = re.split(r'[,，、]\s*', content)
            for part in parts:
                m = re.match(r'(\w+)\s*[→:：=]\s*(\w+)', part.strip())
                if m:
                    base_map[m.group(1)] = m.group(2)
                else:
                    base_map[part.strip()] = "base"
            if base_map:
                profile = self._profile_manager.update_profile("base_classes", base_map)
                return {"status": "ok", "intent": "PROFILE",
                        "message": f"已更新画像 base_classes: {base_map}",
                        "updated_field": "base_classes", "value": base_map}

        # 定位器优先级
        if re.search(r'定位|locator|优先级|priority', raw, re.IGNORECASE):
            locators = re.split(r'[>→,，\s]+', content)
            locators = [l.strip() for l in locators if l.strip()]
            if locators:
                profile = self._profile_manager.update_profile("locator_priorities", locators)
                return {"status": "ok", "intent": "PROFILE",
                        "message": f"已更新画像 locator_priorities: {locators}",
                        "updated_field": "locator_priorities", "value": locators}

        # 组件目录
        if re.search(r'组件|component|目录|包|package', raw, re.IGNORECASE):
            dirs = {"components": content}
            profile = self._profile_manager.update_profile("source_dirs", dirs)
            return {"status": "ok", "intent": "PROFILE",
                    "message": f"已更新画像 source_dirs: {dirs}",
                    "updated_field": "source_dirs", "value": dirs}

        return {"status": "ok", "intent": "PROFILE",
                "message": "画像意图已识别但无法提取具体字段值，请更明确指定。"}

    def operate_nl(self, instruction: str) -> dict:
        """Execute KB CRUD via NL instruction. Returns structured result.

        Intents:
          QUERY: "表格组件的定位方式是什么？"
          ADD:   "新增规则：弹窗用 role='dialog' 识别"
          MODIFY:"表格组件的定位方式改为 data-testid"
          DELETE:"删掉表格排序的规则"
        """
        parsed = self._parse_intent(instruction)
        intent = parsed["intent"]

        if intent == "QUERY":
            answer = self.query_nl(parsed.get("question", instruction))
            return {"status": "ok", "intent": "QUERY", "result": answer}

        elif intent == "DELETE":
            target = parsed["target"]
            candidates = self.store.search(target)
            if not candidates:
                return {"status": "not_found", "intent": "DELETE",
                        "message": f"未找到与'{target}'匹配的 KB 条目",
                        "query": target}
            # Delete the best match
            best = candidates[0]
            before = {"value": best.value.copy(), "description": best.description,
                      "category": best.category, "key": best.key}
            self.store.archive(best)
            if self.audit_logger:
                self.audit_logger.log("kb.delete", f"{best.category}/{best.key}",
                                      before, {}, source="update_knowledge_base",
                                      note=instruction)
            return {"status": "ok", "intent": "DELETE",
                    "message": f"已删除: [{best.category}] {best.key} — {best.description}",
                    "deleted": {"category": best.category, "key": best.key,
                               "description": best.description}}

        elif intent == "ADD":
            content = parsed["content"]
            category = self._infer_category(content)
            key = re.sub(r'[^\w]+', '_', content[:40]).strip('_').lower()
            if not key:
                key = f"nl_add_{int(time.time())}"
            item = self.inject(
                category=category,
                key=key,
                value={"description": content, "source": "nl_dialogue"},
                description=content,
            )
            if self.audit_logger:
                self.audit_logger.log("kb.add", f"{category}/{key}",
                                      {}, {"value": item.value, "description": content},
                                      source="update_knowledge_base", note=instruction)
            return {"status": "ok", "intent": "ADD",
                    "message": f"已新增: [{category}] {key} — {content}",
                    "added": {"category": category, "key": key, "description": content}}

        elif intent == "MODIFY":
            target = parsed["target"]
            new_value = parsed.get("new_value", "")
            candidates = self.store.search(target)
            if not candidates:
                return {"status": "not_found", "intent": "MODIFY",
                        "message": f"未找到与'{target}'匹配的 KB 条目。要新增吗？",
                        "query": target, "suggest_add": True}
            best = candidates[0]
            old_desc = best.description
            before_val = best.value.copy()
            best.description = f"{old_desc} (modified via NL: {new_value or target})"
            if new_value:
                best.value["nl_modification"] = new_value
            best.value["nl_instruction"] = instruction
            best.confidence.source = KnowledgeSource.HUMAN_INJECTION
            best.confidence.score = max(0.9, best.confidence.score)
            best.version += 1
            self.store.save(best)
            if self.audit_logger:
                self.audit_logger.log("kb.modify", f"{best.category}/{best.key}",
                                      {"value": before_val, "description": old_desc},
                                      {"value": best.value, "description": best.description},
                                      source="update_knowledge_base", note=instruction)
            return {"status": "ok", "intent": "MODIFY",
                    "message": f"已更新: [{best.category}] {best.key} — {best.description}",
                    "modified": {"category": best.category, "key": best.key,
                                "old_description": old_desc,
                                "new_description": best.description}}

        elif intent == "PROFILE":
            return self._handle_profile_intent(parsed)

        return {"status": "error", "message": f"无法解析指令: '{instruction}'"}

    def summarize_kb(self) -> str:
        """Generate a full NL summary of the KB."""
        return self.store.summarize()

    def get_high_confidence_knowledge(self) -> dict[str, dict]:
        """Return all high-confidence knowledge as a structured dict, keyed by category."""
        result = {}
        for item in self.store.get_high_confidence(0.7):
            result.setdefault(item.category, {})[item.key] = item.value
        return result
