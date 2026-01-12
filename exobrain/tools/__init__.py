"""Tool modules for ExoBrain.

This module imports all tool implementations to trigger @register_tool decorators.
Tools are automatically discovered and registered via the decorator pattern.
"""

# Import all tool modules to trigger registration
# NOTE: Import order doesn't matter, but we organize by category for clarity
from exobrain.tools import context7_tools  # Context7 search integration
from exobrain.tools import file_tools  # File system operations
from exobrain.tools import location_tools  # Location services
from exobrain.tools import math_tools  # Mathematical evaluation
from exobrain.tools import pdf_tools  # PDF processing
from exobrain.tools import shell_tools  # Shell command execution and OS info
from exobrain.tools import skill_tools  # Skill management tools
from exobrain.tools import time_tools  # Time and timezone tools
from exobrain.tools import web_tools  # Web search and fetch

__all__ = [
    "context7_tools",
    "file_tools",
    "location_tools",
    "math_tools",
    "pdf_tools",
    "shell_tools",
    "skill_tools",
    "time_tools",
    "web_tools",
]
