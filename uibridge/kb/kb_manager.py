"""Backward compatibility shim — use ``from uibridge.kb.manager import ...`` instead."""
import warnings as _w
import logging

logger = logging.getLogger(__name__)
_w.warn("uibridge.kb.kb_manager is deprecated, use uibridge.kb.manager", DeprecationWarning, stacklevel=2)
from .manager import KBManager  # noqa: E402, F401
