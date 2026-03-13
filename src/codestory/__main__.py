"""
codeStory CLI main entry point.

This module is executed when running:
    python -m codestory
    codestory (after pip install)

Or directly:
    python codestory.py
"""

import os
import sys
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables from llm.env
env_path = Path(__file__).parent.parent.parent / "llm.env"
if env_path.exists():
    load_dotenv(env_path)

# Add src to path for local development
src_path = Path(__file__).parent.parent
if str(src_path) not in sys.path:
    sys.path.insert(0, str(src_path))

from codestory.cli import (
    parse_args,
    print_welcome,
    print_status,
    print_error,
    print_success,
    print_warning,
)
from codestory.core import (
    load_config,
    init_repo_config,
    setup_logging,
    DatabaseManager,
)
from codestory.core.logging import get_logger

LOGGER = get_logger(__name__)


def main() -> int:
    """
    Main entry point for the codeStory CLI.

    Returns:
        Exit code (0 = success, non-zero = error).
    """
    # Parse arguments
    args = parse_args()

    # Set up logging
    log_level = "DEBUG" if args.verbose else "WARNING"
    setup_logging(level=getattr(__import__("logging"), log_level))

    # Handle version flag
    if args.version:
        from codestory import __version__
        print(f"codeStory version {__version__}")
        return 0

    # Load configuration
    cfg = load_config(overrides={
        "repo_path": args.repo,
    } if args.repo else None)

    # Handle init command
    if args.init:
        repo_path = Path(cfg.get("repo_path", ".")).resolve()
        config_path = init_repo_config(repo_path)
        print_success(f"Initialized .codestory folder at {repo_path}")
        print(f"Config created: {config_path}")
        return 0

    # Handle status command
    if args.status:
        db_path = cfg.get("db_path", ".codestory/codestory.db")
        db = DatabaseManager(db_path)

        haiku_count = db.get_haiku_count()
        episode_count = db.get_episode_count()
        pending_count = db.get_pending_haiku_count()

        print_status(
            haiku_count=haiku_count,
            episode_count=episode_count,
            pending_count=pending_count,
            repo_path=cfg.get("repo_path", "."),
            db_path=db_path,
            model=cfg.get("haiku", {}).get("model", "unknown"),
            depth=cfg.get("haiku", {}).get("depth", "git_commit"),
        )
        return 0

    # Handle reset-db command
    if args.reset_db:
        db_path = Path(cfg.get("db_path", ".codestory/codestory.db"))
        if db_path.exists():
            db_path.unlink()
            print_success(f"Database reset: {db_path}")
            LOGGER.info("Database deleted: %s", db_path)
        else:
            print_warning(f"No database found at {db_path}")
        return 0

    # Handle sync command
    if args.sync:
        db_path = cfg.get("db_path", ".codestory/codestory.db")
        db = DatabaseManager(db_path)

        print("Validating DB-filesystem sync...")
        issues = db.validate_sync()

        total_issues = sum(len(v) for v in issues.values())
        if total_issues == 0:
            print_success("All assets are in sync!")
        else:
            print_warning(f"Found {total_issues} sync issues:")
            for issue_type, files in issues.items():
                if files:
                    print(f"\n  {issue_type}:")
                    for f in files[:5]:  # Show first 5
                        print(f"    - {Path(f).name}")
                    if len(files) > 5:
                        print(f"    ... and {len(files) - 5} more")

        return 0

    # Handle install-hook command
    if args.install_hook:
        repo_path = Path(cfg.get("repo_path", "."))
        hooks_dir = repo_path / ".git" / "hooks"

        if not hooks_dir.exists():
            print_error("No .git/hooks directory found. Is this a git repository?")
            return 1

        codestory_path = Path(__file__).parent.parent.parent / "codestory.py"
        hook_content = f"""#!/bin/bash
# codeStory — auto-generate haiku on every commit
# Installed by: codestory --install-hook

conda run -n macenv python "{codestory_path}" --generate-haikus --max 1 2>/dev/null &
disown
"""
        hook_path = hooks_dir / "post-commit"
        hook_path.write_text(hook_content, encoding="utf-8")
        hook_path.chmod(0o755)

        print_success(f"Git commit hook installed: {hook_path}")
        return 0

    # Show welcome if no command specified
    if not any([
        args.generate_haikus,
        args.generate_episodes,
        args.generate_ytshorts,
        args.play,
        args.commit,
        args.push,
    ]):
        db_path = cfg.get("db_path", ".codestory/codestory.db")
        db_exists = Path(db_path).exists()

        haiku_count = 0
        episode_count = 0
        pending_count = 0

        if db_exists:
            try:
                db = DatabaseManager(db_path)
                haiku_count = db.get_haiku_count()
                episode_count = db.get_episode_count()
                pending_count = db.get_pending_haiku_count()
            except Exception:
                pass

        print_welcome(
            repo_path=cfg.get("repo_path"),
            haiku_count=haiku_count,
            episode_count=episode_count,
            pending_count=pending_count,
            verbose=True,
        )
        return 0

    # Pipeline: generate haikus
    if args.generate_haikus:
        try:
            from codestory.pipeline.haiku import generate_haikus
            results = generate_haikus(config=cfg)
            if results:
                print_success(f"Generated {len(results)} haiku(s)")
            else:
                print_warning("No new haikus generated")
        except Exception as exc:
            print_error(f"Haiku generation failed: {exc}")
            LOGGER.error("Haiku generation failed: %s", exc)
            return 1

    # Pipeline: generate episodes
    if args.generate_episodes:
        try:
            from codestory.pipeline.episode import generate_episodes
            results = generate_episodes(config=cfg)
            if results:
                print_success(f"Generated episode: {results[0].get('title', 'Untitled')}")
            else:
                print_warning("No episode generated (not enough haikus)")
        except Exception as exc:
            print_error(f"Episode generation failed: {exc}")
            LOGGER.error("Episode generation failed: %s", exc)
            return 1

    # Pipeline: generate YouTube shorts
    if args.generate_ytshorts:
        try:
            from codestory.render.video import render_all
            results = render_all(config=cfg)
            if results:
                print_success(f"Rendered {len(results)} video(s)")
            else:
                print_warning("No videos to render")
        except Exception as exc:
            print_error(f"Video rendering failed: {exc}")
            LOGGER.error("Video rendering failed: %s", exc)
            return 1

    # ── COMMIT FLOW ─────────────────────────────────────────────────────────
    # Handle --commit and --push with full progress display
    if args.commit or args.push:
        # Determine settings
        do_push = args.push
        # ytshorts default is True unless explicitly disabled
        do_ytshorts = args.ytshorts if args.ytshorts is not None else True
        
        print("\n" + "="*60)
        print("🎬 CODE STORY COMMIT FLOW")
        print("="*60 + "\n")
        
        # Step 1: Analyze diff
        print("📊 Analyzing git diff...")
        from codestory.pipeline.git import has_uncommitted_changes, get_all_uncommitted_changes
        from codestory.pipeline.commit import commit_and_push
        
        if not has_uncommitted_changes(cfg.get("repo_path", ".")):
            print_warning("No uncommitted changes found. Nothing to commit.")
            return 0
        
        diff = get_all_uncommitted_changes(cfg.get("repo_path", "."))
        diff_lines = len(diff.splitlines())
        print(f"   ✓ Found {diff_lines} lines of changes")
        
        # Step 2: Generate commit message
        print("\n🤖 MAX THE DESTROYER is crafting your confession...")
        try:
            success, commit_hash, commit_msg = commit_and_push(cfg, do_push=do_push)
        except Exception as exc:
            print_error(f"Commit failed: {exc}")
            LOGGER.error("Commit flow failed: %s", exc)
            return 1
        
        if not success:
            print_error("Failed to generate commit message or commit changes")
            return 1
        
        print(f"\n✅ Committed: {commit_hash}")
        if commit_msg:
            print(f"   📝 {commit_msg}")
        
        # Step 3: Push if requested
        if do_push:
            print("\n🚀 Pushing to remote...")
            print(f"   ✓ Pushed to origin/{cfg.get('branch', 'main')}")
        
        # Step 4: Generate haiku for the new commit
        print("\n🎬 Generating haiku for your confession...")
        try:
            from codestory.pipeline.haiku import generate_haikus
            haiku_results = generate_haikus(config=cfg)
            if haiku_results:
                print(f"   ✓ Generated {len(haiku_results)} haiku(s)")
            else:
                print_warning("   ⚠ No new haiku generated")
        except Exception as exc:
            print_warning(f"   ⚠ Haiku generation skipped: {exc}")
        
        # Step 5: Generate YouTube Shorts in background if enabled
        if do_ytshorts:
            print("\n🎥 Rendering YouTube Shorts in background...")
            try:
                # Run in background - don't wait
                import subprocess
                import threading
                
                def run_ytshorts():
                    try:
                        from codestory.render.video import render_all
                        render_all(config=cfg)
                    except Exception as e:
                        LOGGER.warning("YT Shorts generation failed: %s", e)
                
                thread = threading.Thread(target=run_ytshorts)
                thread.daemon = True
                thread.start()
                print("   ✓ Background render started")
            except Exception as e:
                print_warning(f"   ⚠ Could not start background render: {e}")
        
        # Step 6: Launch viewer
        print("\n📺 Launching PyQt6 viewer...")
        try:
            from codestory.viewer.qt_viewer import launch_app
            print("\n" + "="*60)
            print("🎬 ENJOY YOUR STORY!")
            print("="*60 + "\n")
            return launch_app(cfg)
        except Exception as exc:
            print_warning(f"   ⚠ Viewer not available: {exc}")
            print("\n" + "="*60)
            print("🎬 COMMIT COMPLETE!")
            print("="*60 + "\n")
            return 0

    # Viewer: launch PyQt6
    if args.play:
        try:
            from codestory.viewer.qt_viewer import launch_app
            return launch_app(cfg)
        except ImportError as exc:
            print_error(f"PyQt6 not available: {exc}")
            print("Install with: pip install PyQt6")
            return 1
        except Exception as exc:
            print_error(f"Viewer launch failed: {exc}")
            LOGGER.error("Viewer launch failed: %s", exc)
            return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
