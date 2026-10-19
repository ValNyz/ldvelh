"""
LDVELH - Specialized Extraction Package
Parallel extractors triggered by the narrator's extraction_triggers field.
"""

from .orchestrator import run_resolve_and_extract

__all__ = ["run_resolve_and_extract"]
