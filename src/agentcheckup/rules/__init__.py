"""Rule registry bootstrap.

Importing this package registers every rule. Order matters only for output
grouping, not for correctness.
"""

from __future__ import annotations

from . import config_rules, docs, injection, naming, safety, schema  # noqa: F401
from .base import CONFIG_RULES, SUITE_RULES, TOOL_RULES

__all__ = ["CONFIG_RULES", "SUITE_RULES", "TOOL_RULES"]
