"""agentcheckup - diagnose your agent setup before your agent does."""

from __future__ import annotations

from .conflicts import Conflict, ToolRef, detect_conflicts, lint_conflicts
from .discovery import discover, load_servers
from .engine import Report, lint_audit, lint_servers, lint_tools
from .models import Finding, ServerConfig, Severity, Tool
from .report import __version__

__all__ = [
    "Conflict",
    "Finding",
    "Report",
    "ServerConfig",
    "Severity",
    "Tool",
    "ToolRef",
    "__version__",
    "detect_conflicts",
    "discover",
    "lint_audit",
    "lint_conflicts",
    "lint_servers",
    "lint_tools",
    "load_servers",
]
