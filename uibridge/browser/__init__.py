"""Browser layer — Playwright-based browser management, recording, and page analysis."""

from .recorder import RecordingSession
from .recorder_js import RECORDER_JS
from .runtime_analyzer import RuntimeAnalyzer, RuntimeReport, NetworkEntry
from .aria_analyzer import AriaAnalyzer, DiscoveredComponent
from .dom_diff import DOMDiffer, DOMDiffResult, DiffEntry, AriaNode
from .self_test import SelfTestRunner, SelfTestResult
from .state import BrowserState
from .discovery import DiscoveryService

from .ir import (
    RawRecording, RawStep, ActionType, Target, SelectorSet, Snapshot,
    SemanticActionSequence, SemanticScenario, SemanticAction,
    FrameworkCallSequence, TestCaseIR, FrameworkStep, MethodCall, StepKind, Decl,
)
