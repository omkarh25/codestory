"""
codestory.py — The codeStory CLI Entry Point

The main command-line interface for codeStory. Supports running the haiku
pipeline, episode pipeline, launching the PyQt6 viewer, resetting the DB,
and installing a git commit hook — all from the terminal.

CI/CD ready: all commands return meaningful exit codes.

Usage examples:
    python codestory.py --play
    python codestory.py --generate-haikus
    python codestory.py --generate-haikus --depth git_diff --max 5
    python codestory.py --generate-episodes --depth git_diff
    python codestory.py --generate-haikus --generate-episodes --play
    python codestory.py --reset-db
    python codestory.py --repo /path/to/other/repo --generate-haikus
    python codestory.py --install-hook
    python codestory.py --status
"""

import argparse
import json
import logging
import os
import shutil
import sqlite3
import sys
from pathlib import Path

# ─── Path setup ───────────────────────────────────────────────────────────────
_REPO_ROOT = Path(__file__).resolve().parent

try:
    from dotenv import load_dotenv
    load_dotenv(dotenv_path=_REPO_ROOT / "llm.env")
except ImportError:
    pass

LOGGER = logging.getLogger(__name__)


# ─── Config helper ────────────────────────────────────────────────────────────

def _load_config() -> dict:
    """Load tmChronicles section from config.json.

    Returns:
        Config dict with resolved absolute paths. Uses sensible defaults
        if config.json is missing or malformed.
    """
    defaults = {
        "repo_path": str(_REPO_ROOT),
        "db_path": str(_REPO_ROOT / "tmChron.db"),
        "output_dir": str(_REPO_ROOT / "Assets" / "haikuJSON"),
        "haiku_provider": "anthropic",
        "haiku_model": "claude-haiku-4-5-20251001",
        "haiku_depth": "git_commit",
        "episode_provider": "anthropic",
        "episode_model": "claude-haiku-4-5-20251001",
        "episode_depth": "git_commit",
        "max_haiku_per_run": 12,
        "haiku_per_episode": 10,
        "oldest_first": True,
    }
    config_path = _REPO_ROOT / "config.json"
    try:
        with open(config_path) as f:
            raw = json.load(f)
        cfg = raw.get("tmChronicles", {})
        for key in ("db_path", "output_dir", "repo_path"):
            if key in cfg and not Path(cfg[key]).is_absolute():
                cfg[key] = str(_REPO_ROOT / cfg[key])
        defaults.update(cfg)
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        LOGGER.warning("config.json not loaded: %s — using defaults", exc)
    return defaults


# ─── Commands ─────────────────────────────────────────────────────────────────

def cmd_status(cfg: dict) -> int:
    """Print current DB status: haiku count, episode count, pending haikus.

    Args:
        cfg: Config dict from _load_config().

    Returns:
        Exit code (0 = success).
    """
    db_path = cfg["db_path"]
    print("🎬 codeStory Status")
    print("=" * 50)
    print(f"  Repo:    {cfg.get('repo_path', '.')}")
    print(f"  DB:      {db_path}")
    print(f"  Model:   {cfg.get('haiku_model', '?')} ({cfg.get('haiku_provider', '?')})")
    print(f"  Depth:   haiku={cfg.get('haiku_depth')}  episode={cfg.get('episode_depth')}")

    if not Path(db_path).exists():
        print("\n  DB not initialised yet. Run --generate-haikus to start.")
        return 0

    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row

        total_haikus = conn.execute("SELECT COUNT(*) FROM haiku_commits").fetchone()[0]
        pending = conn.execute(
            "SELECT COUNT(*) FROM haiku_commits WHERE compiled_into_episode = 0"
        ).fetchone()[0]
        total_episodes = conn.execute("SELECT COUNT(*) FROM chronicle_episodes").fetchone()[0]
        conn.close()

        print(f"\n  Haikus:   {total_haikus} total  ({pending} pending → next episode)")
        print(f"  Episodes: {total_episodes} generated")
        haiku_per_ep = int(cfg.get("haiku_per_episode", 10))
        if pending >= haiku_per_ep:
            print(f"\n  ✓ Ready to generate next episode ({pending}/{haiku_per_ep} haikus available)")
        else:
            print(f"\n  Need {haiku_per_ep - pending} more haikus before next episode.")
    except sqlite3.OperationalError as exc:
        print(f"\n  DB error: {exc}")
    return 0


def cmd_reset_db(cfg: dict) -> int:
    """Delete tmChron.db for a completely fresh start.

    Args:
        cfg: Config dict from _load_config().

    Returns:
        Exit code (0 = success).
    """
    db_path = Path(cfg["db_path"])
    if db_path.exists():
        db_path.unlink()
        print(f"✓ Database reset: {db_path}")
        LOGGER.info("Database deleted: %s", db_path)
    else:
        print(f"  No database found at {db_path} (already clean)")
    return 0


def cmd_generate_haikus(cfg: dict) -> int:
    """Run the haiku pipeline for new commits.

    Args:
        cfg: Config dict (haiku_depth, max_haiku_per_run, etc.)

    Returns:
        Exit code (0 = success, 1 = error, 2 = no new commits).
    """
    LOGGER.info("Running haiku pipeline with config: %s", cfg)
    try:
        from git_commit_haiku import fetch_actions
        results = fetch_actions(config=cfg)
        if not results:
            print("[haiku] No new haikus generated (no new commits or error).")
            return 2
        print(f"\n[haiku] ✓ {len(results)} haiku(s) generated.")
        return 0
    except Exception as exc:
        LOGGER.error("Haiku generation failed: %s", exc)
        print(f"[haiku] ERROR: {exc}")
        return 1


def cmd_generate_episodes(cfg: dict) -> int:
    """Run the episode pipeline to compile pending haikus.

    Args:
        cfg: Config dict (episode_depth, haiku_per_episode, etc.)

    Returns:
        Exit code (0 = success, 1 = error, 2 = not enough haikus).
    """
    LOGGER.info("Running episode pipeline with config: %s", cfg)
    try:
        from changelog_episodes import fetch_actions
        results = fetch_actions(config=cfg)
        if not results:
            print("[episode] No episode generated (not enough haikus or error).")
            return 2
        print(f"\n[episode] ✓ Episode generated: {results[0]['title']}")
        return 0
    except Exception as exc:
        LOGGER.error("Episode generation failed: %s", exc)
        print(f"[episode] ERROR: {exc}")
        return 1


def cmd_play(cfg: dict) -> int:
    """Launch the PyQt6 codeStory viewer.

    Args:
        cfg: Config dict (db_path, etc.)

    Returns:
        Exit code from the Qt application.
    """
    LOGGER.info("Launching PyQt6 viewer")
    try:
        from codeQT import launch_app
        return launch_app(cfg)
    except ImportError as exc:
        print(f"[play] ERROR: PyQt6 not available — {exc}")
        print("  Install with: pip install PyQt6")
        return 1
    except Exception as exc:
        LOGGER.error("Viewer launch failed: %s", exc)
        print(f"[play] ERROR: {exc}")
        return 1


def cmd_install_hook(cfg: dict) -> int:
    """Install a git post-commit hook to auto-generate haikus.

    The hook calls: python codestory.py --generate-haikus --max 1
    using the conda macenv environment.

    Args:
        cfg: Config dict (repo_path, etc.)

    Returns:
        Exit code (0 = success, 1 = error).
    """
    repo_path = Path(cfg.get("repo_path", _REPO_ROOT))
    hooks_dir = repo_path / ".git" / "hooks"
    hook_path = hooks_dir / "post-commit"

    if not hooks_dir.exists():
        print(f"[hook] ERROR: No .git/hooks directory in {repo_path}")
        print("  Is this a git repository?")
        return 1

    codestory_path = _REPO_ROOT / "codestory.py"
    hook_content = f"""#!/bin/bash
# codeStory — auto-generate haiku on every commit
# Installed by: python codestory.py --install-hook

conda run -n macenv python "{codestory_path}" --generate-haikus --max 1 2>/dev/null &
disown
"""
    hook_path.write_text(hook_content, encoding="utf-8")
    hook_path.chmod(0o755)
    print(f"✓ Git commit hook installed: {hook_path}")
    print("  Every commit will now auto-generate a haiku in the background.")
    LOGGER.info("Post-commit hook installed at %s", hook_path)
    return 0


# ─── CLI argument parsing ─────────────────────────────────────────────────────

def build_arg_parser() -> argparse.ArgumentParser:
    """Build the full argument parser for codeStory CLI.

    Returns:
        Configured ArgumentParser with all subcommands and flags.
    """
    parser = argparse.ArgumentParser(
        prog="codestory",
        description=(
            "🎬 codeStory — turn your git history into a cinematic noir crime thriller\n\n"
            "Every commit is a confession. Every repo is a crime scene.\n"
            "codeStory is the detective."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
examples:
  python codestory.py --play                              # launch viewer
  python codestory.py --generate-haikus                  # generate haikus
  python codestory.py --generate-haikus --depth git_diff # use full git diff
  python codestory.py --generate-episodes                # compile haikus to episode
  python codestory.py --generate-haikus --play           # pipeline + play
  python codestory.py --repo /path/to/repo --generate-haikus
  python codestory.py --status                           # show DB stats
  python codestory.py --reset-db                         # wipe DB
  python codestory.py --install-hook                     # auto-haiku on commits
        """,
    )

    # ── Pipeline commands ──────────────────────────────────────────────────────
    pipeline = parser.add_argument_group("pipeline")
    pipeline.add_argument(
        "-g", "--generate-haikus",
        action="store_true",
        help="Generate haikus for new commits",
    )
    pipeline.add_argument(
        "-e", "--generate-episodes",
        action="store_true",
        help="Compile pending haikus into an episode act",
    )

    # ── Viewer ─────────────────────────────────────────────────────────────────
    viewer = parser.add_argument_group("viewer")
    viewer.add_argument(
        "-p", "--play",
        action="store_true",
        help="Launch the PyQt6 cinematic viewer",
    )

    # ── Depth ──────────────────────────────────────────────────────────────────
    depth = parser.add_argument_group("depth (configures how much git context the LLM receives)")
    depth.add_argument(
        "-d", "--depth",
        choices=["git_commit", "git_diff"],
        default=None,
        help="Analysis depth: git_commit (message only) or git_diff (full diff + names)",
    )

    # ── Targeting ──────────────────────────────────────────────────────────────
    targeting = parser.add_argument_group("targeting")
    targeting.add_argument(
        "-r", "--repo",
        default=None,
        metavar="PATH",
        help="Path to git repository (default: config.json repo_path)",
    )
    targeting.add_argument(
        "--max",
        type=int,
        default=None,
        metavar="N",
        help="Max haikus to generate per run (overrides config.json)",
    )
    targeting.add_argument(
        "--model",
        default=None,
        help="Override LLM model (applies to both haiku + episode)",
    )

    # ── Utility ────────────────────────────────────────────────────────────────
    utility = parser.add_argument_group("utility")
    utility.add_argument(
        "--status",
        action="store_true",
        help="Show DB status (haiku count, episode count, pending)",
    )
    utility.add_argument(
        "--reset-db",
        action="store_true",
        help="Delete the database for a fresh start (irreversible)",
    )
    utility.add_argument(
        "--install-hook",
        action="store_true",
        help="Install a git post-commit hook to auto-generate haikus",
    )

    # ── Logging ────────────────────────────────────────────────────────────────
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable verbose logging",
    )

    return parser


# ─── Main ─────────────────────────────────────────────────────────────────────

def main() -> int:
    """Main entry point for the codeStory CLI.

    Parses arguments, builds config overrides, and dispatches to the
    appropriate command functions in the correct order.

    Returns:
        Exit code (0 = success, non-zero = error).
    """
    parser = build_arg_parser()
    args = parser.parse_args()

    # Set up logging
    log_level = logging.DEBUG if args.verbose else logging.WARNING
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )

    # Show help if no command given
    if not any([
        args.generate_haikus, args.generate_episodes, args.play,
        args.status, args.reset_db, args.install_hook,
    ]):
        parser.print_help()
        return 0

    # Load and merge config
    cfg = _load_config()

    # Apply CLI overrides
    if args.repo:
        cfg["repo_path"] = str(Path(args.repo).resolve())
        LOGGER.info("Repo overridden to: %s", cfg["repo_path"])
    if args.depth:
        cfg["haiku_depth"] = args.depth
        cfg["episode_depth"] = args.depth
        LOGGER.info("Depth overridden to: %s", args.depth)
    if args.max:
        cfg["max_haiku_per_run"] = args.max
        LOGGER.info("Max haiku per run: %d", args.max)
    if args.model:
        cfg["haiku_model"] = args.model
        cfg["episode_model"] = args.model
        LOGGER.info("Model overridden to: %s", args.model)

    # ── Dispatch ──────────────────────────────────────────────────────────────
    exit_code = 0

    if args.status:
        return cmd_status(cfg)

    if args.reset_db:
        code = cmd_reset_db(cfg)
        if code != 0:
            return code

    if args.install_hook:
        code = cmd_install_hook(cfg)
        if code != 0:
            return code

    if args.generate_haikus:
        code = cmd_generate_haikus(cfg)
        if code == 1:  # hard error
            return code
        exit_code = max(exit_code, code)

    if args.generate_episodes:
        code = cmd_generate_episodes(cfg)
        if code == 1:  # hard error
            return code
        exit_code = max(exit_code, code)

    if args.play:
        return cmd_play(cfg)

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
