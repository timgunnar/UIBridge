"""Engine — recording, DOM analysis, ARIA analysis, self-testing, and runtime analysis."""

from .recorder import RecordingSession
from .aria_analyzer import AriaAnalyzer
from .runtime_analyzer import RuntimeAnalyzer
from .dom_diff import DOMDiffer
from .self_test import SelfTestRunner
