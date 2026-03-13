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

# Add root to path for legacy scripts (ytpipeline.py, codeQT.py, etc.)
root_path = Path(__file__).parent.parent.parent
if str(root_path) not in sys.path:
    sys.path.append(str(root_path))

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


def _box(title: str, width: int = 56) -> str:
    """Return a boxed title string for CLI output."""
    inner = f"  {title}  "
    pad = max(0, width - len(inner))
    return (
        f"╔{'═' * (len(inner) + pad)}╗\n"
        f"║{inner}{' ' * pad}║\n"
        f"╚{'═' * (len(inner) + pad)}╝"
    )


def _step(n: int, total: int, label: str) -> None:
    """Print a numbered step header."""
    print(f"\n\033[1;36m[{n}/{total}]\033[0m  {label}")
    print("  " + "─" * 50)


def run_release_dry_run(cfg: dict, version: str = "v0.1") -> int:
    """
    Interactive Director's Cut preflight wizard.

    Walks through 6 pre-render checks and presents an action menu:
    [R]ender  [P]review storyboard  [C]hange profile  [Q]uit

    Args:
        cfg:     Full config dict.
        version: Release version tag (e.g. "v0.1").

    Returns:
        Exit code (0 = success / quit, 1 = error).
    """
    import json as _json
    from pathlib import Path

    TOTAL_STEPS = 6
    render_profile = cfg.get("render", {}).get("profile", "short")

    print("\n" + _box(f"🎬  codeStory {version} — Director's Preflight"))

    # ── Step 1: DB STATUS ────────────────────────────────────────────────────
    _step(1, TOTAL_STEPS, "📊  DB STATUS")
    db_path = cfg.get("db_path", ".codestory/codestory.db")
    haiku_count = episode_count = pending_count = 0
    all_haikus = []
    all_episodes = []

    if Path(db_path).exists():
        db = DatabaseManager(db_path)
        haiku_count = db.get_haiku_count()
        episode_count = db.get_episode_count()
        pending_count = db.get_pending_haiku_count()
        all_haikus = db.get_all_haikus()
        all_episodes = db.get_all_episodes()
    else:
        print(f"  ⚠  No DB found at {db_path}")
        print("  Run: codestory --init && codestory --generate-haikus")
        return 0

    print(f"  Haikus:    {haiku_count} total  ({haiku_count - pending_count} compiled, {pending_count} pending)")
    print(f"  Episodes:  {episode_count}")

    # Check for storyboards
    assets_dir = Path(cfg.get("output_dir", ".codestory/assets"))
    sb_dir = assets_dir / "storyboards"
    storyboard_files = sorted(sb_dir.glob("storyboard_episode_*.json")) if sb_dir.exists() else []
    latest_sb = None
    if storyboard_files:
        latest_sb_path = storyboard_files[-1]
        try:
            latest_sb = _json.loads(latest_sb_path.read_text())
            n_shots = latest_sb.get("total_shots", "?")
            est_dur = latest_sb.get("estimated_duration_s", "?")
            gen_by  = latest_sb.get("generated_by", "?")
            print(f"  Storyboard: ✓ {latest_sb_path.name}  ({n_shots} shots, ~{est_dur}s, by {gen_by})")
        except Exception:
            print(f"  Storyboard: ✗ could not read {latest_sb_path.name}")
    else:
        print("  Storyboard: — (run --generate-storyboard to create one)")

    # ── Step 2: RENDER QUEUE ─────────────────────────────────────────────────
    _step(2, TOTAL_STEPS, "🎞   RENDER QUEUE")
    yt_dir = Path(cfg.get("yt_shorts", {}).get("output_dir", cfg.get("yt_output_dir", ".codestory/assets/videos")))
    # Support legacy yt_output_dir
    if "yt_output_dir" in cfg:
        yt_dir = Path(cfg["yt_output_dir"])

    unrendered_haikus = []
    for h in all_haikus:
        chron = h.get("chronological_index", 0)
        branch = (h.get("branch") or "main").replace("/", "-")
        short = (h.get("commit_hash") or "")[:7]
        fname = f"haiku_{chron:03d}_{branch}_{short}.mp4"
        if not (yt_dir / fname).exists():
            unrendered_haikus.append((h, fname))

    unrendered_episodes = []
    for ep in all_episodes:
        ep_num = ep.get("episode_number", 0)
        ep_fname = f"episode_{ep_num:03d}.mp4"
        if not (yt_dir / ep_fname).exists():
            unrendered_episodes.append((ep, ep_fname))

    if not unrendered_haikus and not unrendered_episodes:
        print("  ✓ All haikus and episodes already rendered — nothing to do.")
        print("  (Delete existing MP4s to re-render with the new audio pipeline)")
    else:
        total_queue = len(unrendered_haikus) + len(unrendered_episodes)
        print(f"  {total_queue} item(s) queued for render:")
        # Show up to 8 haikus
        for h, fname in unrendered_haikus[:8]:
            commit_type = h.get("commit_type", "?")
            title_short = (h.get("title") or "Untitled")[:45]
            print(f"    • {fname:<40}  [{commit_type}]  {title_short}")
        if len(unrendered_haikus) > 8:
            print(f"    … and {len(unrendered_haikus) - 8} more haikus")
        for ep, ep_fname in unrendered_episodes:
            ep_title = (ep.get("title") or "Untitled")[:45]
            print(f"    • {ep_fname:<40}  [episode]  {ep_title}")

    # ── Step 3: BGM CHECK ────────────────────────────────────────────────────
    _step(3, TOTAL_STEPS, "🎵  AUDIO CHECK")
    audio_cfg = cfg.get("audio", {})
    haiku_track  = audio_cfg.get("track_path", "")
    episode_track = audio_cfg.get("episode_track_path", "")
    volume    = audio_cfg.get("volume", 0.3)
    fade_in   = audio_cfg.get("fade_in_s", 1.0)
    fade_out  = audio_cfg.get("fade_out_s", 1.5)

    if render_profile == "minimal":
        print("  Profile: minimal — audio DISABLED (silent render)")
    else:
        ht_ok = Path(haiku_track).exists() if haiku_track else False
        et_ok = Path(episode_track).exists() if episode_track else False
        ht_name = Path(haiku_track).name if haiku_track else "not configured"
        et_name = Path(episode_track).name if episode_track else "not configured"
        ht_icon = "✓" if ht_ok else "✗"
        et_icon = "✓" if et_ok else "✗"
        print(f"  Haiku BGM:   {ht_icon} {ht_name}")
        print(f"  Episode BGM: {et_icon} {et_name}")
        print(f"  Volume: {volume}  |  Fade in: {fade_in}s  |  Fade out: {fade_out}s")
        if not ht_ok:
            print(f"  ⚠  Haiku track not found — will render silent. Set audio.track_path in config.")

    # ── Step 4: DURATION ESTIMATE ────────────────────────────────────────────
    _step(4, TOTAL_STEPS, "⏱   DURATION ESTIMATE")
    slide_dur   = float(cfg.get("yt_slide_duration_s", 2.5))
    verdict_dur = float(cfg.get("yt_verdict_duration_s", 4.0))
    haiku_video_dur = slide_dur * 4 + verdict_dur  # 5 slides
    episode_video_dur = (slide_dur * 2.2) * 3 + (verdict_dur * 2.0)  # 4 slides with episode timing

    if latest_sb:
        sb_dur = latest_sb.get("estimated_duration_s", 0)
        print(f"  Storyboard:  ~{sb_dur:.0f}s total ({latest_sb.get('total_shots', 0)} shots)")
    else:
        total_haiku_time = len(unrendered_haikus) * haiku_video_dur
        total_ep_time    = len(unrendered_episodes) * episode_video_dur
        print(f"  Haiku renders: {len(unrendered_haikus)} × ~{haiku_video_dur:.1f}s = ~{total_haiku_time:.0f}s of video")
        print(f"  Episode renders: {len(unrendered_episodes)} × ~{episode_video_dur:.1f}s = ~{total_ep_time:.0f}s of video")
        print(f"  Total video output: ~{total_haiku_time + total_ep_time:.0f}s")
    print(f"  Estimated render time: ~{max(1, (len(unrendered_haikus) + len(unrendered_episodes)) * 45)//60}–{max(2, (len(unrendered_haikus) + len(unrendered_episodes)) * 90)//60} min")

    # ── Step 5: OUTPUT ───────────────────────────────────────────────────────
    _step(5, TOTAL_STEPS, "📁  OUTPUT PATHS")
    md_dir = yt_dir / "casefiles"
    print(f"  MP4s:       {yt_dir}")
    print(f"  Casefiles:  {md_dir}")
    print(f"  Storyboards:{sb_dir}")
    print(f"  Profile:    {render_profile}  {'(BGM + casefile MD)' if render_profile == 'short' else '(silent, no MD)'}")

    # ── Step 6: ACTION MENU ──────────────────────────────────────────────────
    while True:
        _step(6, TOTAL_STEPS, "✅  ACTION")
        print(f"  [R] Render now  (profile: {render_profile})")
        print("  [P] Preview latest storyboard shot list")
        print("  [C] Change render profile  (minimal ↔ short)")
        print("  [Q] Quit — do nothing")
        print()

        try:
            choice = input("  Your choice [R/P/C/Q]: ").strip().upper()
        except (KeyboardInterrupt, EOFError):
            print("\n  Aborted.")
            return 0

        if choice == "Q":
            print("\n  Preflight complete. No render started. Run again when ready.")
            return 0

        elif choice == "P":
            if latest_sb:
                print("\n  ── Storyboard Shot List ─────────────────────────────")
                for shot in latest_sb.get("shots", []):
                    sid  = shot.get("shot_id", "?")
                    stype = shot.get("type", "?")
                    dur  = shot.get("duration_s", 0)
                    title = (shot.get("title") or shot.get("ruling") or "")[:50]
                    print(f"    {sid:<25} {stype:<12} {dur:>4.1f}s  {title}")
                print(f"\n  Total: {latest_sb.get('estimated_duration_s', '?')}s | {latest_sb.get('total_shots', '?')} shots")
            else:
                print("  No storyboard found. Run: codestory --generate-storyboard")

        elif choice == "C":
            render_profile = "minimal" if render_profile == "short" else "short"
            cfg.setdefault("render", {})["profile"] = render_profile
            print(f"  ✓ Profile changed to: {render_profile}")
            # Re-show audio check
            if render_profile == "minimal":
                print("  Audio: DISABLED (silent render)")
            else:
                ht_ok = Path(haiku_track).exists() if haiku_track else False
                print(f"  Haiku BGM: {'✓' if ht_ok else '✗'} {Path(haiku_track).name if haiku_track else 'not set'}")

        elif choice == "R":
            if not unrendered_haikus and not unrendered_episodes:
                print("\n  Nothing to render — all videos already exist.")
                print("  Delete existing MP4s first if you want to re-render with audio.")
                return 0

            print(f"\n  🎬 Starting render ({render_profile} profile)...")
            try:
                from codestory.render.video import render_all
                render_all(config=cfg)
                print_success("Render complete!")
            except Exception as exc:
                print_error(f"Render failed: {exc}")
                LOGGER.error("Release dry run render failed: %s", exc)
                return 1
            return 0

        else:
            print("  Unknown choice. Please enter R, P, C, or Q.")


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
    overrides = {}
    if args.repo:
        overrides["repo_path"] = args.repo
    cfg = load_config(overrides=overrides if overrides else None)

    # Apply render profile override (CLI flag wins over config file)
    if hasattr(args, "render_profile") and args.render_profile:
        cfg.setdefault("render", {})["profile"] = args.render_profile
        LOGGER.info("Render profile overridden to: %s", args.render_profile)

    # ── Release dry-run wizard ─────────────────────────────────────────────
    if getattr(args, "release_dry_run", False):
        version = getattr(args, "release_version", "v0.1") or "v0.1"
        return run_release_dry_run(cfg, version=version)

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
        getattr(args, "generate_storyboard", False),
        args.generate_ytshorts,
        args.play,
        args.commit,
        args.push,
        getattr(args, "now", False),
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

    # Pipeline: generate Director's Cut storyboard JSON
    if getattr(args, "generate_storyboard", False):
        try:
            import asyncio
            from codestory.core import DatabaseManager
            from codestory.director.prompts import load_release_cut_prompt
            from codestory.pipeline.haiku import build_llm_client
            from codestory.render.storyboard import (
                generate_episode_storyboard_llm,
                build_episode_storyboard_default,
                save_storyboard,
                storyboard_path_for_episode,
            )

            db_path = cfg.get("db_path", ".codestory/codestory.db")
            db = DatabaseManager(db_path)
            episodes = db.get_all_episodes()

            if not episodes:
                print_warning("No episodes found. Run --generate-episodes first.")
            else:
                episode = episodes[-1]  # Latest episode
                ep_num = episode.get("episode_number", 0)
                haiku_rows = db.get_all_haikus()
                # Filter to haikus in this episode
                raw_hashes = episode.get("commit_hashes", "[]")
                import json as _json
                ep_hashes = set(_json.loads(raw_hashes) if isinstance(raw_hashes, str) else raw_hashes)
                ep_haikus = [h for h in haiku_rows if h.get("commit_hash", "") in ep_hashes]

                audio_cfg = cfg.get("audio", {})
                render_profile = cfg.get("render", {}).get("profile", "short")

                try:
                    haiku_cfg = cfg.get("haiku", {})
                    client = build_llm_client(
                        haiku_cfg.get("provider", "anthropic"),
                        haiku_cfg.get("model", "claude-haiku-4-5-20251001"),
                    )
                    system_prompt = load_release_cut_prompt()
                    storyboard = asyncio.run(generate_episode_storyboard_llm(
                        client,
                        haiku_cfg.get("model", "claude-haiku-4-5-20251001"),
                        episode, ep_haikus, system_prompt, audio_cfg, render_profile,
                    ))
                    print_success(f"Storyboard generated by ReleaseCutDirector")
                except Exception as exc:
                    LOGGER.warning("LLM storyboard failed, using default: %s", exc)
                    storyboard = build_episode_storyboard_default(
                        episode, ep_haikus, audio_cfg, render_profile
                    )
                    print_success(f"Default storyboard generated")

                assets_dir = Path(cfg.get("output_dir", ".codestory/assets"))
                sb_path = storyboard_path_for_episode(assets_dir, ep_num)
                save_storyboard(storyboard, sb_path)
                print_success(f"Storyboard saved: {sb_path}")
                print(f"   shots: {storyboard.get('total_shots', '?')}  "
                      f"  est. duration: {storyboard.get('estimated_duration_s', '?')}s  "
                      f"  generated_by: {storyboard.get('generated_by', '?')}")

        except Exception as exc:
            print_error(f"Storyboard generation failed: {exc}")
            LOGGER.error("Storyboard generation failed: %s", exc)
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
        do_ytshorts = False  # Disabled by default due to Qt threading issues
        
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
                import subprocess
                # NOTE: Using subprocess instead of threading to avoid Qt threading issues
                
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

    # ── NOW FLOW ────────────────────────────────────────────────────────────
    if getattr(args, "now", False):
        print("\n" + "=" * 60)
        print("⚡ CODESTORY — NOW")
        print("=" * 60 + "\n")

        print("🧭 Collecting your current moment...")

        try:
            from codestory.pipeline.now import generate_now
            moment = generate_now(config=cfg)
        except Exception as exc:
            print_error(f"Now pipeline failed: {exc}")
            LOGGER.error("--now pipeline failed: %s", exc)
            return 1

        if not moment:
            print_error("No moment generated — check your API key and config.")
            return 1

        print_success(f"Moment captured: {moment.get('title', 'NOW')}")
        print(f"   id={moment.get('id')}  captured_at={moment.get('captured_at', '')[:19]}")
        print()

        # Launch viewer in 'now' mode — auto-navigated to the Moments tab
        try:
            from codestory.viewer.qt_viewer import launch_app_now
            return launch_app_now(cfg, moment_id=moment.get("id"))
        except ImportError as exc:
            print_error(f"PyQt6 not available: {exc}")
            print("Install with: pip install PyQt6")
            return 1
        except Exception as exc:
            print_error(f"Viewer launch failed: {exc}")
            LOGGER.error("Now viewer launch failed: %s", exc)
            return 1

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
