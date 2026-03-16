"""
Haiku generation pipeline for codeStory.

Reads git commits and generates noir haikus via LLM.

Key features:
- Hash-based coupling: commit_hash is the permanent identifier
- Retry logic: failed generations are retried with exponential backoff
- Progress callbacks: real-time feedback during generation
"""

import json
import os
import re
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

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


# Progress callback type
ProgressCallback = Optional[Callable[[str, str, Any], None]]


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
    max_retries: int = 2,
    progress_callback: ProgressCallback = None,
) -> List[Dict[str, Any]]:
    """
    Generate haikus for a batch of commits with retry logic.

    Args:
        client: AsyncAnthropic client.
        model: Model identifier.
        commits: List of commit dicts.
        system_prompt: Director prompt.
        depth: git_commit or git_diff.
        repo_path: Repository path.
        max_retries: Maximum retry attempts for failed generations.
        progress_callback: Optional callback for progress updates.

    Returns:
        List of haiku dicts (may be fewer than commits if some failed permanently).
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

    # Notify progress
    if progress_callback:
        progress_callback("sending", f"Sending {len(commits)} commits to LLM", None)

    LOGGER.info("Sending haiku batch of %d commits to model=%s", len(commits), model)

    # Retry loop with exponential backoff
    last_error = None
    for attempt in range(max_retries + 1):
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
                if attempt < max_retries:
                    wait_time = 2 ** attempt
                    LOGGER.info(f"Retrying in {wait_time}s (attempt {attempt + 1}/{max_retries})")
                    time.sleep(wait_time)
                    continue
                return []

            raw = text_block.text.strip()
            raw = re.sub(r"^```[a-z]*\n?", "", raw)
            raw = re.sub(r"\n?```$", "", raw)

            haiku_list = json.loads(raw)
            LOGGER.info("Received %d haikus from LLM", len(haiku_list))
            
            # Notify progress
            if progress_callback:
                progress_callback("received", f"Received {len(haiku_list)} haikus", len(haiku_list))
            
            return haiku_list

        except json.JSONDecodeError as exc:
            LOGGER.error("Failed to parse haiku JSON: %s", exc)
            last_error = exc
            if attempt < max_retries:
                wait_time = 2 ** attempt
                LOGGER.info(f"JSON parse error, retrying in {wait_time}s (attempt {attempt + 1}/{max_retries})")
                time.sleep(wait_time)
            continue
        except Exception as exc:
            LOGGER.error("LLM call failed: %s", exc)
            last_error = exc
            if attempt < max_retries:
                wait_time = 2 ** attempt
                LOGGER.info(f"LLM error, retrying in {wait_time}s (attempt {attempt + 1}/{max_retries})")
                time.sleep(wait_time)
            continue

    # All retries exhausted
    LOGGER.error("All %d retries exhausted for haiku batch", max_retries)
    if progress_callback:
        progress_callback("failed", f"All retries failed: {last_error}", None)
    return []


async def run_haiku_pipeline(
    config: Dict[str, Any],
    progress_callback: ProgressCallback = None,
) -> Dict[str, Any]:
    """
    Run the haiku generation pipeline with proper hash-based coupling.
    
    Key changes from original:
    - commit_hash is used as the permanent identifier
    - chronological_index is computed dynamically at render time
    - Failed generations are tracked and reported
    - Progress callback provides real-time updates

    Args:
        config: Configuration dict.
        progress_callback: Optional callback for progress updates.

    Returns:
        Dict with keys: 'generated' (list), 'failed' (list), 'total' (int).
    """
    import asyncio

    db_path = config.get("db_path", ".codestory/codestory.db")
    repo_path = config.get("repo_path", ".")
    haiku_config = config.get("haiku", {})

    max_per_run = haiku_config.get("max_per_run", 12)
    batch_size = haiku_config.get("batch_size", 3)
    provider = haiku_config.get("provider", "anthropic")
    model = haiku_config.get("model", "claude-haiku-4-5-20251001")
    depth = haiku_config.get("depth", "git_commit")
    max_retries = haiku_config.get("max_retries", 2)

    # Notify start
    if progress_callback:
        progress_callback("starting", "Initializing haiku pipeline", None)

    LOGGER.info("Starting haiku pipeline: max=%d, depth=%s", max_per_run, depth)

    # Build LLM client
    try:
        client = build_llm_client(provider, model)
    except Exception as exc:
        LOGGER.error("Cannot build LLM client: %s", exc)
        if progress_callback:
            progress_callback("error", f"Cannot build LLM client: {exc}", None)
        raise

    # Open DB
    db = DatabaseManager(db_path)
    processed_hashes = {h["commit_hash"] for h in db.get_all_haikus()}

    # Notify git read
    if progress_callback:
        progress_callback("git", "Reading git log", None)

    # Get commits
    all_commits = read_git_log(repo_path, limit=500)
    all_commits_reversed = list(reversed(all_commits))  # oldest first

    new_commits = [c for c in all_commits_reversed if c["hash"] not in processed_hashes]
    new_commits = new_commits[:max_per_run]

    if not new_commits:
        LOGGER.info("No new commits to process")
        if progress_callback:
            progress_callback("complete", "No new commits to process", 0)
        return {"generated": [], "failed": [], "total": 0}

    # Notify commits found
    if progress_callback:
        progress_callback("commits", f"Found {len(new_commits)} new commits", len(new_commits))

    # Chronological index map - used for display/render order, NOT as primary key
    # This is computed but commit_hash remains the permanent identifier
    chron_index_map = {c["hash"]: i + 1 for i, c in enumerate(all_commits_reversed)}

    # Load prompt
    system_prompt = load_haiku_prompt()

    results = []
    failed_commits = []
    
    total_batches = (len(new_commits) + batch_size - 1) // batch_size
    
    for batch_num, batch_start in enumerate(range(0, len(new_commits), batch_size)):
        batch = new_commits[batch_start:batch_start + batch_size]
        
        # Notify batch start
        if progress_callback:
            progress_callback(
                "batch", 
                f"Processing batch {batch_num + 1}/{total_batches}", 
                batch_num + 1
            )

        haiku_list = await generate_haiku_batch(
            client, model, batch, system_prompt, depth, repo_path,
            max_retries=max_retries,
            progress_callback=progress_callback,
        )

        # Map haikus by full_hash for O(1) lookup
        haiku_map = {h.get("full_hash", ""): h for h in haiku_list}
        returned_hashes = set(haiku_map.keys())

        for commit in batch:
            commit_hash = commit["hash"]
            haiku = haiku_map.get(commit_hash)
            
            if haiku:
                # Success - save to DB
                chron_idx = chron_index_map.get(commit_hash, 0)
                db.save_haiku(commit, haiku, chron_idx)
                
                results.append({
                    "hash": commit_hash,
                    "short_hash": commit_hash[:7],
                    "chronological_index": chron_idx,
                    "title": haiku.get("title", ""),
                    "commit_msg": commit.get("msg", ""),
                })
                
                if progress_callback:
                    progress_callback(
                        "saved", 
                        f"✓ {commit_hash[:7]}: {haiku.get('title', 'Untitled')[:40]}", 
                        commit_hash
                    )
            else:
                # Failed - track for retry
                failed_commits.append({
                    "hash": commit_hash,
                    "short_hash": commit_hash[:7],
                    "msg": commit.get("msg", ""),
                    "branch": commit.get("branch", "main"),
                })
                
                if progress_callback:
                    progress_callback(
                        "failed_commit", 
                        f"⚠ {commit_hash[:7]}: generation failed", 
                        commit_hash
                    )

    LOGGER.info("Generated %d haikus, %d failed", len(results), len(failed_commits))
    
    # Notify completion
    if progress_callback:
        progress_callback(
            "complete", 
            f"Generated {len(results)} haikus, {len(failed_commits)} failed", 
            len(results)
        )

    return {
        "generated": results,
        "failed": failed_commits,
        "total": len(new_commits),
    }


def generate_haikus(
    config: Optional[Dict[str, Any]] = None,
    progress_callback: ProgressCallback = None,
) -> List[Dict[str, Any]]:
    """
    Generate haikus from git commits.

    Args:
        config: Optional config overrides.
        progress_callback: Optional callback for progress updates.

    Returns:
        List of generated haiku dicts.
    """
    import asyncio

    cfg = load_config(overrides=config) if config else load_config()

    try:
        # Create a new event loop to avoid issues with existing loops
        result = asyncio.run(run_haiku_pipeline(cfg, progress_callback))
        return result.get("generated", [])
    except Exception as exc:
        LOGGER.error("Haiku pipeline failed: %s", exc)
        raise
