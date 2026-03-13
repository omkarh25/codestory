"""
Immersive CLI welcome screen for codeStory.

Displays ASCII art banner and contextual information
about the current repository state.
"""

import sys
from pathlib import Path
from typing import Optional

# ASCII Art Banner
BANNER = r"""
╔══════════════════════════════════════════════════════════════════════╗
║                                                                      ║
║     ██████╗ ███████╗████████╗██████╗  ██████╗                ██████╗  ║
║     ██╔══██╗██╔════╝╚══██╔══╝██╔══██╗██╔═══██╗              ██╔══██╗ ║
║     ██████╔╝█████╗     ██║   ██████╔╝██║   ██║              ██████╔╝ ║
║     ██╔══██╗██╔══╝     ██║   ██╔══██╗██║   ██║              ██╔══██╗ ║
║     ██║  ██║███████╗   ██║   ██║  ██║╚██████╔╝              ██║  ██║ ║
║     ╚═╝  ╚═╝╚══════╝   ╚═╝   ╚═╝  ╚═╝ ╚═════╝               ╚═╝  ╚═╝ ║
║                                                                      ║
║            "Every commit is a confession. Every repo is a crime scene." ║
║                                                                      ║
║     ██████╗ ███████╗██╗   ██╗                                     ║
║     ██╔══██╗██╔════╝██║   ██║                                     ║
║     ██║  ██║█████╗  ██║   ██║                                     ║
║     ██║  ██║██╔══╝  ╚██╗ ██╔╝                                     ║
║     ██████╔╝███████╗ ╚████╔╝                                      ║
║     ╚═════╝ ╚══════╝  ╚═══╝                                       ║
║                                                                      ║
║                    MAX THE DESTROYER awaits.                          ║
║                                                                      ║
╚══════════════════════════════════════════════════════════════════════╝
"""

# ASCII Art - Smaller version for inline display
SMALL_BANNER = r"""
   ██████╗ ███████╗████████╗██████╗  ██████╗
   ██╔══██╗██╔════╝╚══██╔══╝██╔══██╗██╔═══██╗
   ██████╔╝█████╗     ██║   ██████╔╝██║   ██║
   ██╔══██╗██╔══╝     ██║   ██╔══██╗██║   ██║
   ██║  ██║███████╗   ██║   ██║  ██║╚██████╔╝
   ╚═╝  ╚═╝╚══════╝   ╚═╝   ╚═╝  ╚═╝ ╚═════╝

     "Every commit is a confession."
          MAX THE DESTROYER awaits.
"""


# Tagline variants for variety — the first three are NOW-ethos oriented (subtle center)
TAGLINES = [
    '"⚡ NOW is the center. Everything else is archaeology."',
    '"The still point before the next commit."',
    '"Every commit is a confession. Every repo is a crime scene."',
    '"He built the detective. He left all the evidence."',
    '"The investigation is ongoing. The evidence accumulates."',
    '"codeStory is the detective."',
    '"MAX THE DESTROYER has read every commit."',
]


def print_welcome(
    repo_path: Optional[str] = None,
    haiku_count: int = 0,
    episode_count: int = 0,
    pending_count: int = 0,
    verbose: bool = False,
) -> None:
    """
    Print the immersive welcome screen.

    Args:
        repo_path: Path to the repository.
        haiku_count: Number of haikus in database.
        episode_count: Number of episodes in database.
        pending_count: Number of pending haikus.
        verbose: Show detailed information.
    """
    # Print main banner
    print(BANNER)

    # Print repository info
    if repo_path:
        path = Path(repo_path).resolve()
        print(f"\n  📂 Repository: {path}")
        
        # Check if it's a git repo
        if (path / ".git").exists():
            print(f"  ✅ Git repository detected")
        else:
            print(f"  ⚠️  Not a git repository")

    # Print database stats
    if haiku_count > 0 or episode_count > 0:
        print(f"\n  📊 Database Status:")
        print(f"     Haikus:   {haiku_count} total ({pending_count} pending)")
        print(f"     Episodes: {episode_count} generated")

        # Show readiness status
        if pending_count >= 10:
            print(f"\n  ✅ READY — {pending_count} haikus available for next episode")
        else:
            need = 10 - pending_count
            print(f"\n  ⏳ NEED {need} more haiku(s) for next episode")

    # Quick start guide
    if verbose:
        print("""
  ═══════════════════════════════════════════════════════════════════
  🚀 Quick Start:
  
     codestory --generate-haikus    Generate haikus from git commits
     codestory --generate-episodes  Compile haikus into episodes
     codestory --play               Launch the PyQt6 viewer
     codestory --status             Show database status
     codestory --init               Initialize .codestory folder
     
  📖 More Options:
  
     codestory --help               Show all options
     codestory --generate-haikus --depth git_diff  Use full diffs
     codestory --sync               Repair DB-filesystem sync
     
  🔧 Configuration:
  
     Edit config.json or .codestory/config.json
     Copy llm.env.example to llm.env and add your API key
""")

    # Footer — subtle NOW nudge
    print("\n" + "─" * 78)
    print("  ⚡  Run  codestory --now  — your present moment awaits.")
    print("─" * 78)


def print_status(
    haiku_count: int,
    episode_count: int,
    pending_count: int,
    repo_path: str,
    db_path: str,
    model: str,
    depth: str,
) -> None:
    """
    Print detailed status information.

    Args:
        haiku_count: Total haikus in database.
        episode_count: Total episodes in database.
        pending_count: Haikus not yet in episodes.
        repo_path: Repository path.
        db_path: Database path.
        model: LLM model being used.
        depth: Git depth setting.
    """
    print("\n🎬 codeStory Status")
    print("=" * 50)
    print(f"  Repo:    {repo_path}")
    print(f"  DB:      {db_path}")
    print(f"  Model:   {model}")
    print(f"  Depth:   haiku={depth}  episode={depth}")

    if haiku_count == 0:
        print("\n  DB not initialized yet. Run --generate-haikus to start.")
        return

    print(f"\n  Haikus:   {haiku_count} total  ({pending_count} pending → next episode)")
    print(f"  Episodes: {episode_count} generated")

    haiku_per_ep = 10
    if pending_count >= haiku_per_ep:
        print(f"\n  ✅ Ready to generate next episode ({pending_count}/{haiku_per_ep} haikus available)")
    else:
        print(f"\n  Need {haiku_per_ep - pending_count} more haikus before next episode.")


def print_error(message: str) -> None:
    """
    Print an error message in red.

    Args:
        message: Error message to display.
    """
    print(f"\n❌ Error: {message}", file=sys.stderr)


def print_success(message: str) -> None:
    """
    Print a success message in green.

    Args:
        message: Success message to display.
    """
    print(f"\n✅ {message}")


def print_warning(message: str) -> None:
    """
    Print a warning message in yellow.

    Args:
        message: Warning message to display.
    """
    print(f"\n⚠️  Warning: {message}")


def print_info(message: str) -> None:
    """
    Print an info message.

    Args:
        message: Info message to display.
    """
    print(f"\nℹ️  {message}")
