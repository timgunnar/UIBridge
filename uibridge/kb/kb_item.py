"""Backward compatibility shim — use ``from uibridge.kb.item import ...`` instead."""
import warnings as _w
import logging

logger = logging.getLogger(__name__)
_w.warn("uibridge.kb.kb_item is deprecated, use uibridge.kb.item", DeprecationWarning, stacklevel=2)
from .item import KBItem, Confidence, KnowledgeSource  # noqa: E402, F401
