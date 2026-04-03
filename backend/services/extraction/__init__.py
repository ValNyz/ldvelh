"""
LDVELH - Specialized Extraction Package
Parallel extractors triggered by the narrator's extraction_triggers field.
"""

from .orchestrator import run_triggered_extraction

__all__ = ["run_triggered_extraction"]
