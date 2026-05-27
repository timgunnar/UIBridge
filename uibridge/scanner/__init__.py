"""Project scanner — auto-discovery + tree-sitter AST extraction.

Phase 1: Auto-detect project structure → ProjectProfile
Phase 2: Deep extraction with 7 primitives (file_scan, inheritance, calls,
         annotations, patterns, statistics, locators)

Usage:
    from uibridge.scanner import Scanner, ProjectProfile, ProfileField

    scanner = Scanner()
    profile = scanner.discover("/path/to/project")
    print(profile.project_type.value)     # "java_maven"
    print(profile.profile_confidence)     # 0.72
    print(profile.to_dict())
"""

from .discover import Scanner, ProjectProfile, ProfileField
from .parser import UnifiedAST, parse_file, ASTNode
from .primitives import (
    FileScanner,
    InheritanceAnalyzer,
    CallAnalyzer,
    AnnotationExtractor,
    PatternMiner,
    StatisticsCollector,
    LocatorExtractor,
)

__all__ = [
    # Core
    "Scanner",
    "ProjectProfile",
    "ProfileField",
    # Parser
    "UnifiedAST",
    "parse_file",
    "ASTNode",
    # Primitives
    "FileScanner",
    "InheritanceAnalyzer",
    "CallAnalyzer",
    "AnnotationExtractor",
    "PatternMiner",
    "StatisticsCollector",
    "LocatorExtractor",
]
