"""KBExtractor — backward-compatible re-export shim.

The implementation has moved to kb/extractor/ (mixin-based sub-package).
"""

import logging

logger = logging.getLogger(__name__)

from .extractor import KBExtractor

__all__ = ["KBExtractor"]
