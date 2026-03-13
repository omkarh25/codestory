"""
Commit message generation pipeline for codeStory.

Generates LLM-powered commit messages from git diffs.
"""

import os
import re
import subprocess
from typing import Any, Dict, Optional, Tuple

from codestory.core.logging import get_logger
from codestory.director import load_commit_prompt
from codestory.pipeline.git import (
    get_all_uncommitted_changes,
    has_uncommitted_changes,
    git_commit as do_git_commit,
    git_push as do_git_push,
    get_current_branch,
)

LOGGER = get_logger(__name__)

# Check for Anthropic SDK
try:
    import anthropic
    ANTHROPIC_AVAILABLE = True
except ImportError:
    ANTHROPIC_AVAILABLE = False


def build_llm_client(provider: str = "anthropic", model: str = "claude-haiku-4-5-20251001"):
    """Build an Anthropic-compatible async LLM client."""
    if not ANTHROPIC_AVAILABLE:
        raise ImportError("anthropic SDK not installed. Run: pip install anthropic")

    if provider == "anthropic":
        api_key = os.getenv("ANTHROPIC_API_KEY", "").strip()
        if not api_key:
            raise EnvironmentError("ANTHROPIC_API_KEY not set in llm.env")
        return anthropic.AsyncAnthropic(api_key=api_key)
    elif provider == "minimax":
        api_key = os.getenv("MINIMAX_API_KEY", "").strip()
        if not api_key:
            raise EnvironmentError("MINIMAX_API_KEY not set in llm.env")
        return anthropic.AsyncAnthropic(
            api_key=api_key,
            base_url="https://api.minimax.io/anthropic",
        )
    else:
        raise ValueError(f"Unsupported provider: '{provider}'")


async def generate_commit_message(
    client,
    model: str,
    diff: str,
    system_prompt: str,
) -> str:
    """
    Generate a commit message from git diff.

    Args:
        client: AsyncAnthropic client.
        model: Model identifier.
        diff: Git diff string.
        system_prompt: Commit signature prompt.

    Returns:
        Generated commit message, or empty string on failure.
    """
    user_prompt = (
        "Generate a commit message for the following git diff.\n\n"
        "DIFF:\n" + diff
    )

    LOGGER.info("Generating commit message from diff (%d chars)", len(diff))

    try:
        response = await client.messages.create(
            model=model,
            max_tokens=500,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
            temperature=0.7,
        )

        text_block = next(
            (b for b in response.content if getattr(b, "type", "") == "text"),
            None,
        )
        if text_block is None:
            LOGGER.error("No text block in LLM response")
            return ""

        raw = text_block.text.strip()
        
        # Clean up markdown fences if present
        raw = re.sub(r"^```[a-z]*\n?", "", raw)
        raw = re.sub(r"\n?```$", "", raw)
        
        # Check for "nope: no changes" response
        if raw.lower().startswith("nope:"):
            LOGGER.info("No changes detected by LLM")
            return ""
        
        LOGGER.info("Generated commit message: %s", raw[:80])
        return raw.strip()

    except Exception as exc:
        LOGGER.error("Failed to generate commit message: %s", exc)
        return ""


async def run_commit_pipeline(
    config: Dict[str, Any],
    do_push: bool = False,
    do_ytshorts: bool = True,
) -> Tuple[bool, str]:
    """
    Run the commit message generation and git commit/push pipeline.

    Args:
        config: Configuration dict.
        do_push: Whether to push after commit.
        do_ytshorts: Whether to generate YouTube shorts (for main __main__ flow).

    Returns:
        Tuple of (success: bool, commit_hash: str)
    """
    import asyncio

    repo_path = config.get("repo_path", ".")
    provider = config.get("haiku", {}).get("provider", "anthropic")
    model = config.get("haiku", {}).get("model", "claude-haiku-4-5-20251001")

    # Check for uncommitted changes
    if not has_uncommitted_changes(repo_path):
        LOGGER.info("No uncommitted changes to commit")
        return False, ""

    # Get diff
    diff = get_all_uncommitted_changes(repo_path)
    if not diff:
        LOGGER.warning("No diff found")
        return False, ""

    # Build LLM client
    try:
        client = build_llm_client(provider, model)
    except Exception as exc:
        LOGGER.error("Cannot build LLM client: %s", exc)
        raise

    # Load commit signature prompt
    system_prompt = load_commit_prompt()

    # Generate commit message
    commit_msg = await generate_commit_message(client, model, diff, system_prompt)
    
    if not commit_msg:
        return False, ""

    # Stage all changes before committing
    try:
        subprocess.run(
            ["git", "add", "-A"],
            capture_output=True, cwd=repo_path, check=True,
        )
    except subprocess.CalledProcessError as exc:
        LOGGER.warning("git add -A failed: %s", exc.stderr)

    # Execute git commit
    if not do_git_commit(repo_path, commit_msg):
        return False, ""

    # Get the commit hash we just created
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True, text=True, cwd=repo_path, check=True,
        )
        commit_hash = result.stdout.strip()[:8]
    except subprocess.CalledProcessError:
        commit_hash = "unknown"

    # Push if requested
    if do_push:
        if not do_git_push(repo_path):
            LOGGER.warning("Push failed, but commit succeeded")
        else:
            # Get remote info
            branch = get_current_branch(repo_path)
            LOGGER.info("Pushed to origin/%s", branch)

    return True, commit_hash


def generate_commit_message_sync(
    config: Optional[Dict[str, Any]] = None,
) -> Optional[str]:
    """
    Generate commit message synchronously (for CLI use).

    Args:
        config: Optional config overrides.

    Returns:
        Generated commit message, or None on failure.
    """
    import asyncio

    cfg = config if config else {}

    # Get diff
    repo_path = cfg.get("repo_path", ".")
    diff = get_all_uncommitted_changes(repo_path)
    
    if not diff:
        return None

    provider = cfg.get("haiku", {}).get("provider", "anthropic")
    model = cfg.get("haiku", {}).get("model", "claude-haiku-4-5-20251001")

    try:
        client = build_llm_client(provider, model)
    except Exception as exc:
        LOGGER.error("Cannot build LLM client: %s", exc)
        raise

    system_prompt = load_commit_prompt()

    try:
        # Always create a fresh event loop
        return asyncio.run(generate_commit_message(client, model, diff, system_prompt))
    except Exception as exc:
        LOGGER.error("Commit message generation failed: %s", exc)
        return None


def commit_and_push(
    config: Optional[Dict[str, Any]] = None,
    do_push: bool = False,
) -> Tuple[bool, str]:
    """
    Generate commit message, commit, and optionally push.

    Args:
        config: Optional config overrides.
        do_push: Whether to push after commit.

    Returns:
        Tuple of (success: bool, commit_hash: str)
    """
    import asyncio

    cfg = config if config else load_config() if config is None else config

    try:
        # Always create a fresh event loop to avoid threading issues
        return asyncio.run(run_commit_pipeline(cfg, do_push=do_push))
    except Exception as exc:
        LOGGER.error("Commit pipeline failed: %s", exc)
        return False, ""
