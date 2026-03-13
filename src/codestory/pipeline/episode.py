"""
Episode generation pipeline for codeStory.

Reads haikus from DB and generates episodic acts via LLM.
"""

import json
import os
import re
from typing import Any, Dict, List, Optional

from codestory.core import DatabaseManager, load_config
from codestory.core.logging import get_logger
from codestory.director import load_episode_prompt

from codestory.pipeline.haiku import build_llm_client

LOGGER = get_logger(__name__)


async def generate_episode_batch(
    client,
    model: str,
    episode_number: int,
    haiku_rows: List[Dict[str, Any]],
    system_prompt: str,
    depth: str = "git_commit",
    repo_path: str = ".",
) -> Dict[str, Any]:
    """Generate an episode from haiku rows."""
    haiku_digest = []
    for row in haiku_rows:
        haiku_digest.append({
            "commit_hash": (row.get("commit_hash") or "")[:7],
            "date": (row.get("commit_date") or "")[:10],
            "type": row.get("commit_type", "other"),
            "commit_msg": row.get("commit_msg", ""),
            "branch": row.get("branch", "main"),
            "title": row.get("title", ""),
            "when_where": row.get("when_where", ""),
            "who_whom": row.get("who_whom", ""),
            "what_why": row.get("what_why", ""),
            "verdict": row.get("verdict", ""),
        })

    branches = [r.get("branch", "main") for r in haiku_rows if r.get("branch")]
    dominant_branch = max(set(branches), key=branches.count) if branches else "main"

    user_prompt = (
        f"Generate EPISODE ACT {episode_number} of The codeStory Chronicles.\n\n"
        f"This episode covers {len(haiku_rows)} commits on branch '{dominant_branch}'.\n"
        f"Date range: {haiku_digest[0]['date']} → {haiku_digest[-1]['date']}.\n\n"
        "Here are the 3-act haiku case files:\n\n"
        + json.dumps(haiku_digest, indent=2)
        + "\n\nSynthesise into one EPISODE ACT. Return JSON with: title, decade_summary, branch_note, max_ruling."
    )

    LOGGER.info("Generating episode %d", episode_number)

    try:
        response = await client.messages.create(
            model=model,
            max_tokens=1400,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
            temperature=0.85,
        )

        text_block = next(
            (b for b in response.content if getattr(b, "type", "") == "text"),
            None,
        )
        if text_block is None:
            return _fallback_episode(episode_number, dominant_branch)

        raw = text_block.text.strip()
        raw = re.sub(r"^```[a-z]*\n?", "", raw)
        raw = re.sub(r"\n?```$", "", raw)

        episode_data = json.loads(raw)
        return episode_data

    except Exception as exc:
        LOGGER.error("Episode generation failed: %s", exc)
        return _fallback_episode(episode_number, dominant_branch)


def _fallback_episode(episode_number: int, branch: str) -> Dict[str, Any]:
    """Fallback episode when LLM fails."""
    return {
        "title": f'EPISODE ACT {episode_number}: "THE UNWRITTEN CHAPTER"',
        "decade_summary": "The investigation stalled. The evidence was there. But the narrator refused to speak.",
        "branch_note": f"Branch: `{branch}` — The operation continued in silence.",
        "max_ruling": "The system failed. The irony is: he built this too.",
    }


async def run_episode_pipeline(config: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Run the episode generation pipeline."""
    import asyncio

    db_path = config.get("db_path", ".codestory/codestory.db")
    repo_path = config.get("repo_path", ".")
    episode_config = config.get("episode", {})
    haiku_per_episode = episode_config.get("haikus_per_episode", 10)

    provider = episode_config.get("provider", "anthropic")
    model = episode_config.get("model", "claude-haiku-4-5-20251001")
    depth = episode_config.get("depth", "git_commit")

    LOGGER.info("Starting episode pipeline: haikus_per_episode=%d", haiku_per_episode)

    # Build LLM client
    try:
        client = build_llm_client(provider, model)
    except Exception as exc:
        LOGGER.error("Cannot build LLM client: %s", exc)
        raise

    # Open DB
    db = DatabaseManager(db_path)

    # Check uncompiled haikus
    uncompiled = db.get_uncompiled_haikus(limit=haiku_per_episode)
    if len(uncompiled) < haiku_per_episode:
        LOGGER.info("Not enough haikus: %d/%d", len(uncompiled), haiku_per_episode)
        return []

    # Generate episode
    episode_number = db.get_next_episode_number()
    system_prompt = load_episode_prompt()

    episode_data = await generate_episode_batch(
        client, model, episode_number, uncompiled, system_prompt, depth, repo_path
    )

    # Save to DB
    commit_hashes = [h.get("commit_hash", "") for h in uncompiled]
    db.save_episode(episode_number, episode_data, commit_hashes)

    LOGGER.info("Generated episode %d", episode_number)
    return [episode_data]


def generate_episodes(config: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    """
    Generate episodes from pending haikus.

    Args:
        config: Optional config overrides.

    Returns:
        List of generated episode dicts.
    """
    import asyncio

    cfg = load_config(overrides=config) if config else load_config()

    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                future = pool.submit(asyncio.run, run_episode_pipeline(cfg))
                return future.result()
        else:
            return asyncio.run(run_episode_pipeline(cfg))
    except Exception as exc:
        LOGGER.error("Episode pipeline failed: %s", exc)
        raise
