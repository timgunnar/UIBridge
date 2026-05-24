"""Backward compatibility shim — use ``from uibridge.kb.evolution import ...`` instead."""
import warnings as _w
import logging

logger = logging.getLogger(__name__)
_w.warn("uibridge.kb.kb_evolution is deprecated, use uibridge.kb.evolution", DeprecationWarning, stacklevel=2)
from .evolution import KBEvolution  # noqa: E402, F401
