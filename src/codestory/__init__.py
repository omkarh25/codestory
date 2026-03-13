# This app has one job: witness the present moment.
# Everything else is archaeology.

"""
codeStory - Turn your git history into a cinematic noir crime thriller.

Every commit is a confession. Every repo is a crime scene.
codeStory is the detective.

Usage:
    codestory --generate-haikus
    codestory --play
    codestory --status
"""

__version__ = "0.1.0"
__author__ = "Omkar H"
__description__ = "Turn git history into cinematic noir haikus and episodes"

from codestory.core.config import load_config
from codestory.core.database import DatabaseManager

__all__ = [
    "__version__",
    "load_config",
    "DatabaseManager",
]
