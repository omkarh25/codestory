"""Interactive digit-menu CLI for codeStory.

This module provides a nested interactive experience when users run
`codestory` without flags. Existing flag-based workflows remain unchanged.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

from codestory.cli.welcome import print_error, print_status, print_success, print_warning
from codestory.core import DatabaseManager
from codestory.core.logging import get_logger
from codestory.core.public_repo import (
    add_public_repo,
    clone_repo,
    fetch_repo,
    get_public_repo,
    get_repo_db_path,
    get_repo_git_dir,
    list_public_repos,
    remove_public_repo,
)

LOGGER = get_logger(__name__)


def _prompt_choice(prompt: str, valid_choices: List[str]) -> str:
    """Prompt user for a menu choice until a valid choice is entered."""
    while True:
        try:
            choice = input(prompt).strip()
        except (EOFError, KeyboardInterrupt):
            LOGGER.info("Interactive prompt interrupted, exiting to safe default")
            return "0"
        if choice in valid_choices:
            return choice
        print_warning(f"Invalid choice: {choice}. Expected one of: {', '.join(valid_choices)}")


def _render_status(cfg: Dict[str, Any]) -> None:
    """Render status view for local repository."""
    db_path = cfg.get("db_path", ".codestory/codestory.db")
    db = DatabaseManager(db_path)
    print_status(
        haiku_count=db.get_haiku_count(),
        episode_count=db.get_episode_count(),
        pending_count=db.get_pending_haiku_count(),
        repo_path=cfg.get("repo_path", "."),
        db_path=db_path,
        model=cfg.get("haiku", {}).get("model", "unknown"),
        depth=cfg.get("haiku", {}).get("depth", "git_commit"),
    )


def _render_public_repos() -> List[Dict[str, Any]]:
    """Print tracked public repositories and return them."""
    repos = list_public_repos()
    if not repos:
        print_warning("No public repos tracked. Use option 2 to add one.")
        return []

    print(f"\n🌐 Tracked public repos ({len(repos)}):")
    print("  " + "─" * 62)
    for idx, repo in enumerate(repos, start=1):
        slug = repo.get("slug", "unknown")
        status = repo.get("status", "unknown")
        url = repo.get("url", "")
        print(f"  {idx:>2}. {slug:<35} [{status}]")
        print(f"      {url}")
    print()
    return repos


def _choose_public_repo_slug() -> Optional[str]:
    """Show numbered public repos and return chosen slug, if any."""
    repos = _render_public_repos()
    if not repos:
        return None

    valid = [str(i) for i in range(1, len(repos) + 1)] + ["0"]
    choice = _prompt_choice(f"Select repo [1-{len(repos)}] or 0 to cancel: ", valid)
    if choice == "0":
        return None

    selected = repos[int(choice) - 1]
    slug = selected.get("slug")
    LOGGER.info("Interactive selection: public repo slug=%s", slug)
    return slug


def _generate_public_haikus(
    cfg: Dict[str, Any],
    slug: str,
    progress_callback: Optional[Callable[[str, str, Any], None]] = None,
) -> None:
    """Generate public repo haikus for selected slug."""
    repo_cfg = get_public_repo(slug)
    if not repo_cfg:
        print_error(f"Public repo not found: {slug}")
        return

    git_dir = get_repo_git_dir(slug)
    if not git_dir.exists():
        url = repo_cfg.get("url", "")
        print(f"\n📥 Cloning {slug} ...")
        if not clone_repo(url, slug):
            print_error(f"Failed to clone public repo: {slug}")
            return

    fetch_repo(slug)

    try:
        from codestory.pipeline.public_haiku import generate_public_haikus

        generated = generate_public_haikus(
            slug=slug,
            config=cfg,
            progress_callback=progress_callback,
        )
        if generated:
            print_success(f"Generated {len(generated)} public haiku(s) for {slug}")
        else:
            print_warning(f"No new public haikus generated for {slug}")
    except Exception as exc:
        LOGGER.error("Interactive public haiku generation failed for %s: %s", slug, exc)
        print_error(f"Public haiku generation failed: {exc}")


def _local_menu(
    cfg: Dict[str, Any],
    progress_callback: Optional[Callable[[str, str, Any], None]] = None,
) -> None:
    """Run local repository submenu loop."""
    while True:
        print("\n🎬 Local Repo Menu")
        print("  1) Generate haikus")
        print("  2) Generate episodes")
        print("  3) Generate storyboard")
        print("  4) Render YT shorts")
        print("  5) Play PyQt viewer")
        print("  6) Show status")
        print("  0) Back")

        choice = _prompt_choice("Choose option: ", ["1", "2", "3", "4", "5", "6", "0"])
        if choice == "0":
            return

        try:
            if choice == "1":
                from codestory.pipeline.haiku import generate_haikus

                res = generate_haikus(config=cfg, progress_callback=progress_callback)
                print_success(f"Generated {len(res)} haiku(s)") if res else print_warning("No new haikus generated")
            elif choice == "2":
                from codestory.pipeline.episode import generate_episodes

                eps = generate_episodes(config=cfg)
                print_success(f"Generated episode: {eps[0].get('title', 'Untitled')}") if eps else print_warning("No episode generated")
            elif choice == "3":
                from codestory.render.storyboard import build_episode_storyboard_default

                # Keep this action lightweight in interactive mode.
                _ = build_episode_storyboard_default
                print_warning("Use: codestory --generate-storyboard (interactive shortcut pending full integration)")
            elif choice == "4":
                from codestory.render.video import render_all

                videos = render_all(config=cfg)
                print_success(f"Rendered {len(videos)} video(s)") if videos else print_warning("No videos to render")
            elif choice == "5":
                from codestory.viewer.qt_viewer import launch_app

                launch_app(cfg)
            elif choice == "6":
                _render_status(cfg)
        except Exception as exc:
            LOGGER.error("Interactive local menu action failed: %s", exc)
            print_error(str(exc))


def _public_menu(
    cfg: Dict[str, Any],
    progress_callback: Optional[Callable[[str, str, Any], None]] = None,
) -> None:
    """Run public repository submenu loop."""
    selected_slug: Optional[str] = None

    while True:
        print("\n🌐 Public Repo Menu")
        print(f"  Selected: {selected_slug or '(none)'}")
        print("  1) List public repos")
        print("  2) Add public repo")
        print("  3) Remove public repo")
        print("  4) Select public repo")
        print("  5) Generate haikus for selected repo")
        print("  6) Serve HTMX")
        print("  7) Play PyQt viewer")
        print("  0) Back")

        choice = _prompt_choice("Choose option: ", ["1", "2", "3", "4", "5", "6", "7", "0"])
        if choice == "0":
            return

        try:
            if choice == "1":
                _render_public_repos()
            elif choice == "2":
                url = input("Enter GitHub URL (or owner/repo): ").strip()
                if not url:
                    print_warning("No URL entered")
                    continue
                repo = add_public_repo(url)
                selected_slug = repo.get("slug")
                print_success(f"Added public repo: {selected_slug}")
            elif choice == "3":
                slug = _choose_public_repo_slug()
                if not slug:
                    continue
                if remove_public_repo(slug):
                    if selected_slug == slug:
                        selected_slug = None
                    print_success(f"Removed public repo: {slug}")
                else:
                    print_warning(f"Public repo not found: {slug}")
            elif choice == "4":
                slug = _choose_public_repo_slug()
                if slug:
                    selected_slug = slug
                    print_success(f"Selected public repo: {selected_slug}")
            elif choice == "5":
                if not selected_slug:
                    print_warning("No repo selected. Choose option 4 first.")
                    continue
                _generate_public_haikus(cfg, selected_slug, progress_callback=progress_callback)
            elif choice == "6":
                from codestory.web.server import start_server

                port_raw = input("Port [8080]: ").strip() or "8080"
                port = int(port_raw)
                print(f"Starting HTMX server on http://localhost:{port} (Ctrl+C to stop)")
                start_server(port=port)
            elif choice == "7":
                from codestory.viewer.qt_viewer import launch_app

                if not selected_slug:
                    print_warning("No repo selected. Choose option 4 first.")
                    continue

                db_path = get_repo_db_path(selected_slug)
                if not db_path.exists():
                    print_warning(
                        f"No database found for {selected_slug}. Generate public haikus first."
                    )
                    continue

                viewer_cfg = dict(cfg)
                viewer_cfg["db_path"] = str(db_path)
                LOGGER.info(
                    "Launching PyQt viewer for public repo %s using DB %s",
                    selected_slug,
                    db_path,
                )
                launch_app(viewer_cfg)
        except Exception as exc:
            LOGGER.error("Interactive public menu action failed: %s", exc)
            print_error(str(exc))


def run_interactive_menu(
    cfg: Dict[str, Any],
    progress_callback: Optional[Callable[[str, str, Any], None]] = None,
) -> int:
    """Run the top-level interactive CLI menu.

    Returns:
        Exit code integer.
    """
    LOGGER.info("Launching interactive CLI menu")

    while True:
        print("\n🧭 Main Menu")
        print("  1) Local repo")
        print("  2) Public repo")
        print("  0) Exit")

        choice = _prompt_choice("Choose option: ", ["1", "2", "0"])
        if choice == "0":
            print("Goodbye.")
            return 0
        if choice == "1":
            _local_menu(cfg, progress_callback=progress_callback)
        elif choice == "2":
            _public_menu(cfg, progress_callback=progress_callback)
