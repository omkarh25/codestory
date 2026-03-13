"""
Configuration management for codeStory.

Loads configuration from config.json with sensible defaults.
Supports both root-level and repo-level (.codestory/) config files.
"""

import json
import os
from pathlib import Path
from typing import Any, Dict, Optional

from codestory.core.logging import get_logger

LOGGER = get_logger(__name__)

# Default configuration values
DEFAULTS: Dict[str, Any] = {
    "repo_path": ".",
    "db_path": ".codestory/codestory.db",
    "output_dir": ".codestory/assets",
    "haiku": {
        "provider": "anthropic",
        "model": "claude-haiku-4-5-20251001",
        "depth": "git_commit",
        "max_per_run": 12,
        "batch_size": 3,
    },
    "episode": {
        "provider": "anthropic",
        "model": "claude-haiku-4-5-20251001",
        "depth": "git_commit",
        "haikus_per_episode": 10,
    },
    "yt_shorts": {
        "slide_duration": 2.5,
        "verdict_duration": 4.0,
        "fps": 30,
        "resolution": "1920x1080",
        "output_dir": ".codestory/assets/videos",
    },
    "audio": {
        # BGM track played under haiku videos (looped to fit).
        # Defaults to GarageBand's Kyoto Night Synth — loopable, royalty-free.
        # Set to null or "" to disable audio.
        "track_path": "/Library/Audio/Apple Loops/Apple/07 Chillwave/Kyoto Night Synth.caf",
        # BGM track for episode compilation videos (more dramatic).
        "episode_track_path": "/Library/Audio/Apple Loops/Apple/07 Chillwave/Ghost Harmonics Synth.caf",
        "volume": 0.3,
        "fade_in_s": 1.0,
        "fade_out_s": 1.5,
    },
    "render": {
        # "minimal" → no audio (fast, for testing)
        # "short"   → audio BGM + director's cut MD (default)
        "profile": "short",
        "write_casefile_md": True,
    },
    "oldest_first": True,
}


def find_config_file(start_path: Optional[Path] = None) -> Optional[Path]:
    """
    Find the config.json file by searching upward from start_path.

    Search order:
    1. .codestory/config.json in repo root
    2. config.json in repo root

    Args:
        start_path: Starting path for search (default: cwd).

    Returns:
        Path to config file if found, None otherwise.
    """
    if start_path is None:
        start_path = Path.cwd()

    # Search upward from start_path
    current = start_path.resolve()
    while current != current.parent:
        # Check .codestory/config.json first (repo-level)
        repo_config = current / ".codestory" / "config.json"
        if repo_config.exists():
            LOGGER.info("Found repo-level config: %s", repo_config)
            return repo_config

        # Check config.json in root
        root_config = current / "config.json"
        if root_config.exists():
            LOGGER.info("Found root config: %s", root_config)
            return root_config

        current = current.parent

    return None


def load_config(
    config_path: Optional[Path] = None,
    overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Load configuration from JSON file with defaults and overrides.

    Args:
        config_path: Explicit path to config file. If None, searches for it.
        overrides: Optional dict of values to override config file.

    Returns:
        Merged configuration dictionary with all paths resolved.
    """
    # Start with defaults
    config = DEFAULTS.copy()

    # Find and load config file if not explicitly provided
    if config_path is None:
        config_path = find_config_file()

    if config_path and config_path.exists():
        try:
            with open(config_path, "r") as f:
                raw = json.load(f)
            
            # Handle both "codestory" and "tmChronicles" keys for backwards compat
            cfg = raw.get("codestory", raw.get("tmChronicles", {}))
            
            # Resolve relative paths to absolute (relative to config file location)
            config_dir = config_path.parent
            for key in ("db_path", "output_dir"):
                if key in cfg:
                    if not Path(cfg[key]).is_absolute():
                        cfg[key] = str(config_dir.parent / cfg[key])
            
            config.update(cfg)
            LOGGER.info("Config loaded from %s", config_path)
        except (FileNotFoundError, json.JSONDecodeError) as exc:
            LOGGER.warning("Config file not loaded: %s — using defaults", exc)

    # Apply environment variable overrides
    env_overrides = _load_env_overrides()
    config.update(env_overrides)

    # Apply explicit overrides last
    if overrides:
        config.update({k: v for k, v in overrides.items() if v is not None})

    # Ensure paths are absolute
    config = _resolve_paths(config)

    return config


def _load_env_overrides() -> Dict[str, Any]:
    """
    Load configuration overrides from environment variables.

    Environment variables:
    - CODESTORY_REPO_PATH
    - CODESTORY_DB_PATH
    - CODESTORY_HAIKU_PROVIDER
    - CODESTORY_HAIKU_MODEL
    - CODESTORY_HAIKU_DEPTH
    - CODESTORY_EPISODE_PROVIDER
    - CODESTORY_EPISODE_MODEL
    - CODESTORY_EPISODE_DEPTH

    Returns:
        Dictionary of environment-based overrides.
    """
    overrides: Dict[str, Any] = {}
    env_map = {
        "CODESTORY_REPO_PATH": ("repo_path",),
        "CODESTORY_DB_PATH": ("db_path",),
        "CODESTORY_HAIKU_PROVIDER": ("haiku", "provider"),
        "CODESTORY_HAIKU_MODEL": ("haiku", "model"),
        "CODESTORY_HAIKU_DEPTH": ("haiku", "depth"),
        "CODESTORY_EPISODE_PROVIDER": ("episode", "provider"),
        "CODESTORY_EPISODE_MODEL": ("episode", "model"),
        "CODESTORY_EPISODE_DEPTH": ("episode", "depth"),
    }

    for env_var, path in env_map.items():
        value = os.getenv(env_var)
        if value:
            if len(path) == 1:
                overrides[path[0]] = value
            elif len(path) == 2:
                if path[0] not in overrides:
                    overrides[path[0]] = {}
                overrides[path[0]][path[1]] = value

    return overrides


def _resolve_paths(config: Dict[str, Any]) -> Dict[str, Any]:
    """
    Resolve relative paths to absolute paths in configuration.

    Args:
        config: Configuration dictionary.

    Returns:
        Configuration with resolved absolute paths.
    """
    # Get base directory from repo_path
    base_path = Path(config.get("repo_path", ".")).resolve()

    path_keys = ["db_path", "output_dir"]
    
    # Handle yt_shorts paths
    if "yt_shorts" in config and "output_dir" in config["yt_shorts"]:
        path_keys.append(("yt_shorts", "output_dir"))

    for key in path_keys:
        if isinstance(key, tuple):
            # Nested path like ("yt_shorts", "output_dir")
            if key[0] in config and key[1] in config[key[0]]:
                path = Path(config[key[0]][key[1]])
                if not path.is_absolute():
                    config[key[0]][key[1]] = str(base_path / path)
        else:
            if key in config:
                path = Path(config[key])
                if not path.is_absolute():
                    config[key] = str(base_path / path)

    return config


def init_repo_config(repo_path: Path) -> Path:
    """
    Initialize .codestory folder structure in a repository.

    Creates:
    - .codestory/config.json
    - .codestory/codestory.db (empty)
    - .codestory/assets/haikus/
    - .codestory/assets/episodes/
    - .codestory/assets/videos/
    - .codestory/logs/

    Args:
        repo_path: Path to the repository root.

    Returns:
        Path to the created config file.
    """
    codestory_dir = repo_path / ".codestory"
    codestory_dir.mkdir(parents=True, exist_ok=True)

    # Create subdirectories
    (codestory_dir / "assets" / "haikus").mkdir(parents=True, exist_ok=True)
    (codestory_dir / "assets" / "episodes").mkdir(parents=True, exist_ok=True)
    (codestory_dir / "assets" / "videos").mkdir(parents=True, exist_ok=True)
    (codestory_dir / "logs").mkdir(parents=True, exist_ok=True)

    # Create default config
    config_path = codestory_dir / "config.json"
    if not config_path.exists():
        default_config = {
            "codestory": {
                "repo_path": str(repo_path),
                "db_path": str(codestory_dir / "codestory.db"),
                "output_dir": str(codestory_dir / "assets"),
                "haiku": DEFAULTS["haiku"],
                "episode": DEFAULTS["episode"],
                "yt_shorts": DEFAULTS["yt_shorts"],
                "oldest_first": True,
            }
        }
        with open(config_path, "w") as f:
            json.dump(default_config, f, indent=4)
        LOGGER.info("Created repo config at %s", config_path)

    return config_path
