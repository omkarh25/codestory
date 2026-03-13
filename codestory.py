"""
codeStory CLI Entry Point

This file provides backward compatibility for:
    python codestory.py
    python -m codestory (when package is installed)

The actual code is in src/codestory/
"""

import sys
from pathlib import Path

# Add src to path
src_path = Path(__file__).parent / "src"
if str(src_path) not in sys.path:
    sys.path.insert(0, str(src_path))

# Import and run main from the package
from codestory.__main__ import main

if __name__ == "__main__":
    sys.exit(main())
