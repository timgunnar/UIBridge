"""Knowledge Base — explicit, NL-editable framework knowledge layer

Profile classes live in uibridge.profile (re-exported here for backward compat).
"""

from .item import KBItem, Confidence, KnowledgeSource
from .store import KBStore
from .extractor import KBExtractor
from .manager import KBManager
from ..profile import FrameworkProfile, ProfileField  # re-export for backward compat
