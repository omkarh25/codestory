"""
PyQt6 viewer for codeStory.

This is a placeholder - the actual viewer code is migrated from codeQT.py.
"""

import sys
from pathlib import Path
from typing import Any, Dict, Optional

from codestory.core.logging import get_logger

LOGGER = get_logger(__name__)


def launch_app(config: Dict[str, Any], start_index: Optional[int] = None) -> int:
    """
    Launch the PyQt6 viewer.

    Args:
        config: Configuration dictionary.
        start_index: Optional 0-based index to start at. If None, starts at newest haiku.

    Returns:
        Exit code.
    """
    LOGGER.info("Launching PyQt6 viewer (start_index=%s)", start_index)

    try:
        # Import the actual viewer from the old location
        # This allows gradual migration
        codestory_root = Path(__file__).parent.parent.parent.parent.resolve()
        if str(codestory_root) not in sys.path:
            sys.path.insert(0, str(codestory_root))
        
        from PyQt6.QtWidgets import QApplication
        
        # Create QApplication in the main thread - this is critical
        app = QApplication.instance()
        if app is None:
            app = QApplication(sys.argv)
        
        from codeQT import MainWindow
        window = MainWindow(config, start_index=start_index)
        window.showFullScreen()
        return app.exec()
    except ImportError as e:
        LOGGER.error("Viewer not available: %s", e)
        print("Error: PyQt6 viewer not available.")
        print("Install with: pip install PyQt6")
        return 1
