"""
Git operations for codeStory.

Provides utilities for reading git log, diffs, and branch information.
"""

import re
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional

from codestory.core.logging import get_logger

LOGGER = get_logger(__name__)

# Git Crime Lexicon - commit types to crime terminology
GIT_CRIME_LEXICON: Dict[str, str] = {
    "feat": "Rising action — He acquired a new weapon",
    "fix": "Damage control — The alibi was falling apart",
    "chore": "The grind montage — Three days. No sleep. Just code.",
    "refactor": "Identity crisis — He tore it all down and rebuilt himself",
    "docs": "The confession — He documented the crime in detail",
    "test": "Paranoia — He didn't trust himself. He built a lie detector.",
    "revert": "The flashback — He undid it. But you can't unring a bell.",
    "merge": "The conspiracy deepens — Two worlds collided. Nothing was the same.",
    "style": "Vanity — He polished the evidence",
    "ci": "The system closing in — Automated judgment approached",
    "build": "The forge — Infrastructure hammered into shape",
    "perf": "The chase — He made it faster to avoid himself",
    "hotfix": "2 AM damage control — Emergency. No witnesses.",
    "init": "The origin — The first sin. Before the evidence, there was the idea.",
    "wip": "The unfinished crime — Left at the scene, half-done",
}

COMMIT_TYPE_TO_CATEGORY: Dict[str, str] = {
    "feat": "Productive",
    "fix": "Necessity",
    "chore": "Necessity",
    "refactor": "Learning",
    "docs": "Learning",
    "test": "Productive",
    "revert": "Other",
    "merge": "Productive",
    "style": "Other",
    "ci": "Necessity",
    "build": "Necessity",
    "perf": "Productive",
    "hotfix": "Necessity",
    "init": "Productive",
    "wip": "Other",
}


def is_git_repo(path: Path) -> bool:
    """
    Check if a path is a git repository.

    Args:
        path: Path to check.

    Returns:
        True if it's a git repository, False otherwise.
    """
    return (path / ".git").exists()


def parse_commit_type(subject: str) -> str:
    """
    Extract conventional-commit type prefix from subject line.

    Args:
        subject: Full commit subject (e.g., "feat: Add personas").

    Returns:
        Lowercase commit type or "other" if not recognised.
    """
    match = re.match(r"^([a-zA-Z]+)[\(!:]", subject.strip())
    if match:
        return match.group(1).lower()
    return "other"


def read_git_log(repo_path: str, limit: int = 500) -> List[Dict[str, str]]:
    """
    Run git log and parse commits into structured dicts.

    Args:
        repo_path: Absolute path to the git repository root.
        limit: Maximum number of commits to retrieve.

    Returns:
        List of commit dicts with keys: hash, type, msg, branch, author, date.
        Returns empty list on git error.
    """
    sep = "|||"
    fmt = f"%H{sep}%ai{sep}%s{sep}%an{sep}%D"

    try:
        result = subprocess.run(
            ["git", "log", f"--pretty=format:{fmt}", f"-{limit}"],
            capture_output=True, text=True, cwd=repo_path, check=True,
        )
    except subprocess.CalledProcessError as exc:
        LOGGER.error("git log failed in %s: %s", repo_path, exc.stderr)
        return []

    commits = []
    for line in result.stdout.strip().splitlines():
        if not line.strip():
            continue
        parts = line.split(sep)
        if len(parts) < 5:
            continue

        commit_hash, commit_date, subject, author, refs = parts
        commit_type = parse_commit_type(subject)
        branch = _extract_branch_from_refs(refs)

        commits.append({
            "hash": commit_hash.strip(),
            "type": commit_type,
            "msg": subject.strip(),
            "branch": branch,
            "author": author.strip(),
            "date": commit_date.strip(),
        })

    LOGGER.info("git log parsed: %d commits in %s", len(commits), repo_path)
    return commits


def _extract_branch_from_refs(refs: str) -> str:
    """
    Extract branch name from git log refs string.

    Args:
        refs: Git refs string (e.g., "HEAD -> main, origin/main").

    Returns:
        Branch name string, defaults to "main".
    """
    if refs:
        head_match = re.search(r"HEAD -> ([^\s,]+)", refs)
        if head_match:
            return head_match.group(1)
        if "->" in refs:
            return refs.split("->")[-1].strip().split(",")[0].strip()
    return "main"


def get_git_diff(
    repo_path: str,
    commit_hash: str,
    max_lines: int = 150,
) -> str:
    """
    Get the git diff for a single commit (parent vs commit).

    Used for git_diff depth mode — gives MAX THE DESTROYER actual code context.

    Args:
        repo_path: Absolute path to the git repository root.
        commit_hash: Full commit hash.
        max_lines: Maximum diff lines to include.

    Returns:
        Diff string. Empty string on error or first commit.
    """
    try:
        result = subprocess.run(
            ["git", "diff", f"{commit_hash}~1", commit_hash,
             "--unified=2", "--no-color"],
            capture_output=True, text=True, cwd=repo_path,
        )
        if result.returncode != 0:
            # First commit has no parent — return stat summary instead
            result = subprocess.run(
                ["git", "show", "--stat", "--no-patch", commit_hash],
                capture_output=True, text=True, cwd=repo_path, check=True,
            )

        diff_text = result.stdout.strip()
        lines = diff_text.splitlines()

        if len(lines) > max_lines:
            lines = lines[:max_lines] + [
                f"\n... ({len(lines) - max_lines} more lines truncated)"
            ]

        return "\n".join(lines)

    except subprocess.CalledProcessError as exc:
        LOGGER.warning("git diff failed for %s: %s", commit_hash[:7], exc.stderr)
        return ""


def get_current_branch(repo_path: str) -> str:
    """
    Get the current branch name.

    Args:
        repo_path: Path to the git repository.

    Returns:
        Current branch name, or "main" if not found.
    """
    try:
        result = subprocess.run(
            ["git", "branch", "--show-current"],
            capture_output=True, text=True, cwd=repo_path, check=True,
        )
        return result.stdout.strip() or "main"
    except subprocess.CalledProcessError:
        return "main"


def get_commit_count(repo_path: str) -> int:
    """
    Get the total number of commits in the repository.

    Args:
        repo_path: Path to the git repository.

    Returns:
        Number of commits, or 0 if not a git repo.
    """
    try:
        result = subprocess.run(
            ["git", "rev-list", "--count", "HEAD"],
            capture_output=True, text=True, cwd=repo_path, check=True,
        )
        return int(result.stdout.strip())
    except (subprocess.CalledProcessError, ValueError):
        return 0


def get_staged_diff(repo_path: str, max_lines: int = 200) -> str:
    """
    Get the staged diff (git add --cached).

    Args:
        repo_path: Path to the git repository.
        max_lines: Maximum diff lines to include.

    Returns:
        Staged diff string, or empty string if nothing staged.
    """
    try:
        result = subprocess.run(
            ["git", "diff", "--cached", "--unified=3", "--no-color"],
            capture_output=True, text=True, cwd=repo_path,
        )
        diff_text = result.stdout.strip()
        if not diff_text:
            return ""
        
        lines = diff_text.splitlines()
        if len(lines) > max_lines:
            lines = lines[:max_lines] + [
                f"\n... ({len(lines) - max_lines} more lines truncated)"
            ]
        return "\n".join(lines)
    except subprocess.CalledProcessError as exc:
        LOGGER.warning("git diff --cached failed: %s", exc.stderr)
        return ""


def get_unstaged_diff(repo_path: str, max_lines: int = 200) -> str:
    """
    Get the unstaged diff (working tree changes).

    Args:
        repo_path: Path to the git repository.
        max_lines: Maximum diff lines to include.

    Returns:
        Unstaged diff string, or empty string if nothing changed.
    """
    try:
        result = subprocess.run(
            ["git", "diff", "--unified=3", "--no-color"],
            capture_output=True, text=True, cwd=repo_path,
        )
        diff_text = result.stdout.strip()
        if not diff_text:
            return ""
        
        lines = diff_text.splitlines()
        if len(lines) > max_lines:
            lines = lines[:max_lines] + [
                f"\n... ({len(lines) - max_lines} more lines truncated)"
            ]
        return "\n".join(lines)
    except subprocess.CalledProcessError as exc:
        LOGGER.warning("git diff failed: %s", exc.stderr)
        return ""


def get_all_uncommitted_changes(repo_path: str, max_lines: int = 300) -> str:
    """
    Get all uncommitted changes (staged + unstaged).

    Args:
        repo_path: Path to the git repository.
        max_lines: Maximum diff lines to include.

    Returns:
        Combined diff string.
    """
    staged = get_staged_diff(repo_path, max_lines // 2)
    unstaged = get_unstaged_diff(repo_path, max_lines // 2)
    
    parts = []
    if staged:
        parts.append("=== STAGED CHANGES ===\n" + staged)
    if unstaged:
        if parts:
            parts.append("\n=== UNSTAGED CHANGES ===\n" + unstaged)
        else:
            parts.append(unstaged)
    
    return "\n".join(parts) if parts else ""


def has_uncommitted_changes(repo_path: str) -> bool:
    """
    Check if there are uncommitted changes.

    Args:
        repo_path: Path to the git repository.

    Returns:
        True if there are staged or unstaged changes.
    """
    staged = get_staged_diff(repo_path, max_lines=1)
    unstaged = get_unstaged_diff(repo_path, max_lines=1)
    return bool(staged or unstaged)


def git_commit(repo_path: str, message: str) -> bool:
    """
    Execute git commit with the given message.

    Args:
        repo_path: Path to the git repository.
        message: Commit message.

    Returns:
        True if commit succeeded, False otherwise.
    """
    try:
        result = subprocess.run(
            ["git", "commit", "-m", message],
            capture_output=True, text=True, cwd=repo_path, check=True,
        )
        LOGGER.info("Git commit successful: %s", message[:50])
        return True
    except subprocess.CalledProcessError as exc:
        LOGGER.error("Git commit failed: %s", exc.stderr)
        return False


def git_push(repo_path: str, remote: str = "origin") -> bool:
    """
    Push to remote repository.

    Args:
        repo_path: Path to the git repository.
        remote: Remote name (default: origin).

    Returns:
        True if push succeeded, False otherwise.
    """
    try:
        # Get current branch
        branch = get_current_branch(repo_path)
        result = subprocess.run(
            ["git", "push", remote, branch],
            capture_output=True, text=True, cwd=repo_path, check=True,
        )
        LOGGER.info("Git push successful to %s/%s", remote, branch)
        return True
    except subprocess.CalledProcessError as exc:
        LOGGER.error("Git push failed: %s", exc.stderr)
        return False
