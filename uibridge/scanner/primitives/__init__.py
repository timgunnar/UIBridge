"""Scanner primitives — atomic analysis operations.

Each primitive performs one specific extraction task on source files.
Designed to be composed into higher-level analysis pipelines.

Primitives:
  FileScanner       — glob scan, classify files by type
  InheritanceAnalyzer — extract extends/implements relationships
  CallAnalyzer      — extract method invocations
  AnnotationExtractor — extract annotations/decorators
  PatternMiner      — PrefixSpan stub for frequent subsequence mining
  StatisticsCollector — naming distribution, import frequency
  LocatorExtractor  — extract XPath/CSS/@FindBy locators
"""

from .file_scan import FileScanner
from .inheritance import InheritanceAnalyzer
from .calls import CallAnalyzer
from .annotations import AnnotationExtractor
from .patterns import PatternMiner
from .statistics import StatisticsCollector
from .locators import LocatorExtractor

__all__ = [
    "FileScanner",
    "InheritanceAnalyzer",
    "CallAnalyzer",
    "AnnotationExtractor",
    "PatternMiner",
    "StatisticsCollector",
    "LocatorExtractor",
]
