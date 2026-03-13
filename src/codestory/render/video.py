"""
Video rendering for codeStory YouTube Shorts.

This is a placeholder - the actual rendering code is in ytpipeline.py.
"""

from typing import Any, Dict, List, Optional

from codestory.core.logging import get_logger

LOGGER = get_logger(__name__)


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
        from ytpipeline import main as ytpipeline_main
        exit_code = ytpipeline_main()
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
        from ytpipeline import render_haiku as old_render_haiku
        result = old_render_haiku(haiku, config)
        return str(result) if result else None
    except ImportError:
        LOGGER.error("ytpipeline not available")
        return None


def render_episode(episode: Dict[str, Any], config: Dict[str, Any]) -> Optional[str]:
    """Render a single episode to video."""
    try:
        from ytpipeline import render_episode as old_render_episode
        result = old_render_episode(episode, config)
        return str(result) if result else None
    except ImportError:
        LOGGER.error("ytpipeline not available")
        return None
