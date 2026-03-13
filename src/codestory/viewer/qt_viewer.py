"""
PyQt6 viewer for codeStory.

This is a placeholder - the actual viewer code is migrated from codeQT.py.
"""

import sys
from pathlib import Path
from typing import Any, Dict

from codestory.core.logging import get_logger

LOGGER = get_logger(__name__)


def launch_app(config: Dict[str, Any]) -> int:
    """
    Launch the PyQt6 viewer.

    Args:
        config: Configuration dictionary.

    Returns:
        Exit code.
    """
    LOGGER.info("Launching PyQt6 viewer")

    try:
        # Import the actual viewer from the old location
        # This allows gradual migration
        codestory_root = Path(__file__).parent.parent.parent.parent.resolve()
        if str(codestory_root) not in sys.path:
            sys.path.insert(0, str(codestory_root))
        
        from codeQT import launch_app as old_launch_app
        return old_launch_app(config)
    except ImportError as e:
        LOGGER.error("Viewer not available: %s", e)
        print("Error: PyQt6 viewer not available.")
        print("Install with: pip install PyQt6")
        return 1
