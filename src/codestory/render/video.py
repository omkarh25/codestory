"""
Video rendering for codeStory YouTube Shorts.

This is a placeholder - the actual rendering code is in ytpipeline.py.
"""

from typing import Any, Dict, List, Optional

from pathlib import Path
import sys

from codestory.core.logging import get_logger

LOGGER = get_logger(__name__)


def _ensure_legacy_path():
    """Ensure the project root is in sys.path for legacy modules."""
    root_path = Path(__file__).parent.parent.parent.parent.resolve()
    if str(root_path) not in sys.path:
        sys.path.insert(0, str(root_path))


def render_all(config: Dict[str, Any]) -> List[str]:
    """
    Render all unrendered haikus and episodes to video.

    Args:
        config: Configuration dictionary.

    Returns:
        List of rendered video paths.
    """
    LOGGER.info("Running video rendering pipeline")

    try:
        _ensure_legacy_path()
        from ytpipeline import main as ytpipeline_main
        # Pass clean args to ytpipeline — ignore parent CLI flags like --release_dry_run
        import sys as _sys
        orig_argv = _sys.argv
        try:
            _sys.argv = ["ytpipeline", "--all"]
            exit_code = ytpipeline_main()
        finally:
            _sys.argv = orig_argv
        if exit_code == 0:
            LOGGER.info("Video rendering complete")
            return []  # ytpipeline prints its own output
        return []
    except ImportError as exc:
        LOGGER.error("ytpipeline not available: %s", exc)
        print("Error: ytpipeline not available")
        return []


def render_haiku(haiku: Dict[str, Any], config: Dict[str, Any]) -> Optional[str]:
    """Render a single haiku to video."""
    try:
        _ensure_legacy_path()
        from ytpipeline import render_haiku as old_render_haiku
        result = old_render_haiku(haiku, config)
        return str(result) if result else None
    except ImportError:
        LOGGER.error("ytpipeline not available")
        return None


def render_episode(episode: Dict[str, Any], config: Dict[str, Any]) -> Optional[str]:
    """Render a single episode to video."""
    try:
        _ensure_legacy_path()
        from ytpipeline import render_episode as old_render_episode
        result = old_render_episode(episode, config)
        return str(result) if result else None
    except ImportError:
        LOGGER.error("ytpipeline not available")
        return None
