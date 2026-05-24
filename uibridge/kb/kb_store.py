"""Backward compatibility shim — use ``from uibridge.kb.store import ...`` instead."""
import warnings as _w
import logging

logger = logging.getLogger(__name__)
_w.warn("uibridge.kb.kb_store is deprecated, use uibridge.kb.store", DeprecationWarning, stacklevel=2)
from .store import KBStore  # noqa: E402, F401
