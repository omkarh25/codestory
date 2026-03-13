"""
Haiku generation pipeline for codeStory.

Reads git commits and generates noir haikus via LLM.
"""

import json
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from codestory.core import DatabaseManager, load_config
from codestory.core.logging import get_logger
from codestory.director import load_haiku_prompt
from codestory.pipeline.git import (
    GIT_CRIME_LEXICON,
    read_git_log,
    get_git_diff,
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


async def generate_haiku_batch(
    client,
    model: str,
    commits: List[Dict[str, str]],
    system_prompt: str,
    depth: str = "git_commit",
    repo_path: str = ".",
) -> List[Dict[str, Any]]:
    """
    Generate haikus for a batch of commits.

    Args:
        client: AsyncAnthropic client.
        model: Model identifier.
        commits: List of commit dicts.
        system_prompt: Director prompt.
        depth: git_commit or git_diff.
        repo_path: Repository path.

    Returns:
        List of haiku dicts.
    """
    commits_payload = []
    for c in commits:
        role = GIT_CRIME_LEXICON.get(c["type"], f"Unknown crime — {c['type']}")
        entry = {
            "full_hash": c["hash"],
            "hash": c["hash"][:7],
            "type": c["type"],
            "subject": c["msg"],
            "branch": c["branch"],
            "author": c["author"],
            "date": c["date"],
            "narrative_role": role,
        }
        if depth == "git_diff":
            diff = get_git_diff(repo_path, c["hash"])
            if diff:
                entry["git_diff"] = diff

        commits_payload.append(entry)

    depth_note = (
        "You have been given the full git diff. Use actual function names, class names. "
        "Be specific. Name the functions. This is an autopsy, not a metaphor."
        if depth == "git_diff"
        else "You have been given only the commit message. Infer. Imagine. Be devastating."
    )

    user_prompt = (
        f"Generate a 3-act noir case file for each of the following {len(commits)} git commits.\n\n"
        f"DEPTH: {depth.upper()} — {depth_note}\n\n"
        f"Return a JSON array with exactly {len(commits)} objects in the same order.\n"
        "Each object MUST have exactly these keys:\n"
        '  "full_hash"  : the full commit hash\n'
        '  "title"      : "CASE FILE — <short punchy label>"\n'
        '  "subtitle"   : one-line movie-poster tagline\n'
        '  "act1_title" : 2-5 word dramatic noir title for Act I\n'
        '  "when_where" : Act 1 — setting, time, branch (1-3 sentences)\n'
        '  "act2_title" : 2-5 word dramatic noir title for Act II\n'
        '  "who_whom"   : Act 2 — who acted on whom, stakes (1-3 sentences)\n'
        '  "act3_title" : 2-5 word dramatic noir title for Act III\n'
        '  "what_why"   : Act 3 — action, consequence (2-4 sentences)\n'
        '  "verdict"    : one cold, final line judging the man\n\n'
        "Commits:\n" + json.dumps(commits_payload, indent=2)
    )

    LOGGER.info("Sending haiku batch of %d commits to model=%s", len(commits), model)

    try:
        response = await client.messages.create(
            model=model,
            max_tokens=2000,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
            temperature=0.8,
        )

        text_block = next(
            (b for b in response.content if getattr(b, "type", "") == "text"),
            None,
        )
        if text_block is None:
            LOGGER.error("No text block in LLM response")
            return []

        raw = text_block.text.strip()
        raw = re.sub(r"^```[a-z]*\n?", "", raw)
        raw = re.sub(r"\n?```$", "", raw)

        haiku_list = json.loads(raw)
        LOGGER.info("Received %d haikus from LLM", len(haiku_list))
        return haiku_list

    except json.JSONDecodeError as exc:
        LOGGER.error("Failed to parse haiku JSON: %s", exc)
        return []
    except Exception as exc:
        LOGGER.error("LLM call failed: %s", exc)
        return []


async def run_haiku_pipeline(config: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Run the haiku generation pipeline."""
    import asyncio

    db_path = config.get("db_path", ".codestory/codestory.db")
    repo_path = config.get("repo_path", ".")
    haiku_config = config.get("haiku", {})

    max_per_run = haiku_config.get("max_per_run", 12)
    batch_size = haiku_config.get("batch_size", 3)
    provider = haiku_config.get("provider", "anthropic")
    model = haiku_config.get("model", "claude-haiku-4-5-20251001")
    depth = haiku_config.get("depth", "git_commit")

    LOGGER.info("Starting haiku pipeline: max=%d, depth=%s", max_per_run, depth)

    # Build LLM client
    try:
        client = build_llm_client(provider, model)
    except Exception as exc:
        LOGGER.error("Cannot build LLM client: %s", exc)
        raise

    # Open DB
    db = DatabaseManager(db_path)
    processed_hashes = {h["commit_hash"] for h in db.get_all_haikus()}

    # Get commits
    all_commits = read_git_log(repo_path, limit=500)
    all_commits_reversed = list(reversed(all_commits))  # oldest first

    new_commits = [c for c in all_commits_reversed if c["hash"] not in processed_hashes]
    new_commits = new_commits[:max_per_run]

    if not new_commits:
        LOGGER.info("No new commits to process")
        return []

    # Chronological index map
    chron_index_map = {c["hash"]: i + 1 for i, c in enumerate(all_commits_reversed)}

    # Load prompt
    system_prompt = load_haiku_prompt()

    results = []
    for batch_start in range(0, len(new_commits), batch_size):
        batch = new_commits[batch_start:batch_start + batch_size]

        haiku_list = await generate_haiku_batch(
            client, model, batch, system_prompt, depth, repo_path
        )

        haiku_map = {h.get("full_hash", ""): h for h in haiku_list}

        for commit in batch:
            haiku = haiku_map.get(commit["hash"])
            if not haiku:
                continue

            chron_idx = chron_index_map.get(commit["hash"], 0)

            # Save to DB (which also writes JSON)
            db.save_haiku(commit, haiku, chron_idx)

            results.append({
                "hash": commit["hash"],
                "chronological_index": chron_idx,
                "title": haiku.get("title", ""),
            })

    LOGGER.info("Generated %d haikus", len(results))
    return results


def generate_haikus(config: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    """
    Generate haikus from git commits.

    Args:
        config: Optional config overrides.

    Returns:
        List of generated haiku dicts.
    """
    import asyncio

    cfg = load_config(overrides=config) if config else load_config()

    try:
        # Create a new event loop to avoid issues with existing loops
        # This is the safest approach - always create fresh
        return asyncio.run(run_haiku_pipeline(cfg))
    except Exception as exc:
        LOGGER.error("Haiku pipeline failed: %s", exc)
        raise
