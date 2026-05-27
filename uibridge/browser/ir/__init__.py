"""Intermediate Representations — structured data flowing through the pipeline."""

from .raw_recording import (
    RawRecording, RawStep, ActionType, Target, SelectorSet, Snapshot,
)
from .semantic_action import (
    SemanticActionSequence, SemanticScenario, SemanticAction,
)
from .framework_call import (
    FrameworkCallSequence, TestCaseIR, FrameworkStep, MethodCall, StepKind, Decl,
)
