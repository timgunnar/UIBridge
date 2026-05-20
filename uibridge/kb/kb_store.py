"""KBStore — YAML-based persistence for knowledge base items"""

import time
from pathlib import Path
from typing import Optional

import yaml

from .kb_item import KBItem, Confidence, KnowledgeSource

CATEGORIES = ["conventions", "components", "patterns", "pages"]


class KBStore:
    """Stores and retrieves KB items in YAML files under .uibridge/kb/"""

    def __init__(self, project_root: str = "."):
        self.root = Path(project_root) / ".uibridge" / "kb"
        for cat in CATEGORIES:
            (self.root / cat).mkdir(parents=True, exist_ok=True)
        (self.root / "archive").mkdir(parents=True, exist_ok=True)

    # ── CRUD ──────────────────────────────────────────

    def save(self, item: KBItem) -> str:
        item.updated_at = time.time()
        d = item.to_dict()
        d["updated_at"] = item.updated_at
        d["created_at"] = item.created_at
        filepath = self._filepath(item)
        with open(filepath, "w", encoding="utf-8") as f:
            yaml.safe_dump(d, f, allow_unicode=True, sort_keys=False)
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
        """Text search with keyword relevance fallback.

        先尝试精确子串匹配。若无结果，退到关键词相关性评分。
        """
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

    # ── Internal ─────────────────────────────────────

    def _filepath(self, item: KBItem) -> Path:
        return self._filepath_for(item.category, item.id)

    def _filepath_for(self, category: str, item_id: str) -> Path:
        return self.root / category / f"{item_id}.yaml"
