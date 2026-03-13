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
        config: Configuration dictionary (must include db_path, yt_output_dir, etc.).

    Returns:
        List of rendered video paths.
    """
    LOGGER.info("Running video rendering pipeline with config: %s", config.get("db_path"))

    try:
        _ensure_legacy_path()
        from ytpipeline import main as ytpipeline_main, load_config
        import sys as _sys

        # Get the db_path from config and pass it to ytpipeline
        db_path = config.get("db_path", "tmChron.db")
        
        # Build args with explicit db_path override
        args = ["ytpipeline", "--all", "--db-path", db_path]
        
        # Also pass render profile if set
        render_profile = config.get("render", {}).get("profile")
        if render_profile:
            args.extend(["--render-profile", render_profile])

        orig_argv = _sys.argv
        try:
            _sys.argv = args
            exit_code = ytpipeline_main()
        finally:
            _sys.argv = orig_argv
            
        if exit_code == 0:
            LOGGER.info("Video rendering complete")
            return []
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
