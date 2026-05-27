"""KBStore — YAML-based persistence for knowledge base items"""

import re
import time
from pathlib import Path
from typing import Optional
import logging

logger = logging.getLogger(__name__)

import yaml

from .item import KBItem, Confidence, KnowledgeSource

CATEGORIES = ["conventions", "components", "patterns", "pages"]


class KBStore:
    """Stores and retrieves KB items in YAML files under .uibridge/kb/"""

    def __init__(self, project_root: str = "."):
        self.root = Path(project_root) / ".uibridge" / "kb"
        for cat in CATEGORIES:
            (self.root / cat).mkdir(parents=True, exist_ok=True)
        (self.root / "archive").mkdir(parents=True, exist_ok=True)
        self._index: dict[str, set[str]] = {}  # token → set(item_id)
        self._build_index()

    # ── CRUD ──────────────────────────────────────────

    def save(self, item: KBItem) -> str:
        item.updated_at = time.time()
        d = item.to_dict()
        d["updated_at"] = item.updated_at
        d["created_at"] = item.created_at
        filepath = self._filepath(item)
        with open(filepath, "w", encoding="utf-8") as f:
            yaml.safe_dump(d, f, allow_unicode=True, sort_keys=False)
        self._index_item(item)
        return str(filepath)

    def get(self, category: str, item_id: str) -> Optional[KBItem]:
        filepath = self._filepath_for(category, item_id)
        if not filepath.exists():
            return None
        with open(filepath, "r", encoding="utf-8") as f:
            d = yaml.safe_load(f)
        return KBItem.from_dict(d)

    def get_by_key(self, category: str, key: str) -> Optional[KBItem]:
        for item in self.list_category(category):
            if item.key == key and not item.archived:
                return item
        return None

    def list_category(self, category: str) -> list[KBItem]:
        dirpath = self.root / category
        if not dirpath.exists():
            return []
        items = []
        for path in dirpath.glob("*.yaml"):
            with open(path, "r", encoding="utf-8") as f:
                d = yaml.safe_load(f)
            items.append(KBItem.from_dict(d))
        return sorted(items, key=lambda i: i.confidence.effective_score, reverse=True)

    def list_all(self) -> list[KBItem]:
        items = []
        for cat in CATEGORIES:
            items.extend(self.list_category(cat))
        return sorted(items, key=lambda i: i.confidence.effective_score, reverse=True)

    def delete(self, item: KBItem):
        filepath = self._filepath(item)
        if filepath.exists():
            filepath.unlink()
        self._deindex_item(item)

    def archive(self, item: KBItem):
        item.archived = True
        item.updated_at = time.time()
        # Move to archive dir
        old_path = self._filepath(item)
        new_path = self.root / "archive" / f"{item.id}.yaml"
        d = item.to_dict()
        d["updated_at"] = item.updated_at
        d["created_at"] = item.created_at
        with open(new_path, "w", encoding="utf-8") as f:
            yaml.safe_dump(d, f, allow_unicode=True, sort_keys=False)
        if old_path.exists():
            old_path.unlink()

    # ── Query ─────────────────────────────────────────

    def search(self, query: str) -> list[KBItem]:
        """Text search: indexed → substring → keyword relevance.

        1. 先查倒排索引（快速命中）
        2. 无结果退到精确子串匹配
        3. 仍无结果退到 TF-IDF 关键词评分
        """
        # 优先索引
        indexed = self._search_indexed(query)
        if indexed:
            return sorted(indexed, key=lambda i: i.confidence.effective_score, reverse=True)

        # 精确子串匹配
        results = []
        q_lower = query.lower()
        for item in self.list_all():
            text = f"{item.key} {item.description} {' '.join(item.tags)} {str(item.value)}"
            if q_lower in text.lower():
                results.append(item)

        if results:
            return sorted(results, key=lambda i: i.confidence.effective_score, reverse=True)

        # 回退：关键词相关性
        return self._keyword_search(query)

    def _keyword_search(self, query: str, min_score: float = 0.05) -> list[KBItem]:
        """IDF 加权语义搜索。

        将 query 拆分为词元（ASCII 单词 + CJK 字符独立成词），
        对每个 item 计算 IDF 加权余弦相似度，结合置信度排序。
        """
        import math
        import re

        # ── 分词：ASCII 单词 + CJK 单字 ──
        tokens_raw = re.findall(r'[a-zA-Z0-9_]+|[一-鿿]', query.lower())
        if not tokens_raw:
            return []

        # ── 构建文档集合 ──
        all_items = self.list_all()
        if not all_items:
            return []

        # 每个 item 的文本表示
        item_texts = {}
        for item in all_items:
            text = f"{item.key} {item.description} {' '.join(item.tags)} {str(item.value)}"
            item_texts[item.id] = text.lower()

        # ── 计算 IDF ──
        N = len(all_items)
        idf = {}
        for token in set(tokens_raw):
            df = sum(1 for text in item_texts.values() if token in text)
            idf[token] = math.log((N + 1) / (df + 1)) + 1  # smooth IDF

        # ── 查询向量 ──
        query_tf = {}
        for t in tokens_raw:
            query_tf[t] = query_tf.get(t, 0) + 1
        query_norm = math.sqrt(sum((query_tf[t] * idf.get(t, 0)) ** 2 for t in query_tf))

        if query_norm == 0:
            return []

        # ── 对每个 item 计算余弦相似度 ──
        scored = []
        for item in all_items:
            text = item_texts[item.id]
            # item 的 TF-IDF 向量（只对查询中出现的词计算）
            dot = 0.0
            item_norm_sq = 0.0
            for token in set(tokens_raw):
                w = idf.get(token, 0)
                if w == 0:
                    continue
                tf = text.count(token)
                dot += query_tf.get(token, 0) * w * tf * w
                item_norm_sq += (tf * w) ** 2
            item_norm = math.sqrt(item_norm_sq)

            if item_norm > 0:
                relevance = dot / (query_norm * item_norm)
            else:
                relevance = 0.0

            if relevance >= min_score:
                combined = relevance * 0.5 + item.confidence.effective_score * 0.5
                scored.append((combined, item))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [item for _, item in scored]

    def get_high_confidence(self, min_score: float = 0.7) -> list[KBItem]:
        return [i for i in self.list_all()
                if i.confidence.effective_score >= min_score and not i.archived]

    def search_by_tag(self, tag: str) -> list[KBItem]:
        """Find all active KBItems that have the given tag."""
        tag_lower = tag.lower()
        results = []
        for item in self.list_all():
            if not item.archived:
                for t in item.tags:
                    if t.lower() == tag_lower:
                        results.append(item)
                        break
        return sorted(results, key=lambda i: i.confidence.effective_score, reverse=True)

    def search_by_category(self, category: str) -> list[KBItem]:
        """Find all active KBItems in the given category."""
        if category not in CATEGORIES:
            return []
        items = self.list_category(category)
        return [i for i in items if not i.archived]

    # ── Summary ──────────────────────────────────────

    def summarize(self) -> str:
        """Generate a NL summary of the entire KB."""
        lines = ["# Knowledge Base Summary\n"]
        for cat in CATEGORIES:
            items = self.list_category(cat)
            active = [i for i in items if not i.archived]
            if not active:
                continue
            lines.append(f"\n## {cat} ({len(active)} entries)\n")
            for item in active[:10]:  # top 10 by confidence
                conf = item.confidence.effective_score
                icon = "●" if conf >= 0.8 else "◐" if conf >= 0.5 else "○"
                lines.append(
                    f"- {icon} `{item.key}` — {item.description} "
                    f"(confidence: {conf:.2f}, source: {item.confidence.source.value})"
                )
        return "\n".join(lines)

    # ── Batch Operations ──────────────────────────────

    def save_batch(self, items: list[KBItem]) -> list[str]:
        """批量保存多个 KBItem，返回文件路径列表"""
        return [self.save(item) for item in items]

    def merge_or_save(self, item: KBItem) -> tuple[str, bool]:
        """如果已有同 category + key 的条目，合并 value + 升置信度；否则新增。
        Returns (filepath, was_merged).
        """
        existing = self.get_by_key(item.category, item.key)
        if existing and not existing.archived:
            existing.value.update(item.value)
            existing.confidence.score = max(existing.confidence.score, item.confidence.score)
            existing.confidence.source = item.confidence.source
            existing.version += 1
            existing.updated_at = time.time()
            if item.source_files:
                existing.source_files = list(set((existing.source_files or []) + item.source_files))
            existing.tags = list(set(existing.tags + item.tags))
            return (self.save(existing), True)
        return (self.save(item), False)

    # ── Component Snapshots ──────────────────────────

    def save_component_snapshot(self, component_name: str, source_file: str,
                                 methods: list[str], locators: dict,
                                 base_class: str = "") -> str:
        """Save a component's current state snapshot for freshness monitoring.

        Args:
            component_name: e.g. "WebTable"
            source_file: relative path to source file
            methods: list of method signatures
            locators: {"xpath": "...", "data_testid": "...", ...}
            base_class: extends class name

        Returns:
            File path of the saved snapshot.
        """
        snap_dir = self.root / "snapshots"
        snap_dir.mkdir(parents=True, exist_ok=True)
        filepath = snap_dir / f"{component_name}.yaml"

        d = {
            "component": component_name,
            "source_file": source_file,
            "base_class": base_class,
            "methods": methods,
            "locators": locators,
            "captured_at": time.time(),
        }
        with open(filepath, "w", encoding="utf-8") as f:
            yaml.safe_dump(d, f, allow_unicode=True, sort_keys=False)
        return str(filepath)

    def load_component_snapshot(self, component_name: str) -> dict | None:
        """Load a previously saved component snapshot.

        Returns None if snapshot doesn't exist.
        """
        filepath = self.root / "snapshots" / f"{component_name}.yaml"
        if not filepath.exists():
            return None
        with open(filepath, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)

    def list_snapshots(self) -> list[str]:
        """List all component names that have snapshots."""
        snap_dir = self.root / "snapshots"
        if not snap_dir.exists():
            return []
        return [p.stem for p in snap_dir.glob("*.yaml")]

    def delete_snapshot(self, component_name: str):
        """Remove a component snapshot."""
        filepath = self.root / "snapshots" / f"{component_name}.yaml"
        if filepath.exists():
            filepath.unlink()

    @staticmethod
    def compare_snapshot(existing: dict, current: dict) -> dict:
        """Compare stored snapshot with current source, returning a diff report.

        Uses structured method signature parsing to detect return type and
        parameter changes, not just method name presence.

        Args:
            existing: dict from load_component_snapshot()
            current: dict with same shape from fresh analysis

        Returns:
            {"stale": bool, "added_methods": [...], "removed_methods": [...],
             "locator_changes": [...], "base_class_changed": bool,
             "signature_changes": [...]}
        """
        old_sigs = {s: KBStore._parse_method_signature(s)
                    for s in existing.get("methods", [])}
        new_sigs = {s: KBStore._parse_method_signature(s)
                    for s in current.get("methods", [])}

        old_names = {v["name"] for v in old_sigs.values() if v}
        new_names = {v["name"] for v in new_sigs.values() if v}

        added = sorted(new_names - old_names)
        removed = sorted(old_names - new_names)

        # Signature changes: same method name, different return/params
        sig_changes = []
        for name in old_names & new_names:
            old_sig = next(v for v in old_sigs.values() if v and v["name"] == name)
            new_sig = next(v for v in new_sigs.values() if v and v["name"] == name)
            if old_sig != new_sig:
                sig_changes.append({
                    "method": name,
                    "old": old_sig,
                    "new": new_sig,
                })

        old_locators = existing.get("locators") or {}
        new_locators = current.get("locators") or {}

        locator_changes = []
        for key in set(old_locators) | set(new_locators):
            old_val = old_locators.get(key)
            new_val = new_locators.get(key)
            if old_val != new_val:
                locator_changes.append({
                    "key": key,
                    "old": old_val,
                    "new": new_val,
                })

        base_changed = existing.get("base_class") != current.get("base_class")

        return {
            "stale": bool(added or removed or locator_changes or base_changed or sig_changes),
            "added_methods": added,
            "removed_methods": removed,
            "signature_changes": sig_changes,
            "locator_changes": locator_changes,
            "base_class_changed": base_changed,
        }

    @staticmethod
    def _parse_method_signature(sig: str) -> dict | None:
        """Parse a method signature into structured components.

        "void sortColumn(String name, int count)" →
            {"return": "void", "name": "sortColumn",
             "params": ["String name", "int count"]}
        "def get_text(self) -> str" →
            {"return": "str", "name": "get_text",
             "params": ["self"]}
        """
        sig = sig.strip()
        if not sig:
            return None

        # Java: "returnType methodName(params)"
        java_match = re.match(
            r'(\w+(?:<[^>]+>)?)\s+(\w+)\s*\(([^)]*)\)', sig)
        if java_match:
            ret = java_match.group(1)
            name = java_match.group(2)
            params_str = java_match.group(3).strip()
            params = [p.strip() for p in params_str.split(",") if p.strip()]
            return {"return": ret, "name": name, "params": params}

        # Python: "def methodName(params) -> returnType"
        py_match = re.match(
            r'def\s+(\w+)\s*\(([^)]*)\)(?:\s*->\s*(\w+))?', sig)
        if py_match:
            name = py_match.group(1)
            params_str = py_match.group(2).strip()
            ret = py_match.group(3) or "None"
            params = [p.strip() for p in params_str.split(",") if p.strip()]
            return {"return": ret, "name": name, "params": params}

        return None

    # ── Index ────────────────────────────────────────

    def _build_index(self):
        """从已有文件重建倒排索引。"""
        self._index.clear()
        for item in self.list_all():
            self._index_item(item)

    @staticmethod
    def _tokenize(text: str) -> set[str]:
        """将文本拆分为搜索 token。"""
        tokens = set()
        for token in re.findall(r'[a-zA-Z0-9_]+|[一-鿿]', text.lower()):
            tokens.add(token)
            if len(token) > 2:
                for i in range(len(token) - 1):
                    tokens.add(token[i:i + 2])
        return tokens

    def _index_item(self, item: KBItem):
        """将 item 的 token 加入索引。"""
        text = f"{item.key} {item.description} {' '.join(item.tags)} {str(item.value)}"
        for token in self._tokenize(text):
            self._index.setdefault(token, set()).add(item.id)

    def _deindex_item(self, item: KBItem):
        """从索引中移除 item。"""
        text = f"{item.key} {item.description} {' '.join(item.tags)} {str(item.value)}"
        for token in self._tokenize(text):
            if token in self._index:
                self._index[token].discard(item.id)
                if not self._index[token]:
                    del self._index[token]

    def _search_indexed(self, query: str) -> list[KBItem]:
        """使用倒排索引搜索。匹配所有 token 的 item 得分更高。"""
        tokens = self._tokenize(query)
        if not tokens:
            return []

        scores: dict[str, float] = {}
        for token in tokens:
            for item_id in self._index.get(token, set()):
                scores[item_id] = scores.get(item_id, 0) + 1

        min_score = max(2, len(tokens) * 0.4)
        ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        results = []
        for item_id, score in ranked[:20]:
            if score < min_score:
                break
            item = self._get_by_id(item_id)
            if item and not item.archived:
                results.append(item)

        return results

    def _get_by_id(self, item_id: str) -> Optional[KBItem]:
        """按 ID 获取 item。用于索引查询后获取完整对象。"""
        for cat in CATEGORIES:
            filepath = self.root / cat / f"{item_id}.yaml"
            if filepath.exists():
                try:
                    with open(filepath, "r", encoding="utf-8") as f:
                        d = yaml.safe_load(f)
                    return KBItem.from_dict(d)
                except Exception:
                    logger.warning("Failed to load KB item from YAML: %s", filepath, exc_info=True)
                    pass
        return None

    # ── Internal ─────────────────────────────────────

    def _filepath(self, item: KBItem) -> Path:
        return self._filepath_for(item.category, item.id)

    def _filepath_for(self, category: str, item_id: str) -> Path:
        return self.root / category / f"{item_id}.yaml"
