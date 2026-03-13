"""
Director prompts for MAX THE DESTROYER.

Loads LLM system prompts from Director/ files.
"""

from pathlib import Path
from typing import Optional

from codestory.core.logging import get_logger

LOGGER = get_logger(__name__)

# Default prompts (fallback if Director files are missing)
FALLBACK_HAIKU_PROMPT = """You are MAX THE DESTROYER — the merciless, sardonic narrator of The codeStory Chronicles.
Turn git commits into 3-act noir case files. Short. Visceral. Cinematic.

Return ONLY a valid JSON array with one object per commit containing:
  full_hash, title, subtitle, when_where, who_whom, what_why, verdict
"""

FALLBACK_EPISODE_PROMPT = """You are MAX THE DESTROYER — the merciless, sardonic narrator of The codeStory Chronicles.
Synthesise 10 git commit haikus into one devastating EPISODE ACT.

Return ONLY a valid JSON object with keys: title, decade_summary, branch_note, max_ruling.
"""


def find_director_dir() -> Optional[Path]:
    """
    Find the Director directory.

    Search order:
    1. ./Director/ (relative to where codeStory is running)
    2. ../Director/ (parent directory)
    3. Built-in (use fallbacks)

    Returns:
        Path to Director directory if found, None otherwise.
    """
    # Check current directory
    for search_path in [Path("."), Path(".."), Path(__file__).parent.parent.parent]:
        director_path = search_path / "Director"
        if director_path.exists() and director_path.is_dir():
            # Verify it has the expected files
            if (director_path / "HaikuDirector.md").exists():
                LOGGER.info("Found Director directory at %s", director_path)
                return director_path

    return None


def load_haiku_prompt() -> str:
    """
    Load MAX THE DESTROYER's haiku brief from Director/HaikuDirector.md.

    Returns:
        System prompt string. Falls back to hardcoded prompt if file missing.
    """
    director_dir = find_director_dir()
    if director_dir:
        prompt_path = director_dir / "HaikuDirector.md"
        if prompt_path.exists():
            try:
                prompt = prompt_path.read_text(encoding="utf-8").strip()
                LOGGER.info("Loaded haiku director prompt (%d chars)", len(prompt))
                return prompt
            except OSError as exc:
                LOGGER.warning("Failed to read HaikuDirector.md: %s", exc)

    LOGGER.warning("HaikuDirector.md not found — using fallback prompt")
    return FALLBACK_HAIKU_PROMPT


def load_episode_prompt() -> str:
    """
    Load MAX THE DESTROYER's episode brief from Director/EpisodeDirector.md.

    Injects Director/RepoStory.md as baseline context.

    Returns:
        Combined system prompt (RepoStory preface + EpisodeDirector brief).
        Falls back to hardcoded prompt if files missing.
    """
    director_dir = find_director_dir()

    # Load RepoStory baseline
    repo_story = ""
    if director_dir:
        repo_story_path = director_dir / "RepoStory.md"
        if repo_story_path.exists():
            try:
                repo_story = repo_story_path.read_text(encoding="utf-8").strip()
                LOGGER.info("Loaded RepoStory baseline (%d chars)", len(repo_story))
            except OSError as exc:
                LOGGER.warning("Failed to read RepoStory.md: %s", exc)

    # Load EpisodeDirector
    episode_prompt = ""
    if director_dir:
        episode_path = director_dir / "EpisodeDirector.md"
        if episode_path.exists():
            try:
                episode_prompt = episode_path.read_text(encoding="utf-8").strip()
                LOGGER.info("Loaded episode director prompt (%d chars)", len(episode_prompt))
            except OSError as exc:
                LOGGER.warning("Failed to read EpisodeDirector.md: %s", exc)

    if not episode_prompt:
        episode_prompt = FALLBACK_EPISODE_PROMPT

    # Combine if RepoStory exists
    if repo_story:
        return (
            "# BASELINE CONTEXT — THE ORIGIN STORY\n\n"
            + repo_story
            + "\n\n---\n\n"
            + episode_prompt
        )

    return episode_prompt
