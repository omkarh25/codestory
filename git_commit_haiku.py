"""
git_commit_haiku.py — The codeStory Haiku Pipeline

Reads git commits from a target repo, generates cinematic 3-act noir haikus
(plus title, subtitle, and verdict) via Anthropic or MiniMax, and persists
them to tmChron.db.

Depth modes (configurable via config.json):
  git_commit — LLM receives only the commit message
  git_diff   — LLM receives the full git diff (function names, class names,
               changed lines) for maximum dramatic specificity

DB schema stores: title, subtitle, when_where, who_whom, what_why, verdict
so the PyQt viewer can render the full 3-act + verdict experience.

Usage (standalone):
    python git_commit_haiku.py
    python git_commit_haiku.py --depth git_diff --max 5

Standard pipeline entry point:
    from git_commit_haiku import fetch_actions
    results = fetch_actions(config={"haiku_depth": "git_diff"})
"""

import asyncio
import json
import logging
import os
import re
import sqlite3
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

# ─── Path bootstrap ────────────────────────────────────────────────────────────
_REPO_ROOT = Path(__file__).resolve().parent

try:
    from dotenv import load_dotenv
    load_dotenv(dotenv_path=_REPO_ROOT / "llm.env")
except ImportError:
    pass  # dotenv optional — env vars may already be set

try:
    import anthropic
    ANTHROPIC_AVAILABLE = True
except ImportError:
    ANTHROPIC_AVAILABLE = False

LOGGER = logging.getLogger(__name__)

# ─── Git Crime Lexicon ─────────────────────────────────────────────────────────
GIT_CRIME_LEXICON: Dict[str, str] = {
    "feat":     "Rising action — He acquired a new weapon",
    "fix":      "Damage control — The alibi was falling apart",
    "chore":    "The grind montage — Three days. No sleep. Just code.",
    "refactor": "Identity crisis — He tore it all down and rebuilt himself",
    "docs":     "The confession — He documented the crime in detail",
    "test":     "Paranoia — He didn't trust himself. He built a lie detector.",
    "revert":   "The flashback — He undid it. But you can't unring a bell.",
    "merge":    "The conspiracy deepens — Two worlds collided. Nothing was the same.",
    "style":    "Vanity — He polished the evidence",
    "ci":       "The system closing in — Automated judgment approached",
    "build":    "The forge — Infrastructure hammered into shape",
    "perf":     "The chase — He made it faster to avoid himself",
    "hotfix":   "2 AM damage control — Emergency. No witnesses.",
    "init":     "The origin — The first sin. Before the evidence, there was the idea.",
    "wip":      "The unfinished crime — Left at the scene, half-done",
}

COMMIT_TYPE_TO_CATEGORY: Dict[str, str] = {
    "feat": "Productive", "fix": "Necessity", "chore": "Necessity",
    "refactor": "Learning", "docs": "Learning", "test": "Productive",
    "revert": "Other", "merge": "Productive", "style": "Other",
    "ci": "Necessity", "build": "Necessity", "perf": "Productive",
    "hotfix": "Necessity", "init": "Productive", "wip": "Other",
}

_HAIKU_DIRECTOR_PATH = _REPO_ROOT / "Director" / "HaikuDirector.md"

# Fallback prompt (used only if HaikuDirector.md is missing)
_FALLBACK_HAIKU_PROMPT = """You are MAX THE DESTROYER — the merciless, sardonic narrator of The codeStory Chronicles.
Turn git commits into 3-act noir case files. Short. Visceral. Cinematic.

Return ONLY a valid JSON array with one object per commit containing:
  full_hash, title, subtitle, when_where, who_whom, what_why, verdict
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
        # Resolve relative paths to absolute (relative to repo root)
        for key in ("db_path", "output_dir", "repo_path"):
            if key in cfg and not Path(cfg[key]).is_absolute():
                cfg[key] = str(_REPO_ROOT / cfg[key])
        defaults.update(cfg)
        LOGGER.debug("Config loaded from %s: %s", config_path, defaults)
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        LOGGER.warning("Could not load config.json (%s) — using defaults", exc)
    if overrides:
        defaults.update({k: v for k, v in overrides.items() if v is not None})
    return defaults


# ─── Director prompt ───────────────────────────────────────────────────────────

def load_haiku_director_prompt() -> str:
    """Load MAX THE DESTROYER's haiku brief from Director/HaikuDirector.md.

    Returns:
        System prompt string. Falls back to hardcoded prompt if file missing.
    """
    try:
        prompt = _HAIKU_DIRECTOR_PATH.read_text(encoding="utf-8").strip()
        LOGGER.info("Loaded haiku director prompt (%d chars)", len(prompt))
        return prompt
    except (FileNotFoundError, OSError) as exc:
        LOGGER.warning("HaikuDirector.md not found (%s) — using fallback prompt", exc)
        return _FALLBACK_HAIKU_PROMPT


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
        raise ValueError(f"Unsupported LLM provider: '{provider}'. Use 'anthropic' or 'minimax'.")


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
    _init_schema(conn)
    return conn


def _init_schema(conn: sqlite3.Connection) -> None:
    """Create tmChron.db tables if they don't exist (idempotent).

    Schema includes:
    - title, subtitle: case file header
    - act1_title, act2_title, act3_title: dramatic act titles shown via typewriter
      (e.g. "ACT I: The Dystopian Mind") — generated by LLM to be apt for each act's content
    - when_where, who_whom, what_why: act body text
    - verdict: final one-line judgment

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
            act1_title            TEXT,
            when_where            TEXT,
            act2_title            TEXT,
            who_whom              TEXT,
            act3_title            TEXT,
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
            created_at     TEXT DEFAULT (datetime('now'))
        );
    """)
    conn.commit()
    LOGGER.debug("tmChron.db schema verified/initialised.")


def get_processed_hashes(conn: sqlite3.Connection) -> set:
    """Return all commit hashes already in haiku_commits.

    Args:
        conn: Open SQLite connection.

    Returns:
        Set of full commit hash strings.
    """
    rows = conn.execute("SELECT commit_hash FROM haiku_commits").fetchall()
    return {row["commit_hash"] for row in rows}


def save_haiku(
    conn: sqlite3.Connection,
    commit: Dict[str, str],
    title: str,
    subtitle: str,
    act1_title: str,
    when_where: str,
    act2_title: str,
    who_whom: str,
    act3_title: str,
    what_why: str,
    verdict: str,
) -> None:
    """Persist a haiku record to haiku_commits.

    Args:
        conn:       Open SQLite connection.
        commit:     Dict with keys: hash, type, msg, branch, author, date.
        title:      Case file title.
        subtitle:   One-line tagline.
        act1_title: Dramatic title for Act I (e.g. "The Dystopian Mind").
        when_where: Act 1 — setting body text.
        act2_title: Dramatic title for Act II.
        who_whom:   Act 2 — players and tension body text.
        act3_title: Dramatic title for Act III.
        what_why:   Act 3 — action and consequence body text.
        verdict:    Final one-line judgment.
    """
    conn.execute(
        """
        INSERT OR IGNORE INTO haiku_commits
            (commit_hash, commit_type, commit_msg, branch, author, commit_date,
             title, subtitle, act1_title, when_where, act2_title, who_whom,
             act3_title, what_why, verdict)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            commit["hash"], commit["type"], commit["msg"],
            commit["branch"], commit["author"], commit["date"],
            title, subtitle, act1_title, when_where, act2_title,
            who_whom, act3_title, what_why, verdict,
        ),
    )
    conn.commit()
    LOGGER.info("Saved haiku for commit %s (%s)", commit["hash"][:7], commit["msg"][:40])


# ─── Git log parser ────────────────────────────────────────────────────────────

def parse_commit_type(subject: str) -> str:
    """Extract conventional-commit type prefix from subject line.

    Args:
        subject: Full commit subject (e.g. "feat: Add personas").

    Returns:
        Lowercase commit type or "other" if not recognised.
    """
    match = re.match(r"^([a-zA-Z]+)[\(!:]", subject.strip())
    if match:
        return match.group(1).lower()
    return "other"


def read_git_log(repo_path: str, limit: int = 500) -> List[Dict[str, str]]:
    """Run git log and parse commits into structured dicts.

    Args:
        repo_path: Absolute path to the git repository root.
        limit:     Maximum number of commits to retrieve.

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
    """Extract branch name from git log refs string.

    Args:
        refs: Git refs string (e.g. "HEAD -> main, origin/main").

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


def get_git_diff(repo_path: str, commit_hash: str, max_lines: int = 150) -> str:
    """Get the git diff for a single commit (parent vs commit).

    Used for git_diff depth mode — gives MAX THE DESTROYER actual code context:
    function names, class names, changed lines.

    Args:
        repo_path:   Absolute path to the git repository root.
        commit_hash: Full commit hash.
        max_lines:   Maximum diff lines to include (keeps prompt size reasonable).

    Returns:
        Diff string. Empty string on error or first commit (no parent).
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
            lines = lines[:max_lines] + [f"\n... ({len(lines) - max_lines} more lines truncated)"]
        return "\n".join(lines)
    except subprocess.CalledProcessError as exc:
        LOGGER.warning("git diff failed for %s: %s", commit_hash[:7], exc.stderr)
        return ""


# ─── Haiku generation ─────────────────────────────────────────────────────────

async def generate_haiku_batch(
    client: "anthropic.AsyncAnthropic",
    model: str,
    batch: List[Dict[str, str]],
    system_prompt: str,
    depth: str = "git_commit",
    repo_path: str = ".",
) -> List[Dict[str, str]]:
    """Call LLM to generate haikus for a batch of commits.

    At git_commit depth: sends commit message only.
    At git_diff depth:   sends full diff (function names, class names, lines).

    Args:
        client:       Configured AsyncAnthropic client.
        model:        Model identifier.
        batch:        List of commit dicts.
        system_prompt: Director brief.
        depth:        "git_commit" or "git_diff"
        repo_path:    Repo path (needed for git_diff).

    Returns:
        List of haiku dicts with keys: full_hash, title, subtitle,
        when_where, who_whom, what_why, verdict.
        Empty list on failure.
    """
    commits_payload = []
    for c in batch:
        role = GIT_CRIME_LEXICON.get(c["type"], f"Unknown crime — {c['type']}")
        entry: Dict[str, Any] = {
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
                LOGGER.debug("Added diff for %s (%d chars)", c["hash"][:7], len(diff))
        commits_payload.append(entry)

    depth_note = (
        "You have been given the full git diff for each commit. "
        "Use the actual function names, class names, and changed lines in your haikus. "
        "Be specific. Name the functions. Name the classes. This is an autopsy, not a metaphor."
        if depth == "git_diff"
        else "You have been given only the commit message. Infer. Imagine. Be devastating."
    )

    user_prompt = (
        f"Generate a 3-act noir case file for each of the following {len(batch)} git commits.\n\n"
        f"DEPTH: {depth.upper()} — {depth_note}\n\n"
        f"Return a JSON array with exactly {len(batch)} objects in the same order.\n"
        "Each object MUST have exactly these keys:\n"
        '  "full_hash"  : the full commit hash (copy from input)\n'
        '  "title"      : "CASE FILE — <short punchy label>" (do NOT include hash in title)\n'
        '  "subtitle"   : one-line movie-poster tagline for this commit\n'
        '  "act1_title" : 2-5 word dramatic noir title for Act I — must be SPECIFIC to this act\'s setting/time content (e.g. "The Midnight Confession", "A Room Without Windows")\n'
        '  "when_where" : Act 1 — setting, time, branch, vibe (1-3 sentences)\n'
        '  "act2_title" : 2-5 word dramatic noir title for Act II — specific to the players/stakes (e.g. "The Wrong Hands", "Two Suspects, One Motive")\n'
        '  "who_whom"   : Act 2 — who acted on whom, stakes, tension (1-3 sentences)\n'
        '  "act3_title" : 2-5 word dramatic noir title for Act III — specific to the action/consequence (e.g. "Point of No Return", "The Unrung Bell")\n'
        '  "what_why"   : Act 3 — action taken, consequence, confession (2-4 sentences)\n'
        '  "verdict"    : one cold, final, irreversible line judging the man not the code\n\n'
        "IMPORTANT: act1_title, act2_title, act3_title must be SHORT (2-5 words), dramatically evocative, "
        "and SPECIFIC to that act's actual content — NOT generic labels like 'The Setting' or 'The Players'.\n\n"
        "Commits:\n"
        + json.dumps(commits_payload, indent=2)
    )

    LOGGER.info("Sending haiku batch of %d commits (depth=%s) to model=%s", len(batch), depth, model)
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
            raise ValueError(f"No text block in LLM response — got: {[type(b).__name__ for b in response.content]}")

        raw = text_block.text.strip()
        # Strip markdown fences if model wrapped the JSON
        raw = re.sub(r"^```[a-z]*\n?", "", raw)
        raw = re.sub(r"\n?```$", "", raw)

        haiku_list = json.loads(raw)
        LOGGER.info("Received %d haikus from LLM", len(haiku_list))
        return haiku_list

    except json.JSONDecodeError as exc:
        LOGGER.error("Failed to parse haiku JSON response: %s", exc)
        return []
    except Exception as exc:
        LOGGER.error("LLM call failed for haiku batch: %s", exc)
        return []


# ─── Output ────────────────────────────────────────────────────────────────────

def write_haiku_json(output_dir: Path, commit: Dict[str, str], haiku: Dict[str, str]) -> Path:
    """Write a haiku to a JSON file under Assets/haikuJSON/.

    Args:
        output_dir: Directory to write into.
        commit:     Commit metadata dict.
        haiku:      Haiku fields dict from LLM.

    Returns:
        Path of the written JSON file.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    short_hash = commit["hash"][:7]
    branch_safe = (commit.get("branch") or "main").replace("/", "-")
    filename = output_dir / f"haiku_{branch_safe}_{short_hash}.json"
    data = {
        "commit_hash": commit["hash"],
        "commit_type": commit["type"],
        "commit_msg": commit["msg"],
        "branch": commit["branch"],
        "author": commit["author"],
        "date": commit["date"],
        "title": haiku.get("title", ""),
        "subtitle": haiku.get("subtitle", ""),
        "act1_title": haiku.get("act1_title", ""),
        "when_where": haiku.get("when_where", ""),
        "act2_title": haiku.get("act2_title", ""),
        "who_whom": haiku.get("who_whom", ""),
        "act3_title": haiku.get("act3_title", ""),
        "what_why": haiku.get("what_why", ""),
        "verdict": haiku.get("verdict", ""),
    }
    filename.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    LOGGER.debug("Haiku JSON written: %s", filename)
    return filename


# ─── Core pipeline ─────────────────────────────────────────────────────────────

async def run_haiku_pipeline(cfg: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Main async pipeline: fetch commits → generate haikus → persist.

    Args:
        cfg: Full configuration dict from load_config().

    Returns:
        List of result dicts summarising generated haikus.
    """
    db_path    = cfg["db_path"]
    output_dir = Path(cfg["output_dir"])
    max_per_run: int = int(cfg["max_haiku_per_run"])
    batch_size: int  = int(cfg["batch_size"])
    provider: str    = cfg["haiku_provider"]
    model: str       = cfg["haiku_model"]
    depth: str       = cfg.get("haiku_depth", "git_commit")
    repo_path: str   = cfg.get("repo_path", str(_REPO_ROOT))
    oldest_first: bool = bool(cfg.get("oldest_first", True))

    LOGGER.info(
        "Starting haiku pipeline — max=%d batch=%d provider=%s model=%s depth=%s",
        max_per_run, batch_size, provider, model, depth,
    )
    print(f"🎬 codeStory Haiku Pipeline | depth={depth} | model={model}")
    print("=" * 60)

    # 1. Build LLM client
    try:
        client = build_llm_client(provider, model)
    except (ImportError, EnvironmentError, ValueError) as exc:
        LOGGER.error("Cannot build LLM client: %s", exc)
        print(f"[haiku] ERROR: {exc}")
        return []

    # 2. Open DB
    conn = get_db_connection(db_path)
    processed = get_processed_hashes(conn)
    LOGGER.info("Already processed: %d commits", len(processed))

    # 3. Fetch git log
    all_commits = read_git_log(repo_path, limit=500)
    if oldest_first:
        all_commits = list(reversed(all_commits))
        LOGGER.info("oldest_first=True — processing from oldest commit")

    new_commits = [c for c in all_commits if c["hash"] not in processed]
    new_commits = new_commits[:max_per_run]

    if not new_commits:
        print("[haiku] No new commits to process.")
        conn.close()
        return []

    print(f"[haiku] {len(new_commits)} new commits to process (batches of {batch_size})...")

    # 4. Load director prompt
    system_prompt = load_haiku_director_prompt()

    # 5. Batch processing
    results: List[Dict[str, Any]] = []

    for batch_start in range(0, len(new_commits), batch_size):
        batch = new_commits[batch_start: batch_start + batch_size]
        batch_num = (batch_start // batch_size) + 1
        hashes = [c["hash"][:7] for c in batch]
        print(f"  → Batch {batch_num}: {hashes}")

        haiku_list = await generate_haiku_batch(
            client, model, batch, system_prompt, depth, repo_path
        )
        haiku_map = {h.get("full_hash", ""): h for h in haiku_list}

        for commit in batch:
            haiku = haiku_map.get(commit["hash"])
            if not haiku:
                LOGGER.warning("No haiku returned for commit %s", commit["hash"][:7])
                continue

            title      = haiku.get("title", f"CASE FILE — {commit['hash'][:7]}")
            subtitle   = haiku.get("subtitle", "")
            act1_title = haiku.get("act1_title", "I")
            when_where = haiku.get("when_where", "")
            act2_title = haiku.get("act2_title", "II")
            who_whom   = haiku.get("who_whom", "")
            act3_title = haiku.get("act3_title", "III")
            what_why   = haiku.get("what_why", "")
            verdict    = haiku.get("verdict", "")

            # Persist to DB
            save_haiku(
                conn, commit, title, subtitle,
                act1_title, when_where,
                act2_title, who_whom,
                act3_title, what_why,
                verdict,
            )

            # Write JSON file
            write_haiku_json(output_dir, commit, haiku)

            category = COMMIT_TYPE_TO_CATEGORY.get(commit["type"], "Other")
            results.append({
                "hash": commit["hash"],
                "title": title,
                "subtitle": subtitle,
                "act1_title": act1_title,
                "when_where": when_where,
                "act2_title": act2_title,
                "who_whom": who_whom,
                "act3_title": act3_title,
                "what_why": what_why,
                "verdict": verdict,
                "commit_msg": commit["msg"],
                "branch": commit["branch"],
                "date": commit["date"],
                "category": category,
            })
            print(f"     ✓ {title}")

    conn.close()
    print(f"\n[haiku] ✓ Generated {len(results)} haikus.")
    return results


# ─── Public API ───────────────────────────────────────────────────────────────

def fetch_actions(config: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    """Standard pipeline entry point.

    Loads config.json, merges optional overrides, runs the async haiku
    generation pipeline, and returns results.

    Args:
        config: Optional overrides (repo_path, max_haiku_per_run, haiku_depth, etc.)

    Returns:
        List of haiku result dicts. Empty list if no new commits or on error.
    """
    cfg = load_config(config)
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                future = pool.submit(asyncio.run, run_haiku_pipeline(cfg))
                return future.result()
        else:
            return asyncio.run(run_haiku_pipeline(cfg))
    except Exception as exc:
        LOGGER.error("Haiku pipeline fatal error: %s", exc)
        print(f"[haiku] FATAL: {exc}")
        return []


# ─── CLI ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )

    parser = argparse.ArgumentParser(
        description="codeStory Haiku Pipeline — generate noir haikus from git commits"
    )
    parser.add_argument("--repo",  default=None, help="Path to git repo (default: config.json)")
    parser.add_argument("--depth", choices=["git_commit", "git_diff"], default=None,
                        help="Analysis depth (default: config.json haiku_depth)")
    parser.add_argument("--max",   type=int, default=None,
                        help="Max haikus to generate per run (default: config.json)")
    parser.add_argument("--model", default=None, help="Override LLM model")
    args = parser.parse_args()

    overrides = {
        "repo_path":       args.repo,
        "haiku_depth":     args.depth,
        "max_haiku_per_run": args.max,
        "haiku_model":     args.model,
    }

    items = fetch_actions(config={k: v for k, v in overrides.items() if v is not None})
    print(f"\nTotal haikus generated: {len(items)}")
    for item in items[:2]:
        print(f"\n─── {item['title']} ───")
        print(f"  {item['subtitle']}")
        print(f"\n  ACT I — WHEN/WHERE\n  {item['when_where']}")
        print(f"\n  ACT II — WHO/WHOM\n  {item['who_whom']}")
        print(f"\n  ACT III — WHAT/WHY\n  {item['what_why']}")
        print(f"\n  VERDICT: {item['verdict']}")
