"""
Public repo haiku generation pipeline for codeStory.

Generates haikus for public GitHub repos using bare git clones.
"""

import json
import os
import re
import subprocess
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from codestory.core import DatabaseManager, load_config
from codestory.core.logging import get_logger
from codestory.core.public_repo import (
    get_repo_dir,
    get_repo_db_path,
    get_repo_git_dir,
    get_public_repo,
)
from codestory.director import load_haiku_prompt
from codestory.pipeline.git import (
    GIT_CRIME_LEXICON,
    parse_commit_type,
)

LOGGER = get_logger(__name__)

# Progress callback type
ProgressCallback = Optional[Callable[[str, str, Any], None]]


def read_git_log_from_bare(bare_repo_path: str, limit: int = 500) -> List[Dict[str, str]]:
    """
    Read git log from a bare repository.
    
    Args:
        bare_repo_path: Path to bare git repo
        limit: Maximum commits to retrieve
        
    Returns:
        List of commit dicts
    """
    sep = "|||"
    fmt = f"%H{sep}%ai{sep}%s{sep}%an{sep}%D"
    
    try:
        result = subprocess.run(
            ["git", "-C", bare_repo_path, "log", f"--pretty=format:{fmt}", f"-{limit}"],
            capture_output=True,
            text=True,
            check=True,
        )
    except subprocess.CalledProcessError as exc:
        LOGGER.error("git log failed in %s: %s", bare_repo_path, exc.stderr)
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
    
    LOGGER.info("git log parsed: %d commits from %s", len(commits), bare_repo_path)
    return commits


def _extract_branch_from_refs(refs: str) -> str:
    """Extract branch name from git refs."""
    import re
    if refs:
        head_match = re.search(r"HEAD -> ([^\s,]+)", refs)
        if head_match:
            return head_match.group(1)
        if "->" in refs:
            return refs.split("->")[-1].strip().split(",")[0].strip()
    return "main"


def get_git_diff_from_bare(bare_repo_path: str, commit_hash: str, max_lines: int = 150) -> str:
    """Get git diff for a commit from bare repo."""
    try:
        result = subprocess.run(
            ["git", "-C", bare_repo_path, "diff", f"{commit_hash}~1", commit_hash,
             "--unified=2", "--no-color"],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            result = subprocess.run(
                ["git", "-C", bare_repo_path, "show", "--stat", "--no-patch", commit_hash],
                capture_output=True,
                text=True,
                check=True,
            )
        
        diff_text = result.stdout.strip()
        lines = diff_text.splitlines()
        
        if len(lines) > max_lines:
            lines = lines[:max_lines] + [f"\n... ({len(lines) - max_lines} more lines)"]
        
        return "\n".join(lines)
    except Exception as exc:
        LOGGER.warning("git diff failed for %s: %s", commit_hash[:7], exc)
        return ""


def read_git_log_public(repo_path: str, limit: int = 500) -> List[Dict[str, str]]:
    """Read git log from a regular (non-bare) repo."""
    return read_git_log_from_bare(repo_path, limit)


async def generate_haiku_batch_public(
    client,
    model: str,
    commits: List[Dict[str, str]],
    system_prompt: str,
    depth: str = "git_commit",
    bare_repo_path: str = ".",
    max_retries: int = 2,
    progress_callback: ProgressCallback = None,
) -> List[Dict[str, Any]]:
    """
    Generate haikus for public repo commits.
    
    Same as generate_haiku_batch but for public repos.
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
            diff = get_git_diff_from_bare(bare_repo_path, c["hash"])
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
    
    if progress_callback:
        progress_callback("sending", f"Sending {len(commits)} commits to LLM", None)
    
    LOGGER.info("Sending haiku batch of %d commits to model=%s", len(commits), model)
    
    # Retry loop
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
                    LOGGER.info(f"Retrying in {wait_time}s")
                    time.sleep(wait_time)
                    continue
                return []
            
            raw = text_block.text.strip()
            raw = re.sub(r"^```[a-z]*\n?", "", raw)
            raw = re.sub(r"\n?```$", "", raw)
            
            haiku_list = json.loads(raw)
            LOGGER.info("Received %d haikus from LLM", len(haiku_list))
            
            if progress_callback:
                progress_callback("received", f"Received {len(haiku_list)} haikus", len(haiku_list))
            
            return haiku_list
            
        except json.JSONDecodeError as exc:
            LOGGER.error("Failed to parse haiku JSON: %s", exc)
            last_error = exc
            if attempt < max_retries:
                wait_time = 2 ** attempt
                time.sleep(wait_time)
            continue
        except Exception as exc:
            LOGGER.error("LLM call failed: %s", exc)
            last_error = exc
            if attempt < max_retries:
                wait_time = 2 ** attempt
                time.sleep(wait_time)
            continue
    
    if progress_callback:
        progress_callback("failed", f"All retries failed: {last_error}", None)
    return []


async def run_public_haiku_pipeline(
    slug: str,
    config: Dict[str, Any],
    progress_callback: ProgressCallback = None,
) -> Dict[str, Any]:
    """
    Run haiku generation for a public repo.
    
    Args:
        slug: Public repo slug (owner-repo)
        config: Configuration dict
        progress_callback: Optional callback for progress updates
        
    Returns:
        Dict with 'generated', 'failed', 'total' lists
    """
    import asyncio
    
    # Get repo config
    repo_config = get_public_repo(slug)
    if not repo_config:
        raise ValueError(f"Public repo not found: {slug}")
    
    # Get paths
    db_path = get_repo_db_path(slug)
    git_dir = get_repo_git_dir(slug)
    
    if not git_dir.exists():
        raise ValueError(f"Repo not cloned: {slug}. Run --add-public-repo first.")
    
    # Config
    haiku_config = config.get("haiku", {})
    max_per_run = haiku_config.get("max_per_run", 10)
    batch_size = haiku_config.get("batch_size", 3)
    provider = haiku_config.get("provider", "anthropic")
    model = haiku_config.get("model", "claude-haiku-4-5-20251001")
    depth = haiku_config.get("depth", "git_commit")
    max_retries = haiku_config.get("max_retries", 2)
    
    if progress_callback:
        progress_callback("starting", f"Initializing haiku pipeline for {slug}", None)
    
    LOGGER.info("Starting public haiku pipeline: repo=%s, max=%d", slug, max_per_run)
    
    # Build LLM client
    from codestory.pipeline.haiku import build_llm_client
    try:
        client = build_llm_client(provider, model)
    except Exception as exc:
        LOGGER.error("Cannot build LLM client: %s", exc)
        if progress_callback:
            progress_callback("error", f"Cannot build LLM client: {exc}", None)
        raise
    
    # Initialize DB for this repo
    db = DatabaseManager(str(db_path))
    processed_hashes = {h["commit_hash"] for h in db.get_all_haikus()}
    
    if progress_callback:
        progress_callback("git", "Reading git log", None)
    
    # Get commits from bare repo
    all_commits = read_git_log_from_bare(str(git_dir), limit=500)
    all_commits_reversed = list(reversed(all_commits))
    
    new_commits = [c for c in all_commits_reversed if c["hash"] not in processed_hashes]
    new_commits = new_commits[:max_per_run]
    
    if not new_commits:
        LOGGER.info("No new commits to process")
        if progress_callback:
            progress_callback("complete", "No new commits to process", 0)
        return {"generated": [], "failed": [], "total": 0}
    
    if progress_callback:
        progress_callback("commits", f"Found {len(new_commits)} new commits", len(new_commits))
    
    # Chronological index map
    chron_index_map = {c["hash"]: i + 1 for i, c in enumerate(all_commits_reversed)}
    
    # Load prompt
    from codestory.director.prompts import load_haiku_prompt
    system_prompt = load_haiku_prompt()
    
    results = []
    failed_commits = []
    
    total_batches = (len(new_commits) + batch_size - 1) // batch_size
    
    for batch_num, batch_start in enumerate(range(0, len(new_commits), batch_size)):
        batch = new_commits[batch_start:batch_start + batch_size]
        
        if progress_callback:
            progress_callback("batch", f"Processing batch {batch_num + 1}/{total_batches}", batch_num + 1)
        
        haiku_list = await generate_haiku_batch_public(
            client, model, batch, system_prompt, depth, str(git_dir),
            max_retries=max_retries,
            progress_callback=progress_callback,
        )
        
        haiku_map = {h.get("full_hash", ""): h for h in haiku_list}
        
        for commit in batch:
            commit_hash = commit["hash"]
            haiku = haiku_map.get(commit_hash)
            
            if haiku:
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
                    progress_callback("saved", f"✓ {commit_hash[:7]}: {haiku.get('title', '')[:40]}", commit_hash)
            else:
                failed_commits.append({
                    "hash": commit_hash,
                    "short_hash": commit_hash[:7],
                    "msg": commit.get("msg", ""),
                    "branch": commit.get("branch", "main"),
                })
                
                if progress_callback:
                    progress_callback("failed_commit", f"⚠ {commit_hash[:7]}: generation failed", commit_hash)
    
    LOGGER.info("Generated %d haikus, %d failed", len(results), len(failed_commits))
    
    if progress_callback:
        progress_callback("complete", f"Generated {len(results)} haikus, {len(failed_commits)} failed", len(results))
    
    return {
        "generated": results,
        "failed": failed_commits,
        "total": len(new_commits),
    }


def generate_public_haikus(
    slug: str,
    config: Optional[Dict[str, Any]] = None,
    progress_callback: ProgressCallback = None,
) -> List[Dict[str, Any]]:
    """
    Generate haikus for a public repo.
    
    Args:
        slug: Public repo slug (owner-repo)
        config: Optional config overrides
        progress_callback: Optional callback for progress
        
    Returns:
        List of generated haiku dicts
    """
    import asyncio
    
    cfg = load_config(overrides=config) if config else load_config()
    
    try:
        result = asyncio.run(run_public_haiku_pipeline(slug, cfg, progress_callback))
        return result.get("generated", [])
    except Exception as exc:
        LOGGER.error("Public haiku pipeline failed: %s", exc)
        raise
