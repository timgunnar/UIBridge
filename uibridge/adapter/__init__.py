"""Adapters — framework-specific code generation and action recognition."""

from .loader import load_adapter
from .base import (
    CodeGenerator, ActionRecognizer, ComponentResolver,
    LocatorStrategy, DataFormatter,
    ScriptDef, ComponentDef, BAWDef, TestDataDef,
)
