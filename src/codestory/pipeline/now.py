"""
Now pipeline for codeStory.

The --now command: synthesises the current moment (TODO files, unstaged diff,
recent commits) into a single clearing-the-mind haiku via MAX THE DESTROYER.

The resulting moment is saved to the `now_moments` DB table for later browsing.
"""

import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from codestory.core import DatabaseManager, load_config
from codestory.core.logging import get_logger
from codestory.director import load_now_prompt
from codestory.pipeline.git import (
    get_unstaged_diff,
    get_staged_diff,
    read_git_log,
)

LOGGER = get_logger(__name__)


# ---------------------------------------------------------------------------
# Context collection helpers
# ---------------------------------------------------------------------------

def load_todo_files(repo_path: str) -> str:
    """
    Hierarchically load TODO content from known locations.

    Search order:
    1. {repo_path}/TODO.md
    2. {repo_path}/.codestory/TODO.md

    Both files are merged if they exist; duplicates are not de-duplicated.

    Args:
        repo_path: Absolute path to the repository root.

    Returns:
        Combined TODO text (may be empty string if no files found).
    """
    parts: List[str] = []
    root = Path(repo_path)

    candidates = [
        root / "TODO.md",
        root / ".codestory" / "TODO.md",
    ]

    for path in candidates:
        if path.exists():
            try:
                text = path.read_text(encoding="utf-8").strip()
                if text:
                    LOGGER.info("Loaded TODO from %s (%d chars)", path, len(text))
                    parts.append(f"[from {path.name}]\n{text}")
            except OSError as exc:
                LOGGER.warning("Could not read %s: %s", path, exc)

    result = "\n\n".join(parts)
    LOGGER.debug("TODO total length: %d chars", len(result))
    return result


def get_combined_diff(repo_path: str, max_lines: int = 300) -> str:
    """
    Get all current local changes (staged + unstaged).

    Args:
        repo_path: Absolute path to the repository root.
        max_lines: Maximum diff lines to include.

    Returns:
        Combined diff string (may be empty if nothing changed).
    """
    staged = get_staged_diff(repo_path, max_lines // 2)
    unstaged = get_unstaged_diff(repo_path, max_lines // 2)

    parts = []
    if staged:
        parts.append("=== STAGED CHANGES ===\n" + staged)
    if unstaged:
        parts.append("=== UNSTAGED CHANGES ===\n" + unstaged)

    combined = "\n\n".join(parts)
    LOGGER.debug("Combined diff: %d chars", len(combined))
    return combined


def get_recent_commits(repo_path: str, n: int = 3) -> List[Dict[str, str]]:
    """
    Fetch the N most recent commits from the git log.

    Args:
        repo_path: Absolute path to the repository root.
        n: Number of recent commits to retrieve.

    Returns:
        List of commit dicts (newest first), each with:
        hash, type, subject (msg), branch, author, date.
    """
    commits = read_git_log(repo_path, limit=n)
    LOGGER.info("Fetched %d recent commits from %s", len(commits), repo_path)
    return commits


# ---------------------------------------------------------------------------
# LLM call
# ---------------------------------------------------------------------------

async def _call_now_llm(
    client: Any,
    model: str,
    context: Dict[str, Any],
    system_prompt: str,
) -> Optional[Dict[str, Any]]:
    """
    Call the LLM with the Now context and return one haiku dict.

    Args:
        client: AsyncAnthropic (or compatible) client.
        model: Model identifier string.
        context: Dict with keys: todos, diff, recent_commits, captured_at.
        system_prompt: Director/Now.md content.

    Returns:
        Haiku dict with keys: title, subtitle, act1_title, when_where,
        act2_title, who_whom, act3_title, what_why, verdict.
        Returns None on failure.
    """
    # Summarise recent commits for the prompt
    commits_summary = []
    for c in context.get("recent_commits", []):
        commits_summary.append({
            "hash":    c.get("hash", "")[:7],
            "type":    c.get("type", "other"),
            "subject": c.get("msg", ""),
            "date":    c.get("date", ""),
            "branch":  c.get("branch", "main"),
        })

    user_prompt = (
        "You are looking at the developer's current moment.\n\n"
        "Synthesise everything below into ONE 3-act clarity haiku.\n\n"
        "=== CONTEXT ===\n"
        + json.dumps({
            "captured_at":     context["captured_at"],
            "todos":           context["todos"] or "(none)",
            "diff":            context["diff"] or "(no uncommitted changes)",
            "recent_commits":  commits_summary,
        }, indent=2)
        + "\n\n"
        "Return ONLY a valid JSON object (no fences, no prose) with these exact keys:\n"
        "title, subtitle, act1_title, when_where, act2_title, who_whom, "
        "act3_title, what_why, verdict"
    )

    LOGGER.info("Sending Now context to model=%s (diff=%d chars, todos=%d chars)",
                model, len(context["diff"]), len(context["todos"]))

    try:
        response = await client.messages.create(
            model=model,
            max_tokens=1500,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
            temperature=0.75,
        )

        text_block = next(
            (b for b in response.content if getattr(b, "type", "") == "text"),
            None,
        )
        if text_block is None:
            LOGGER.error("No text block in Now LLM response")
            return None

        raw = text_block.text.strip()
        raw = re.sub(r"^```[a-z]*\n?", "", raw)
        raw = re.sub(r"\n?```$", "", raw)

        haiku = json.loads(raw)
        LOGGER.info("Received Now haiku: %s", haiku.get("title", "?"))
        return haiku

    except json.JSONDecodeError as exc:
        LOGGER.error("Failed to parse Now haiku JSON: %s", exc)
        return None
    except Exception as exc:
        LOGGER.error("Now LLM call failed: %s", exc)
        return None


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

async def run_now_pipeline(config: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Run the --now pipeline end-to-end.

    Steps:
    1. Load TODO files from repo root and .codestory/
    2. Collect current diff (staged + unstaged)
    3. Get last N recent commits
    4. Call LLM for ONE synthesis haiku
    5. Save to now_moments DB table
    6. Return the saved moment dict

    Args:
        config: Full codeStory config dict.

    Returns:
        The saved moment dict (all haiku fields + DB metadata), or None on failure.
    """
    from codestory.pipeline.haiku import build_llm_client

    repo_path = config.get("repo_path", ".")
    db_path = config.get("db_path", ".codestory/codestory.db")
    haiku_cfg = config.get("haiku", {})

    provider = haiku_cfg.get("provider", "anthropic")
    model    = haiku_cfg.get("model",    "claude-haiku-4-5-20251001")
    n_commits = config.get("now_commits", 3)

    captured_at = datetime.now().isoformat()
    LOGGER.info("Starting Now pipeline at %s", captured_at)

    # 1. Collect context
    todos          = load_todo_files(repo_path)
    diff           = get_combined_diff(repo_path)
    recent_commits = get_recent_commits(repo_path, n_commits)

    context: Dict[str, Any] = {
        "captured_at":    captured_at,
        "todos":          todos,
        "diff":           diff,
        "recent_commits": recent_commits,
    }

    LOGGER.info(
        "Now context: todos=%d chars, diff=%d chars, commits=%d",
        len(todos), len(diff), len(recent_commits),
    )

    # 2. Build LLM client
    try:
        client = build_llm_client(provider, model)
    except Exception as exc:
        LOGGER.error("Cannot build LLM client for --now: %s", exc)
        raise

    # 3. Load Now prompt
    system_prompt = load_now_prompt()

    # 4. Call LLM
    haiku = await _call_now_llm(client, model, context, system_prompt)
    if haiku is None:
        LOGGER.error("Now LLM returned nothing")
        return None

    # 5. Save to DB
    db = DatabaseManager(db_path)
    moment = db.save_moment(
        haiku_data=haiku,
        captured_at=captured_at,
        todo_snapshot=todos,
        diff_snapshot=diff,
        commits_snapshot=recent_commits,
    )

    LOGGER.info("Now moment saved: id=%s title=%s", moment.get("id"), moment.get("title"))
    return moment


def generate_now(config: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    """
    Public entry point: generate a single Now moment haiku.

    Loads config, runs the async pipeline synchronously, returns the moment.

    Args:
        config: Optional config dict overrides.

    Returns:
        The saved moment dict, or None on failure.
    """
    import asyncio

    cfg = load_config(overrides=config) if config else load_config()

    try:
        return asyncio.run(run_now_pipeline(cfg))
    except Exception as exc:
        LOGGER.error("Now pipeline failed: %s", exc)
        raise
