"""ProfileStore — 画像 YAML 持久化，带 TTL 缓存和旧路径自动迁移"""

import time
from pathlib import Path
from typing import Optional
import logging

logger = logging.getLogger(__name__)

import yaml

from .profile import FrameworkProfile


class ProfileStore:
    """画像的 YAML 持久化层。

    存储路径: .uibridge/profile.yaml
    旧路径 .uibridge/kb/profile.yaml 存在时自动迁移。

    内置 TTL 内存缓存（默认 5 分钟），避免频繁磁盘读取。
    """

    _CACHE_TTL = 300  # 5 minutes

    def __init__(self, project_root: str = "."):
        self.root = Path(project_root) / ".uibridge"
        self.root.mkdir(parents=True, exist_ok=True)
        self._filepath = self.root / "profile.yaml"
        self._old_filepath = self.root / "kb" / "profile.yaml"
        self._cache: Optional[FrameworkProfile] = None
        self._cache_time: float = 0.0

        # 自动迁移旧路径
        self._migrate_if_needed()

    # ── Migration ──────────────────────────────────────

    def _migrate_if_needed(self):
        """若新旧路径都存在，优先新路径；若仅旧路径存在，迁移到新路径。"""
        new_exists = self._filepath.exists()
        old_exists = self._old_filepath.exists()

        if new_exists:
            return  # 新路径已存在，无需迁移

        if old_exists:
            self._old_filepath.rename(self._filepath)

    # ── Read / Write ───────────────────────────────────

    def save(self, profile: FrameworkProfile) -> str:
        """持久化画像到 .uibridge/profile.yaml，刷新缓存。"""
        d = profile.to_dict()
        d["created_at"] = profile.created_at
        d["version"] = profile.version
        with open(self._filepath, "w", encoding="utf-8") as f:
            yaml.safe_dump(d, f, allow_unicode=True, sort_keys=False)
        # 写后刷新缓存
        self._cache = profile
        self._cache_time = time.time()
        return str(self._filepath)

    def load(self) -> Optional[FrameworkProfile]:
        """加载画像。优先返回缓存，超时后从磁盘重新读取。"""
        now = time.time()
        if self._cache is not None and (now - self._cache_time) < self._CACHE_TTL:
            return self._cache

        if not self._filepath.exists():
            return None

        with open(self._filepath, "r", encoding="utf-8") as f:
            d = yaml.safe_load(f)
        if d is None:
            return None

        profile = FrameworkProfile.from_dict(d)
        self._cache = profile
        self._cache_time = now
        return profile

    def invalidate_cache(self):
        """强制使缓存失效，下次 load() 从磁盘重新读取。"""
        self._cache = None
        self._cache_time = 0.0

    # ── Convenience ────────────────────────────────────

    def exists(self) -> bool:
        """检查画像文件是否存在（新路径或缓存）。"""
        if self._cache is not None:
            return True
        return self._filepath.exists()
