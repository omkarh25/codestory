"""
codeStory render module — Director's Cut video & markdown pipeline.

Modules:
  video      - YouTube Shorts MP4 rendering (delegates to ytpipeline)
  markdown   - Director's Cut casefile .md writer
  storyboard - Storyboard JSON generator (deterministic + LLM-powered)
"""

from codestory.render.video import render_all, render_haiku, render_episode
from codestory.render.markdown import write_cinematic_casefile
from codestory.render.storyboard import (
    build_haiku_storyboard,
    build_episode_storyboard_default,
    generate_episode_storyboard_llm,
    save_storyboard,
    load_storyboard,
    storyboard_path_for_episode,
    storyboard_path_for_haiku,
)

__all__ = [
    # Video rendering
    "render_all",
    "render_haiku",
    "render_episode",
    # Director's Cut markdown
    "write_cinematic_casefile",
    # Storyboard pipeline
    "build_haiku_storyboard",
    "build_episode_storyboard_default",
    "generate_episode_storyboard_llm",
    "save_storyboard",
    "load_storyboard",
    "storyboard_path_for_episode",
    "storyboard_path_for_haiku",
]
