"""
CLI argument parsing for codeStory.

Provides argument parsing with subcommands and options.
"""

import argparse
from typing import Optional


def build_arg_parser() -> argparse.ArgumentParser:
    """
    Build the full argument parser for codeStory CLI.

    Returns:
        Configured ArgumentParser with all subcommands and flags.
    """
    parser = argparse.ArgumentParser(
        prog="codestory",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
examples:
  codestory --play                              # launch viewer
  codestory --generate-haikus                  # generate haikus
  codestory --generate-haikus --depth git_diff # use full git diff
  codestory --generate-episodes                # compile haikus to episode
  codestory --generate-haikus --play           # pipeline + play
  codestory --repo /path/to/repo --generate-haikus
  codestory --status                           # show DB stats
  codestory --reset-db                         # wipe DB
  codestory --init                             # initialize .codestory folder
  codestory --sync                             # repair DB-filesystem sync
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
    pipeline.add_argument(
        "--generate-ytshorts",
        action="store_true",
        help="Render haikus and episodes to MP4 videos (YouTube Shorts)",
    )
    pipeline.add_argument(
        "--generate-storyboard",
        action="store_true",
        help="Generate Director's Cut storyboard JSON for latest episode (uses ReleaseCutDirector LLM)",
    )
    pipeline.add_argument(
        "--render-profile",
        choices=["minimal", "short"],
        default=None,
        metavar="PROFILE",
        help="Render complexity: minimal (no audio, fast) | short (BGM + casefile MD, default)",
    )

    # ── Commit & Push ─────────────────────────────────────────────────────────
    commit_push = parser.add_argument_group("commit & push")
    commit_push.add_argument(
        "--commit",
        action="store_true",
        help="Generate LLM commit message from diff, commit, and generate haiku",
    )
    commit_push.add_argument(
        "--push",
        action="store_true",
        help="Commit changes, push to remote, and generate haiku",
    )
    commit_push.add_argument(
        "--ytshorts",
        dest="ytshorts",
        action="store_true",
        default=None,
        help="Generate YouTube Shorts video after commit/push (default: on)",
    )
    commit_push.add_argument(
        "--no-ytshorts",
        dest="ytshorts",
        action="store_false",
        help="Skip YouTube Shorts video generation",
    )

    # ── Now ────────────────────────────────────────────────────────────────────
    now_group = parser.add_argument_group("now")
    now_group.add_argument(
        "--now",
        action="store_true",
        help=(
            "Capture a 'Now' moment — reads TODO.md, current git diff and "
            "last N commits, generates one clearing-the-mind haiku, saves it "
            "to the moments table, and launches the viewer on it."
        ),
    )

    # ── Viewer ─────────────────────────────────────────────────────────────────
    viewer = parser.add_argument_group("viewer")
    viewer.add_argument(
        "-p", "--play",
        action="store_true",
        help="Launch the PyQt6 cinematic viewer",
    )

    # ── Depth ──────────────────────────────────────────────────────────────────
    depth = parser.add_argument_group("depth")
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
        "--init",
        action="store_true",
        help="Initialize .codestory folder in current repository",
    )
    utility.add_argument(
        "--reset-db",
        action="store_true",
        help="Delete the database for a fresh start (irreversible)",
    )
    utility.add_argument(
        "--sync",
        action="store_true",
        help="Validate and repair DB-filesystem sync",
    )
    utility.add_argument(
        "--install-hook",
        action="store_true",
        help="Install a git post-commit hook to auto-generate haikus",
    )

    # ── Release ────────────────────────────────────────────────────────────────
    release = parser.add_argument_group("release")
    release.add_argument(
        "--release_dry_run",
        action="store_true",
        help=(
            "Interactive Director's Cut preflight wizard — shows what would be rendered "
            "(DB stats, render queue, BGM check, duration estimate) then lets you "
            "[R]ender / [P]review storyboard / [C]hange profile / [Q]uit"
        ),
    )
    release.add_argument(
        "--release-version",
        default="v0.1",
        metavar="TAG",
        help="Version tag for the release (default: v0.1, used with --release_dry_run)",
    )

    # ── Logging ────────────────────────────────────────────────────────────────
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable verbose logging",
    )
    parser.add_argument(
        "--version",
        action="store_true",
        help="Show version information",
    )

    return parser


def parse_args(args: Optional[list] = None) -> argparse.Namespace:
    """
    Parse command line arguments.

    Args:
        args: Optional list of arguments (default: sys.argv).

    Returns:
        Parsed arguments namespace.
    """
    parser = build_arg_parser()
    return parser.parse_args(args)
