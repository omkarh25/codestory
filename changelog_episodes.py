"""
changelog_episodes.py — The codeStory Episode Pipeline

Reads uncompiled haiku records from tmChron.db and generates episodic acts
when enough haikus are available (default: 10 per episode).

Depth modes (episode_depth, configurable via config.json):
  git_commit — LLM synthesises from haiku text only
  git_diff   — LLM also receives aggregated diffs for the episode's commits,
               for more code-specific episode summaries

Each episode follows the 4-section format defined in Director/EpisodeDirector.md:
  TITLE          ← Thematic crime of the decade
  DECADE SUMMARY ← 3-4 sentences pulling the emotional thread
  BRANCH NOTE    ← Branch name + noir criminal operation pun
  MAX'S RULING   ← One line. Cold. Final. Irreversible.

Usage (standalone):
    python changelog_episodes.py

Standard pipeline entry point:
    from changelog_episodes import fetch_actions
    results = fetch_actions(config={"episode_depth": "git_diff"})
"""

import asyncio
import json
import logging
import os
import re
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional

# ─── Path bootstrap ────────────────────────────────────────────────────────────
_REPO_ROOT = Path(__file__).resolve().parent

try:
    from dotenv import load_dotenv
    load_dotenv(dotenv_path=_REPO_ROOT / "llm.env")
except ImportError:
    pass

try:
    import anthropic
    ANTHROPIC_AVAILABLE = True
except ImportError:
    ANTHROPIC_AVAILABLE = False

LOGGER = logging.getLogger(__name__)

_EPISODE_DIRECTOR_PATH = _REPO_ROOT / "Director" / "EpisodeDirector.md"
_REPO_STORY_PATH       = _REPO_ROOT / "Director" / "RepoStory.md"

_FALLBACK_EPISODE_PROMPT = """You are MAX THE DESTROYER — the merciless, sardonic narrator of The codeStory Chronicles.
Synthesise 10 git commit haikus into one devastating EPISODE ACT.

Return ONLY a valid JSON object with keys: title, decade_summary, branch_note, max_ruling.
"""


# ─── Config ────────────────────────────────────────────────────────────────────

def load_config(overrides: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Load configuration from config.json, merged with optional overrides.

    Args:
        overrides: Key/value pairs to override config values.

    Returns:
        Merged configuration dict with sensible defaults.
    """
    defaults: Dict[str, Any] = {
        "repo_path": str(_REPO_ROOT),
        "max_haiku_per_run": 12,
        "batch_size": 3,
        "haiku_per_episode": 10,
        "db_path": str(_REPO_ROOT / "tmChron.db"),
        "output_dir": str(_REPO_ROOT / "Assets" / "haikuJSON"),
        "haiku_provider": "anthropic",
        "haiku_model": "claude-haiku-4-5-20251001",
        "haiku_depth": "git_commit",
        "episode_provider": "anthropic",
        "episode_model": "claude-haiku-4-5-20251001",
        "episode_depth": "git_commit",
        "oldest_first": True,
    }
    config_path = _REPO_ROOT / "config.json"
    try:
        with open(config_path, "r") as f:
            raw = json.load(f)
        cfg = raw.get("tmChronicles", {})
        for key in ("db_path", "output_dir", "repo_path"):
            if key in cfg and not Path(cfg[key]).is_absolute():
                cfg[key] = str(_REPO_ROOT / cfg[key])
        defaults.update(cfg)
        LOGGER.debug("Config loaded from %s", config_path)
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        LOGGER.warning("Could not load config.json (%s) — using defaults", exc)
    if overrides:
        defaults.update({k: v for k, v in overrides.items() if v is not None})
    return defaults


# ─── Director prompts ──────────────────────────────────────────────────────────

def load_episode_director_prompt() -> str:
    """Load MAX THE DESTROYER's episode brief from Director/EpisodeDirector.md.

    Injects Director/RepoStory.md as the baseline context preamble so MAX
    knows the codeStory origin story before rendering every episode verdict.

    Returns:
        Combined system prompt (RepoStory preface + EpisodeDirector brief).
        Falls back to hardcoded prompt if either file is missing.
    """
    # Load RepoStory baseline context
    repo_story = ""
    try:
        repo_story = _REPO_STORY_PATH.read_text(encoding="utf-8").strip()
        LOGGER.info("Loaded RepoStory baseline (%d chars)", len(repo_story))
    except (FileNotFoundError, OSError) as exc:
        LOGGER.warning("RepoStory.md not found (%s) — skipping baseline context", exc)

    # Load EpisodeDirector brief
    try:
        director = _EPISODE_DIRECTOR_PATH.read_text(encoding="utf-8").strip()
        LOGGER.info("Loaded episode director prompt (%d chars)", len(director))
    except (FileNotFoundError, OSError) as exc:
        LOGGER.warning("EpisodeDirector.md not found (%s) — using fallback prompt", exc)
        director = _FALLBACK_EPISODE_PROMPT

    if repo_story:
        return (
            "# BASELINE CONTEXT — THE ORIGIN STORY\n\n"
            + repo_story
            + "\n\n---\n\n"
            + director
        )
    return director


# ─── LLM client ────────────────────────────────────────────────────────────────

def build_llm_client(provider: str, model: str) -> "anthropic.AsyncAnthropic":
    """Build an Anthropic-compatible async LLM client.

    Args:
        provider: "anthropic" or "minimax"
        model:    Model identifier string

    Returns:
        Configured AsyncAnthropic client.

    Raises:
        ImportError:      anthropic SDK not installed
        ValueError:       Unsupported provider
        EnvironmentError: Required API key missing
    """
    if not ANTHROPIC_AVAILABLE:
        raise ImportError("anthropic SDK not installed. Run: pip install anthropic")
    LOGGER.info("Building LLM client — provider=%s model=%s", provider, model)
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
        raise ValueError(f"Unsupported provider: '{provider}'. Use 'anthropic' or 'minimax'.")


# ─── Database ──────────────────────────────────────────────────────────────────

def get_db_connection(db_path: str) -> sqlite3.Connection:
    """Open (and initialise) the tmChron.db SQLite database.

    Args:
        db_path: Path to the SQLite database file.

    Returns:
        Open sqlite3 connection with row_factory set to sqlite3.Row.
    """
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    _ensure_schema(conn)
    return conn


def _ensure_schema(conn: sqlite3.Connection) -> None:
    """Create tables if they don't already exist (idempotent).

    Args:
        conn: Open SQLite connection.
    """
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS haiku_commits (
            id                    INTEGER PRIMARY KEY AUTOINCREMENT,
            commit_hash           TEXT    UNIQUE NOT NULL,
            commit_type           TEXT,
            commit_msg            TEXT,
            branch                TEXT,
            author                TEXT,
            commit_date           TEXT,
            title                 TEXT,
            subtitle              TEXT,
            when_where            TEXT,
            who_whom              TEXT,
            what_why              TEXT,
            verdict               TEXT,
            compiled_into_episode INTEGER DEFAULT 0,
            created_at            TEXT    DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS chronicle_episodes (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            episode_number INTEGER UNIQUE,
            title          TEXT,
            decade_summary TEXT,
            branch_note    TEXT,
            max_ruling     TEXT,
            commit_hashes  TEXT,
            is_hearted     INTEGER DEFAULT 0,
            is_starred     INTEGER DEFAULT 0,
            is_saved       INTEGER DEFAULT 0,
            created_at     TEXT DEFAULT (datetime('now'))
        );
    """)
    conn.commit()


def get_uncompiled_haikus(conn: sqlite3.Connection, limit: int) -> List[sqlite3.Row]:
    """Fetch haiku rows not yet compiled into an episode (oldest first).

    Args:
        conn:  Open SQLite connection.
        limit: Maximum number of rows to return.

    Returns:
        List of sqlite3.Row objects ordered by commit_date ASC.
    """
    rows = conn.execute(
        """
        SELECT * FROM haiku_commits
        WHERE compiled_into_episode = 0
        ORDER BY commit_date ASC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    LOGGER.debug("Fetched %d uncompiled haiku rows", len(rows))
    return rows


def get_next_episode_number(conn: sqlite3.Connection) -> int:
    """Determine the next sequential episode number.

    Args:
        conn: Open SQLite connection.

    Returns:
        Integer episode number (1-based).
    """
    row = conn.execute(
        "SELECT COALESCE(MAX(episode_number), 0) AS max_ep FROM chronicle_episodes"
    ).fetchone()
    return (row["max_ep"] or 0) + 1


def save_episode(
    conn: sqlite3.Connection,
    episode_number: int,
    title: str,
    decade_summary: str,
    branch_note: str,
    max_ruling: str,
    commit_hashes: List[str],
) -> int:
    """Persist an episode to chronicle_episodes and mark haiku rows as compiled.

    Args:
        conn:           Open SQLite connection.
        episode_number: Sequential episode number.
        title:          Episode act title.
        decade_summary: 3-4 sentence essence.
        branch_note:    Branch + pun text.
        max_ruling:     Max's one-line verdict.
        commit_hashes:  List of commit hashes in this episode.

    Returns:
        Newly inserted episode row id.
    """
    cursor = conn.execute(
        """
        INSERT INTO chronicle_episodes
            (episode_number, title, decade_summary, branch_note, max_ruling, commit_hashes)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (episode_number, title, decade_summary, branch_note, max_ruling,
         json.dumps(commit_hashes)),
    )
    episode_id = cursor.lastrowid
    for h in commit_hashes:
        conn.execute(
            "UPDATE haiku_commits SET compiled_into_episode = ? WHERE commit_hash = ?",
            (episode_id, h),
        )
    conn.commit()
    LOGGER.info("Episode %d saved (id=%d) — %d commits", episode_number, episode_id, len(commit_hashes))
    return episode_id


# ─── Git diff aggregation (episode_depth=git_diff) ────────────────────────────

def _get_aggregated_diff_summary(repo_path: str, haiku_rows: List[sqlite3.Row]) -> str:
    """Get a condensed diff summary across all commits in an episode.

    Used for episode_depth=git_diff to give MAX THE DESTROYER richer context
    about what code actually changed across the episode's commits.

    Args:
        repo_path:  Path to the git repository root.
        haiku_rows: Haiku rows for the episode.

    Returns:
        Aggregated diff summary string (file names, function names, line counts).
    """
    import subprocess
    summaries = []
    for row in haiku_rows:
        commit_hash = row["commit_hash"]
        try:
            result = subprocess.run(
                ["git", "diff", f"{commit_hash}~1", commit_hash,
                 "--stat", "--no-color"],
                capture_output=True, text=True, cwd=repo_path,
            )
            if result.returncode == 0 and result.stdout.strip():
                summaries.append(f"[{commit_hash[:7]}] {row['commit_msg'] or ''}\n{result.stdout.strip()}")
        except Exception as exc:
            LOGGER.debug("Diff stat failed for %s: %s", commit_hash[:7], exc)
    return "\n\n".join(summaries[:10])  # cap at 10 to keep prompt sane


# ─── Episode generation ────────────────────────────────────────────────────────

async def generate_episode(
    client: "anthropic.AsyncAnthropic",
    model: str,
    episode_number: int,
    haiku_rows: List[sqlite3.Row],
    system_prompt: str,
    depth: str = "git_commit",
    repo_path: str = ".",
) -> Dict[str, str]:
    """Call the LLM to generate an episodic act from haiku rows.

    At git_commit depth: synthesises from haiku text only.
    At git_diff depth:   includes aggregated code change summaries.

    Args:
        client:         Configured AsyncAnthropic client.
        model:          Model identifier.
        episode_number: Episode sequence number.
        haiku_rows:     Haiku rows to synthesise into the episode.
        system_prompt:  Director brief (includes RepoStory.md baseline).
        depth:          "git_commit" or "git_diff"
        repo_path:      Repo path (for git_diff aggregation).

    Returns:
        Dict with keys: title, decade_summary, branch_note, max_ruling.
        Falls back to placeholder on LLM failure.
    """
    haiku_digest = []
    for row in haiku_rows:
        haiku_digest.append({
            "commit_hash": (row["commit_hash"] or "")[:7],
            "date": (row["commit_date"] or "")[:10],
            "type": row["commit_type"] or "other",
            "commit_msg": row["commit_msg"] or "",
            "branch": row["branch"] or "main",
            "title": row["title"] or "",
            "when_where": row["when_where"] or "",
            "who_whom":   row["who_whom"] or "",
            "what_why":   row["what_why"] or "",
            "verdict":    row["verdict"] or "",
        })

    branches = [r["branch"] for r in haiku_rows if r["branch"]]
    dominant_branch = max(set(branches), key=branches.count) if branches else "main"

    depth_section = ""
    if depth == "git_diff":
        diff_summary = _get_aggregated_diff_summary(repo_path, haiku_rows)
        if diff_summary:
            depth_section = (
                "\n\nCODE CHANGES SUMMARY (for richer episode context):\n"
                + diff_summary
            )

    user_prompt = (
        f"Generate EPISODE ACT {episode_number} of The codeStory Chronicles.\n\n"
        f"This episode covers {len(haiku_rows)} commits on branch '{dominant_branch}'.\n"
        f"Date range: {haiku_digest[0]['date']} → {haiku_digest[-1]['date']}.\n"
        f"Depth mode: {depth.upper()}\n"
        + depth_section
        + "\n\nHere are the 3-act haiku case files for each commit:\n\n"
        + json.dumps(haiku_digest, indent=2)
        + "\n\nSynthesise these into one EPISODE ACT. Return the JSON object as specified."
    )

    LOGGER.info("Generating episode %d — depth=%s model=%s", episode_number, depth, model)
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
            raise ValueError(f"No text block in LLM response — got: {[type(b).__name__ for b in response.content]}")

        raw = text_block.text.strip()
        raw = re.sub(r"^```[a-z]*\n?", "", raw)
        raw = re.sub(r"\n?```$", "", raw)

        episode_data = json.loads(raw)
        LOGGER.info("Episode %d generated successfully.", episode_number)
        return episode_data

    except json.JSONDecodeError as exc:
        LOGGER.error("Failed to parse episode JSON for episode %d: %s", episode_number, exc)
        return _fallback_episode(episode_number, dominant_branch)
    except Exception as exc:
        LOGGER.error("LLM call failed for episode %d: %s", episode_number, exc)
        return _fallback_episode(episode_number, dominant_branch)


def _fallback_episode(episode_number: int, branch: str) -> Dict[str, str]:
    """Return a minimal fallback episode when LLM generation fails.

    Args:
        episode_number: Episode number.
        branch:         Branch name.

    Returns:
        Episode dict with placeholder copy.
    """
    return {
        "title": f'EPISODE ACT {episode_number}: "THE UNWRITTEN CHAPTER"',
        "decade_summary": (
            "The investigation stalled. The evidence was there — 10 confessions in the ledger. "
            "But the narrator refused to speak. Or couldn't. The LLM had its own alibi."
        ),
        "branch_note": (
            f"Branch: `{branch}` — The operation continued in silence. "
            "Not every branch bears fruit. Some just grow in the dark."
        ),
        "max_ruling": "The system failed. The irony is: he built this too.",
    }


# ─── CRUD operations (delete, regenerate, validate) ────────────────────────

def delete_episode(conn: sqlite3.Connection, episode_number: int, output_dir: Path) -> bool:
    """Delete an episode and un-mark its haikus as compiled.

    Orphaned haikus can now be re-used in future episodes.

    Args:
        conn:            Open SQLite connection.
        episode_number:  Episode number to delete.
        output_dir:      Assets/haikuJSON directory.

    Returns:
        True on success, False if episode not found.
    """
    try:
        # Fetch episode to get its commit hashes
        row = conn.execute(
            "SELECT commit_hashes FROM chronicle_episodes WHERE episode_number = ?",
            (episode_number,),
        ).fetchone()
        if not row:
            LOGGER.warning("Episode not found: %d", episode_number)
            return False

        commit_hashes = json.loads(row["commit_hashes"])

        # Un-mark haikus as compiled
        for h in commit_hashes:
            conn.execute(
                "UPDATE haiku_commits SET compiled_into_episode = 0 WHERE commit_hash = ?",
                (h,),
            )

        # Delete episode from DB
        conn.execute("DELETE FROM chronicle_episodes WHERE episode_number = ?", (episode_number,))
        conn.commit()
        LOGGER.info("Deleted episode %d (un-marked %d haikus)", episode_number, len(commit_hashes))

        # Delete JSON file
        json_file = output_dir / f"episode_{episode_number:03d}.json"
        if json_file.exists():
            json_file.unlink()
            LOGGER.debug("Deleted JSON: %s", json_file.name)

        return True
    except sqlite3.Error as exc:
        LOGGER.error("DB error deleting episode: %s", exc)
        return False


def regenerate_episode(conn: sqlite3.Connection, episode_number: int, cfg: Dict[str, Any]) -> bool:
    """Delete an episode and regenerate it from fresh haikus.

    Useful for LLM retries or changing episode synthesis parameters.

    Args:
        conn:            Open SQLite connection.
        episode_number:  Episode number to regenerate.
        cfg:             Config dict with episode_provider, episode_model, etc.

    Returns:
        True on success, False on failure.
    """
    output_dir = Path(cfg.get("output_dir", str(_REPO_ROOT / "Assets" / "haikuJSON")))
    repo_path = cfg.get("repo_path", str(_REPO_ROOT))
    haiku_per_episode = int(cfg.get("haiku_per_episode", 10))

    # 1. Delete old episode (un-marks haikus)
    if not delete_episode(conn, episode_number, output_dir):
        return False

    # 2. Fetch fresh uncompiled haikus (oldest first)
    uncompiled = get_uncompiled_haikus(conn, limit=haiku_per_episode)
    available = len(uncompiled)

    if available < haiku_per_episode:
        LOGGER.warning(
            "Not enough haikus to regenerate episode %d: %d/%d available",
            episode_number, available, haiku_per_episode,
        )
        return False

    # 3. Generate fresh episode via LLM
    try:
        client = build_llm_client(cfg["episode_provider"], cfg["episode_model"])
        system_prompt = load_episode_director_prompt()
        depth = cfg.get("episode_depth", "git_commit")

        episode_data = asyncio.run(
            generate_episode(
                client, cfg["episode_model"], episode_number, uncompiled,
                system_prompt, depth, repo_path,
            )
        )

        if not episode_data:
            LOGGER.error("Failed to generate episode %d", episode_number)
            return False

        title = episode_data.get("title", f"EPISODE ACT {episode_number}: UNTITLED")
        decade_summary = episode_data.get("decade_summary", "")
        branch_note = episode_data.get("branch_note", "")
        max_ruling = episode_data.get("max_ruling", "")

        # 4. Save fresh episode (same episode_number to maintain sequential integrity)
        commit_hashes = [row["commit_hash"] for row in uncompiled]
        save_episode(conn, episode_number, title, decade_summary, branch_note, max_ruling, commit_hashes)

        # Re-write JSON
        write_episode_json(
            output_dir, episode_number, title, decade_summary,
            branch_note, max_ruling, commit_hashes,
        )

        LOGGER.info("Successfully regenerated episode %d", episode_number)
        return True

    except Exception as exc:
        LOGGER.error("Regenerate failed for episode %d: %s", episode_number, exc)
        return False


def validate_episode_consistency(db_path: str, json_dir: Path) -> Dict[str, List[str]]:
    """Check for orphaned/broken episodes and missing JSON files.

    Args:
        db_path:  Path to tmChron.db.
        json_dir: Path to Assets/haikuJSON.

    Returns:
        Dict with 'orphaned_json', 'broken_refs', 'missing_json' lists.
    """
    issues = {
        "orphaned_json": [],
        "broken_refs": [],
        "missing_json": [],
    }

    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row

        # Get all episodes from DB
        episodes = conn.execute("SELECT * FROM chronicle_episodes ORDER BY episode_number").fetchall()
        db_episode_numbers = {row["episode_number"] for row in episodes}

        # Get all haiku commit_hashes
        haiku_hashes = {row["commit_hash"] for row in conn.execute(
            "SELECT commit_hash FROM haiku_commits"
        ).fetchall()}

        # Check JSON files
        json_files = set(json_dir.glob("episode_*.json"))
        json_episode_numbers = {
            int(f.name.replace("episode_", "").replace(".json", ""))
            for f in json_files if f.name.startswith("episode_")
        }

        # Orphaned JSONs (no DB record)
        for ep_num in json_episode_numbers:
            if ep_num not in db_episode_numbers:
                issues["orphaned_json"].append(f"episode_{ep_num:03d}.json")

        # Missing JSONs (DB record but no file)
        for ep_num in db_episode_numbers:
            if ep_num not in json_episode_numbers:
                issues["missing_json"].append(f"episode_{ep_num:03d}")

        # Broken refs (episode references non-existent commit_hashes)
        for ep in episodes:
            commit_hashes = json.loads(ep["commit_hashes"] or "[]")
            for h in commit_hashes:
                if h not in haiku_hashes:
                    issues["broken_refs"].append(
                        f"Episode {ep['episode_number']}: commit {h[:7]} not in DB"
                    )

        conn.close()

        total = sum(len(v) for v in issues.values())
        LOGGER.info("Episode consistency check: %d issues found", total)
        return issues

    except Exception as exc:
        LOGGER.error("Episode consistency check failed: %s", exc)
        return issues


# ─── File output ──────────────────────────────────────────────────────────────

def write_episode_json(
    output_dir: Path,
    episode_number: int,
    title: str,
    decade_summary: str,
    branch_note: str,
    max_ruling: str,
    commit_hashes: List[str],
) -> Path:
    """Write an episode to a JSON file under Assets/haikuJSON/.

    Args:
        output_dir:     Target directory.
        episode_number: Sequential episode number.
        title:          Episode act title.
        decade_summary: 3-4 sentence essence.
        branch_note:    Branch + pun text.
        max_ruling:     Max's one-line verdict.
        commit_hashes:  Commit hashes in this episode.

    Returns:
        Path of the written JSON file.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    filename = output_dir / f"episode_{episode_number:03d}.json"
    data = {
        "episode_number": episode_number,
        "title": title,
        "decade_summary": decade_summary,
        "branch_note": branch_note,
        "max_ruling": max_ruling,
        "commit_hashes": commit_hashes,
    }
    filename.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    LOGGER.info("Episode JSON written: %s", filename)
    return filename


# ─── Core pipeline ─────────────────────────────────────────────────────────────

async def run_episode_pipeline(cfg: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Main async pipeline: check haiku count → generate episode → persist.

    Args:
        cfg: Full configuration dict from load_config().

    Returns:
        List of result dicts. Empty list if not enough haikus or on error.
    """
    db_path    = cfg["db_path"]
    output_dir = Path(cfg["output_dir"])
    haiku_per_episode: int = int(cfg["haiku_per_episode"])
    provider: str = cfg["episode_provider"]
    model: str    = cfg["episode_model"]
    depth: str    = cfg.get("episode_depth", "git_commit")
    repo_path: str = cfg.get("repo_path", str(_REPO_ROOT))

    LOGGER.info(
        "Starting episode pipeline — haiku_per_episode=%d provider=%s model=%s depth=%s",
        haiku_per_episode, provider, model, depth,
    )
    print(f"🎬 codeStory Episode Pipeline | depth={depth} | model={model}")
    print("=" * 60)

    # 1. Open DB
    conn = get_db_connection(db_path)

    # 2. Check uncompiled haiku count
    uncompiled = get_uncompiled_haikus(conn, limit=haiku_per_episode)
    available = len(uncompiled)

    if available < haiku_per_episode:
        msg = (
            f"[episode] Not enough haikus yet. "
            f"({available}/{haiku_per_episode} available). "
            f"Run --generate-haikus to add more."
        )
        print(msg)
        LOGGER.info(msg)
        conn.close()
        return []

    # 3. Build LLM client
    try:
        client = build_llm_client(provider, model)
    except (ImportError, EnvironmentError, ValueError) as exc:
        LOGGER.error("Cannot build LLM client: %s", exc)
        print(f"[episode] ERROR: {exc}")
        conn.close()
        return []

    # 4. Episode number
    episode_number = get_next_episode_number(conn)
    print(f"[episode] Generating EPISODE ACT {episode_number} from {haiku_per_episode} haikus...")

    # 5. Load director prompt (with RepoStory.md baseline)
    system_prompt = load_episode_director_prompt()

    # 6. Generate via LLM
    episode_data = await generate_episode(
        client, model, episode_number, uncompiled, system_prompt, depth, repo_path
    )

    title          = episode_data.get("title", f"EPISODE ACT {episode_number}: UNTITLED")
    decade_summary = episode_data.get("decade_summary", "")
    branch_note    = episode_data.get("branch_note", "")
    max_ruling     = episode_data.get("max_ruling", "")

    # 7. Persist to DB
    commit_hashes = [row["commit_hash"] for row in uncompiled]
    save_episode(conn, episode_number, title, decade_summary, branch_note, max_ruling, commit_hashes)

    # 8. Write JSON file
    json_path = write_episode_json(
        output_dir, episode_number, title, decade_summary,
        branch_note, max_ruling, commit_hashes,
    )

    conn.close()
    print(f"[episode] ✓ {title}")
    print(f"[episode] MAX'S RULING: {max_ruling}")
    print(f"[episode] Written to {json_path.name}")

    return [{
        "episode_number": episode_number,
        "title": title,
        "decade_summary": decade_summary,
        "branch_note": branch_note,
        "max_ruling": max_ruling,
        "commit_hashes": commit_hashes,
    }]


# ─── Public API ───────────────────────────────────────────────────────────────

def fetch_actions(config: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    """Standard pipeline entry point — generates one episode per invocation.

    Args:
        config: Optional overrides (haiku_per_episode, episode_provider,
                episode_model, episode_depth, db_path, output_dir).

    Returns:
        List of episode result dicts. Empty if not enough haikus.
    """
    cfg = load_config(config)
    try:
        # Try to get existing event loop, create new one if not available
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            # No event loop exists for this thread - create a new one
            loop = asyncio.new_event_loop()
        
        if loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                future = pool.submit(asyncio.run, run_episode_pipeline(cfg))
                return future.result()
        else:
            return asyncio.run(run_episode_pipeline(cfg))
    except Exception as exc:
        LOGGER.error("Episode pipeline fatal error: %s", exc)
        print(f"[episode] FATAL: {exc}")
        return []


# ─── CLI ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )

    parser = argparse.ArgumentParser(
        description="codeStory Episode Pipeline — synthesise haikus into episode acts",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
examples:
  python changelog_episodes.py                  # generate next episode
  python changelog_episodes.py --delete 1      # delete episode 1 (un-marks haikus)
  python changelog_episodes.py --regenerate 1  # delete + re-synthesize episode 1
  python changelog_episodes.py --validate      # check DB ↔ JSON episode consistency
        """,
    )
    parser.add_argument("--depth", choices=["git_commit", "git_diff"], default=None,
                        help="Analysis depth (default: config.json episode_depth)")
    parser.add_argument("--model", default=None, help="Override LLM model")
    parser.add_argument("--delete", type=int, metavar="N", default=None,
                        help="Delete episode N (un-marks its haikus)")
    parser.add_argument("--regenerate", type=int, metavar="N", default=None,
                        help="Delete + re-synthesize episode N")
    parser.add_argument("--validate", action="store_true",
                        help="Check episode DB ↔ JSON consistency")
    args = parser.parse_args()

    cfg = load_config({
        "episode_depth": args.depth,
        "episode_model": args.model,
    })

    # ── Delete ──────────────────────────────────────────────────────────────────
    if args.delete:
        db_path = cfg["db_path"]
        output_dir = Path(cfg["output_dir"])
        try:
            conn = get_db_connection(db_path)
            if delete_episode(conn, args.delete, output_dir):
                print(f"✓ Deleted episode {args.delete} (un-marked its haikus)")
            else:
                print(f"✗ Episode not found: {args.delete}")
            conn.close()
        except Exception as exc:
            print(f"ERROR: {exc}")
        import sys
        sys.exit(0)

    # ── Regenerate ──────────────────────────────────────────────────────────────
    if args.regenerate:
        db_path = cfg["db_path"]
        try:
            conn = get_db_connection(db_path)
            if regenerate_episode(conn, args.regenerate, cfg):
                print(f"✓ Regenerated episode {args.regenerate}")
            else:
                print(f"✗ Regeneration failed: episode {args.regenerate}")
            conn.close()
        except Exception as exc:
            print(f"ERROR: {exc}")
        import sys
        sys.exit(0)

    # ── Validate ────────────────────────────────────────────────────────────────
    if args.validate:
        db_path = cfg["db_path"]
        json_dir = Path(cfg["output_dir"])
        issues = validate_episode_consistency(db_path, json_dir)
        total = sum(len(v) for v in issues.values())
        if total == 0:
            print("✓ Episode consistency check: All good — no issues found.")
        else:
            print(f"⚠ {total} consistency issue(s) found:\n")
            if issues["orphaned_json"]:
                print(f"Orphaned JSON files (no DB record):\n  " + "\n  ".join(issues["orphaned_json"]))
            if issues["missing_json"]:
                print(f"Missing JSON files (DB record but no file):\n  " + "\n  ".join(issues["missing_json"]))
            if issues["broken_refs"]:
                print(f"Broken references (commits missing from DB):\n  " + "\n  ".join(issues["broken_refs"]))
        import sys
        sys.exit(0)

    # ── Standard generation ─────────────────────────────────────────────────────
    overrides = {
        "episode_depth": args.depth,
        "episode_model": args.model,
    }

    items = fetch_actions(config={k: v for k, v in overrides.items() if v is not None})
    if items:
        ep = items[0]
        print(f"\n─── {ep['title']} ───")
        print(f"\n{ep['decade_summary']}")
        print(f"\nBRANCH: {ep['branch_note']}")
        print(f"\nMAX'S RULING: {ep['max_ruling']}")
    else:
        print("\nNo episode generated — check haiku count.")
