"""
Database management for codeStory.

Provides SQLite database operations with:
- Full CRUD for haikus and episodes
- Asset tracking (JSON files, MP4 videos)
- Auto-sync between DB and filesystem
- Validation and repair utilities
"""

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from codestory.core.logging import get_logger
from codestory.core.types import (
    EpisodeAssetDict,
    EpisodeDict,
    HaikuAssetDict,
    HaikuDict,
)

LOGGER = get_logger(__name__)


class DatabaseManager:
    """
    Manages SQLite database for codeStory with asset tracking.

    Handles:
    - Haiku CRUD operations
    - Episode CRUD operations
    - Asset tracking (JSON + video files)
    - Auto-sync between DB and filesystem
    """

    def __init__(self, db_path: str, assets_dir: Optional[Path] = None):
        """
        Initialize database manager.

        Args:
            db_path: Path to SQLite database file.
            assets_dir: Base directory for assets (default: derived from db_path).
        """
        self._db_path = Path(db_path)
        self._assets_dir = assets_dir or self._db_path.parent / "assets"
        self._haikus_dir = self._assets_dir / "haikus"
        self._episodes_dir = self._assets_dir / "episodes"
        self._videos_dir = self._assets_dir / "videos"

        # Ensure directories exist
        self._haikus_dir.mkdir(parents=True, exist_ok=True)
        self._episodes_dir.mkdir(parents=True, exist_ok=True)
        self._videos_dir.mkdir(parents=True, exist_ok=True)

        # Initialize database
        self._init_schema()

    def _get_connection(self) -> sqlite3.Connection:
        """Get a database connection with row_factory set."""
        conn = sqlite3.connect(str(self._db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def _init_schema(self) -> None:
        """Create database tables if they don't exist."""
        conn = self._get_connection()
        try:
            conn.executescript("""
                -- Haiku content table
                CREATE TABLE IF NOT EXISTS haiku_commits (
                    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
                    commit_hash           TEXT UNIQUE NOT NULL,
                    short_hash            TEXT NOT NULL,
                    commit_type           TEXT,
                    commit_msg            TEXT,
                    branch                TEXT,
                    author                TEXT,
                    commit_date           TEXT,
                    chronological_index   INTEGER DEFAULT 0,
                    title                 TEXT,
                    subtitle              TEXT,
                    act1_title            TEXT,
                    when_where            TEXT,
                    act2_title            TEXT,
                    who_whom              TEXT,
                    act3_title            TEXT,
                    what_why              TEXT,
                    verdict               TEXT,
                    is_hearted            INTEGER DEFAULT 0,
                    is_starred            INTEGER DEFAULT 0,
                    is_saved              INTEGER DEFAULT 0,
                    compiled_into_episode INTEGER DEFAULT 0,
                    created_at            TEXT DEFAULT (datetime('now'))
                );

                -- Episode content table
                CREATE TABLE IF NOT EXISTS chronicle_episodes (
                    id             INTEGER PRIMARY KEY AUTOINCREMENT,
                    episode_number INTEGER UNIQUE NOT NULL,
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

                -- Haiku asset tracking
                CREATE TABLE IF NOT EXISTS haiku_assets (
                    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                    commit_hash         TEXT UNIQUE NOT NULL,
                    short_hash          TEXT NOT NULL,
                    chronological_index INTEGER NOT NULL,
                    branch              TEXT NOT NULL,
                    json_path           TEXT NOT NULL,
                    video_path          TEXT,
                    synced_at           TEXT,
                    created_at          TEXT DEFAULT (datetime('now'))
                );

                -- Episode asset tracking
                CREATE TABLE IF NOT EXISTS episode_assets (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    episode_number  INTEGER UNIQUE NOT NULL,
                    json_path       TEXT NOT NULL,
                    video_path      TEXT,
                    synced_at       TEXT,
                    created_at      TEXT DEFAULT (datetime('now'))
                );

                -- Now moments table: one row per --now invocation
                CREATE TABLE IF NOT EXISTS now_moments (
                    id                INTEGER PRIMARY KEY AUTOINCREMENT,
                    captured_at       TEXT NOT NULL,
                    title             TEXT,
                    subtitle          TEXT,
                    act1_title        TEXT,
                    when_where        TEXT,
                    act2_title        TEXT,
                    who_whom          TEXT,
                    act3_title        TEXT,
                    what_why          TEXT,
                    verdict           TEXT,
                    todo_snapshot     TEXT,
                    diff_snapshot     TEXT,
                    commits_snapshot  TEXT,
                    is_hearted        INTEGER DEFAULT 0,
                    is_starred        INTEGER DEFAULT 0,
                    is_saved          INTEGER DEFAULT 0,
                    created_at        TEXT DEFAULT (datetime('now'))
                );

                -- Indexes for performance
                CREATE INDEX IF NOT EXISTS idx_haiku_chron ON haiku_commits(chronological_index);
                CREATE INDEX IF NOT EXISTS idx_haiku_asset_hash ON haiku_assets(commit_hash);
                CREATE INDEX IF NOT EXISTS idx_episode_num ON chronicle_episodes(episode_number);
                CREATE INDEX IF NOT EXISTS idx_episode_asset_num ON episode_assets(episode_number);
                CREATE INDEX IF NOT EXISTS idx_moment_captured ON now_moments(captured_at);
            """)
            conn.commit()
            LOGGER.debug("Database schema initialized")
        finally:
            conn.close()

    # ==================== HAIKU OPERATIONS ====================

    def get_all_haikus(self) -> List[HaikuDict]:
        """Get all haikus ordered chronologically."""
        conn = self._get_connection()
        try:
            rows = conn.execute("""
                SELECT * FROM haiku_commits
                ORDER BY CASE WHEN chronological_index > 0
                         THEN chronological_index ELSE id END ASC
            """).fetchall()
            return [dict(row) for row in rows]
        finally:
            conn.close()

    def get_haiku_by_hash(self, commit_hash: str) -> Optional[HaikuDict]:
        """Get a haiku by full or partial commit hash."""
        conn = self._get_connection()
        try:
            row = conn.execute(
                "SELECT * FROM haiku_commits WHERE commit_hash LIKE ?",
                (f"{commit_hash}%",),
            ).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def get_uncompiled_haikus(self, limit: int = 10) -> List[HaikuDict]:
        """Get haikus not yet compiled into episodes."""
        conn = self._get_connection()
        try:
            rows = conn.execute("""
                SELECT * FROM haiku_commits
                WHERE compiled_into_episode = 0
                ORDER BY chronological_index ASC
                LIMIT ?
            """, (limit,)).fetchall()
            return [dict(row) for row in rows]
        finally:
            conn.close()

    def save_haiku(
        self,
        commit: Dict[str, str],
        haiku_data: Dict[str, Any],
        chronological_index: int = 0,
    ) -> Tuple[HaikuDict, HaikuAssetDict]:
        """
        Save a haiku to DB and write JSON file.

        Args:
            commit: Commit metadata dict.
            haiku_data: Haiku content dict from LLM.
            chronological_index: Position in repo history.

        Returns:
            Tuple of (haiku_dict, asset_dict).
        """
        commit_hash = commit["hash"]
        short_hash = commit_hash[-4:]  # Last 4 characters
        branch = (commit.get("branch") or "main").replace("/", "-")

        # Generate JSON filename
        json_filename = f"haiku_{chronological_index:03d}_{branch}_{short_hash}.json"
        json_path = self._haikus_dir / json_filename

        # Write JSON file
        json_data = {
            "commit_hash": commit_hash,
            "short_hash": short_hash,
            "commit_type": commit.get("type", "other"),
            "commit_msg": commit.get("msg", ""),
            "branch": commit.get("branch", "main"),
            "author": commit.get("author", ""),
            "date": commit.get("date", ""),
            "chronological_index": chronological_index,
            "title": haiku_data.get("title", ""),
            "subtitle": haiku_data.get("subtitle", ""),
            "act1_title": haiku_data.get("act1_title", ""),
            "when_where": haiku_data.get("when_where", ""),
            "act2_title": haiku_data.get("act2_title", ""),
            "who_whom": haiku_data.get("who_whom", ""),
            "act3_title": haiku_data.get("act3_title", ""),
            "what_why": haiku_data.get("what_why", ""),
            "verdict": haiku_data.get("verdict", ""),
        }
        json_path.write_text(json.dumps(json_data, indent=2, ensure_ascii=False))
        LOGGER.debug("Wrote haiku JSON: %s", json_path)

        # Insert into DB
        conn = self._get_connection()
        try:
            cursor = conn.execute("""
                INSERT OR REPLACE INTO haiku_commits
                (commit_hash, short_hash, commit_type, commit_msg, branch, author,
                 commit_date, chronological_index, title, subtitle, act1_title,
                 when_where, act2_title, who_whom, act3_title, what_why, verdict)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                commit_hash, short_hash, commit.get("type", "other"),
                commit.get("msg", ""), commit.get("branch", "main"),
                commit.get("author", ""), commit.get("date", ""),
                chronological_index, haiku_data.get("title", ""),
                haiku_data.get("subtitle", ""), haiku_data.get("act1_title", ""),
                haiku_data.get("when_where", ""), haiku_data.get("act2_title", ""),
                haiku_data.get("who_whom", ""), haiku_data.get("act3_title", ""),
                haiku_data.get("what_why", ""), haiku_data.get("verdict", ""),
            ))

            # Track asset
            synced_at = datetime.now().isoformat()
            conn.execute("""
                INSERT OR REPLACE INTO haiku_assets
                (commit_hash, short_hash, chronological_index, branch, json_path, synced_at)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (commit_hash, short_hash, chronological_index, branch, str(json_path), synced_at))

            conn.commit()

            haiku_dict = {"id": cursor.lastrowid, **json_data}
            asset_dict = {
                "commit_hash": commit_hash,
                "short_hash": short_hash,
                "chronological_index": chronological_index,
                "branch": branch,
                "json_path": str(json_path),
                "video_path": None,
                "synced_at": synced_at,
            }
            return haiku_dict, asset_dict
        finally:
            conn.close()

    def delete_haiku(self, commit_hash: str) -> bool:
        """
        Delete a haiku from DB and remove JSON file.

        Args:
            commit_hash: Full or partial commit hash.

        Returns:
            True if deleted, False if not found.
        """
        # Get asset info first
        conn = self._get_connection()
        try:
            asset = conn.execute(
                "SELECT * FROM haiku_assets WHERE commit_hash LIKE ?",
                (f"{commit_hash}%",),
            ).fetchone()

            if not asset:
                LOGGER.warning("Haiku asset not found: %s", commit_hash)
                return False

            # Delete JSON file
            json_path = Path(asset["json_path"])
            if json_path.exists():
                json_path.unlink()
                LOGGER.debug("Deleted haiku JSON: %s", json_path)

            # Delete video if exists
            if asset["video_path"]:
                video_path = Path(asset["video_path"])
                if video_path.exists():
                    video_path.unlink()
                    LOGGER.debug("Deleted haiku video: %s", video_path)

            # Delete from DB
            conn.execute("DELETE FROM haiku_assets WHERE commit_hash = ?", (asset["commit_hash"],))
            conn.execute("DELETE FROM haiku_commits WHERE commit_hash = ?", (asset["commit_hash"],))
            conn.commit()

            LOGGER.info("Deleted haiku: %s", commit_hash)
            return True
        finally:
            conn.close()

    def get_haiku_count(self) -> int:
        """Get total haiku count."""
        conn = self._get_connection()
        try:
            row = conn.execute("SELECT COUNT(*) FROM haiku_commits").fetchone()
            return row[0] if row else 0
        finally:
            conn.close()

    def get_pending_haiku_count(self) -> int:
        """Get count of haikus not compiled into episodes."""
        conn = self._get_connection()
        try:
            row = conn.execute(
                "SELECT COUNT(*) FROM haiku_commits WHERE compiled_into_episode = 0"
            ).fetchone()
            return row[0] if row else 0
        finally:
            conn.close()

    # ==================== EPISODE OPERATIONS ====================

    def get_all_episodes(self) -> List[EpisodeDict]:
        """Get all episodes ordered by episode number."""
        conn = self._get_connection()
        try:
            rows = conn.execute(
                "SELECT * FROM chronicle_episodes ORDER BY episode_number ASC"
            ).fetchall()
            return [dict(row) for row in rows]
        finally:
            conn.close()

    def get_episode_by_number(self, episode_number: int) -> Optional[EpisodeDict]:
        """Get an episode by number."""
        conn = self._get_connection()
        try:
            row = conn.execute(
                "SELECT * FROM chronicle_episodes WHERE episode_number = ?",
                (episode_number,),
            ).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def get_next_episode_number(self) -> int:
        """Get the next available episode number."""
        conn = self._get_connection()
        try:
            row = conn.execute(
                "SELECT COALESCE(MAX(episode_number), 0) FROM chronicle_episodes"
            ).fetchone()
            return (row[0] or 0) + 1
        finally:
            conn.close()

    def save_episode(
        self,
        episode_number: int,
        episode_data: Dict[str, Any],
        commit_hashes: List[str],
    ) -> Tuple[EpisodeDict, EpisodeAssetDict]:
        """
        Save an episode to DB and write JSON file.

        Args:
            episode_number: Episode sequence number.
            episode_data: Episode content from LLM.
            commit_hashes: List of commit hashes in this episode.

        Returns:
            Tuple of (episode_dict, asset_dict).
        """
        # Generate JSON filename
        json_filename = f"episode_{episode_number:03d}.json"
        json_path = self._episodes_dir / json_filename

        # Write JSON file
        json_data = {
            "episode_number": episode_number,
            "title": episode_data.get("title", ""),
            "decade_summary": episode_data.get("decade_summary", ""),
            "branch_note": episode_data.get("branch_note", ""),
            "max_ruling": episode_data.get("max_ruling", ""),
            "commit_hashes": commit_hashes,
        }
        json_path.write_text(json.dumps(json_data, indent=2, ensure_ascii=False))
        LOGGER.debug("Wrote episode JSON: %s", json_path)

        # Insert into DB
        conn = self._get_connection()
        try:
            cursor = conn.execute("""
                INSERT OR REPLACE INTO chronicle_episodes
                (episode_number, title, decade_summary, branch_note, max_ruling, commit_hashes)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                episode_number,
                episode_data.get("title", ""),
                episode_data.get("decade_summary", ""),
                episode_data.get("branch_note", ""),
                episode_data.get("max_ruling", ""),
                json.dumps(commit_hashes),
            ))

            # Mark haikus as compiled
            for h in commit_hashes:
                conn.execute(
                    "UPDATE haiku_commits SET compiled_into_episode = ? WHERE commit_hash = ?",
                    (episode_number, h),
                )

            # Track asset
            synced_at = datetime.now().isoformat()
            conn.execute("""
                INSERT OR REPLACE INTO episode_assets
                (episode_number, json_path, synced_at)
                VALUES (?, ?, ?)
            """, (episode_number, str(json_path), synced_at))

            conn.commit()

            episode_dict = dict(cursor.lastrowid, **json_data)
            asset_dict = {
                "episode_number": episode_number,
                "json_path": str(json_path),
                "video_path": None,
                "synced_at": synced_at,
            }
            return episode_dict, asset_dict
        finally:
            conn.close()

    def delete_episode(self, episode_number: int) -> bool:
        """
        Delete an episode from DB and remove JSON file.

        Args:
            episode_number: Episode number to delete.

        Returns:
            True if deleted, False if not found.
        """
        conn = self._get_connection()
        try:
            # Get asset info
            asset = conn.execute(
                "SELECT * FROM episode_assets WHERE episode_number = ?",
                (episode_number,),
            ).fetchone()

            if not asset:
                LOGGER.warning("Episode asset not found: %d", episode_number)
                return False

            # Delete JSON file
            json_path = Path(asset["json_path"])
            if json_path.exists():
                json_path.unlink()
                LOGGER.debug("Deleted episode JSON: %s", json_path)

            # Delete video if exists
            if asset["video_path"]:
                video_path = Path(asset["video_path"])
                if video_path.exists():
                    video_path.unlink()
                    LOGGER.debug("Deleted episode video: %s", video_path)

            # Get commit hashes to unmark
            episode = conn.execute(
                "SELECT commit_hashes FROM chronicle_episodes WHERE episode_number = ?",
                (episode_number,),
            ).fetchone()

            if episode and episode["commit_hashes"]:
                commit_hashes = json.loads(episode["commit_hashes"])
                for h in commit_hashes:
                    conn.execute(
                        "UPDATE haiku_commits SET compiled_into_episode = 0 WHERE commit_hash = ?",
                        (h,),
                    )

            # Delete from DB
            conn.execute("DELETE FROM episode_assets WHERE episode_number = ?", (episode_number,))
            conn.execute("DELETE FROM chronicle_episodes WHERE episode_number = ?", (episode_number,))
            conn.commit()

            LOGGER.info("Deleted episode: %d", episode_number)
            return True
        finally:
            conn.close()

    def get_episode_count(self) -> int:
        """Get total episode count."""
        conn = self._get_connection()
        try:
            row = conn.execute("SELECT COUNT(*) FROM chronicle_episodes").fetchone()
            return row[0] if row else 0
        finally:
            conn.close()

    # ==================== NOW MOMENTS OPERATIONS ====================

    def save_moment(
        self,
        haiku_data: Dict[str, Any],
        captured_at: str,
        todo_snapshot: str = "",
        diff_snapshot: str = "",
        commits_snapshot: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """
        Save a Now moment to the now_moments table.

        Args:
            haiku_data: Haiku fields from LLM (title, subtitle, acts, verdict).
            captured_at: ISO timestamp when --now was invoked.
            todo_snapshot: Raw TODO text used as context.
            diff_snapshot: Raw git diff used as context.
            commits_snapshot: List of recent commit dicts used as context.

        Returns:
            Full moment dict with id and all fields.
        """
        commits_json = json.dumps(commits_snapshot or [], ensure_ascii=False)

        conn = self._get_connection()
        try:
            cursor = conn.execute("""
                INSERT INTO now_moments
                (captured_at, title, subtitle, act1_title, when_where,
                 act2_title, who_whom, act3_title, what_why, verdict,
                 todo_snapshot, diff_snapshot, commits_snapshot)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                captured_at,
                haiku_data.get("title", ""),
                haiku_data.get("subtitle", ""),
                haiku_data.get("act1_title", ""),
                haiku_data.get("when_where", ""),
                haiku_data.get("act2_title", ""),
                haiku_data.get("who_whom", ""),
                haiku_data.get("act3_title", ""),
                haiku_data.get("what_why", ""),
                haiku_data.get("verdict", ""),
                todo_snapshot,
                diff_snapshot,
                commits_json,
            ))
            conn.commit()

            moment_id = cursor.lastrowid
            LOGGER.info("Saved Now moment id=%d: %s", moment_id, haiku_data.get("title", "?"))

            return {
                "id":               moment_id,
                "captured_at":      captured_at,
                "title":            haiku_data.get("title", ""),
                "subtitle":         haiku_data.get("subtitle", ""),
                "act1_title":       haiku_data.get("act1_title", ""),
                "when_where":       haiku_data.get("when_where", ""),
                "act2_title":       haiku_data.get("act2_title", ""),
                "who_whom":         haiku_data.get("who_whom", ""),
                "act3_title":       haiku_data.get("act3_title", ""),
                "what_why":         haiku_data.get("what_why", ""),
                "verdict":          haiku_data.get("verdict", ""),
                "todo_snapshot":    todo_snapshot,
                "diff_snapshot":    diff_snapshot,
                "commits_snapshot": commits_json,
                "is_hearted":       0,
                "is_starred":       0,
                "is_saved":         0,
            }
        finally:
            conn.close()

    def get_all_moments(self) -> List[Dict[str, Any]]:
        """
        Get all Now moments ordered by capture time (oldest first).

        Returns:
            List of moment dicts.
        """
        conn = self._get_connection()
        try:
            rows = conn.execute(
                "SELECT * FROM now_moments ORDER BY captured_at ASC"
            ).fetchall()
            return [dict(row) for row in rows]
        finally:
            conn.close()

    def get_moment_by_id(self, moment_id: int) -> Optional[Dict[str, Any]]:
        """
        Get a single Now moment by ID.

        Args:
            moment_id: Primary key of the moment.

        Returns:
            Moment dict, or None if not found.
        """
        conn = self._get_connection()
        try:
            row = conn.execute(
                "SELECT * FROM now_moments WHERE id = ?", (moment_id,)
            ).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def get_moment_count(self) -> int:
        """Get total count of saved Now moments."""
        conn = self._get_connection()
        try:
            row = conn.execute("SELECT COUNT(*) FROM now_moments").fetchone()
            return row[0] if row else 0
        finally:
            conn.close()

    def toggle_moment_flag(self, moment_id: int, flag: str) -> int:
        """
        Toggle a flag on a Now moment.

        Args:
            moment_id: Primary key of the moment.
            flag: One of 'is_hearted', 'is_starred', 'is_saved'.

        Returns:
            New flag value (0 or 1), or -1 on error.
        """
        if flag not in ("is_hearted", "is_starred", "is_saved"):
            return -1

        conn = self._get_connection()
        try:
            row = conn.execute(
                f"SELECT {flag} FROM now_moments WHERE id = ?", (moment_id,)
            ).fetchone()

            if not row:
                return -1

            new_val = 0 if row[0] else 1
            conn.execute(
                f"UPDATE now_moments SET {flag} = ? WHERE id = ?",
                (new_val, moment_id),
            )
            conn.commit()
            LOGGER.info("Toggled %s for moment id=%d: %d", flag, moment_id, new_val)
            return new_val
        finally:
            conn.close()

    # ==================== FLAG OPERATIONS ====================

    def toggle_haiku_flag(self, commit_hash: str, flag: str) -> int:
        """Toggle a flag on a haiku."""
        if flag not in ("is_hearted", "is_starred", "is_saved"):
            return -1

        conn = self._get_connection()
        try:
            row = conn.execute(
                f"SELECT {flag} FROM haiku_commits WHERE commit_hash LIKE ?",
                (f"{commit_hash}%",),
            ).fetchone()

            if not row:
                return -1

            new_val = 0 if row[0] else 1
            conn.execute(
                f"UPDATE haiku_commits SET {flag} = ? WHERE commit_hash LIKE ?",
                (new_val, f"{commit_hash}%"),
            )
            conn.commit()
            LOGGER.info("Toggled %s for haiku %s: %d", flag, commit_hash[:7], new_val)
            return new_val
        finally:
            conn.close()

    def toggle_episode_flag(self, episode_number: int, flag: str) -> int:
        """Toggle a flag on an episode."""
        if flag not in ("is_hearted", "is_starred", "is_saved"):
            return -1

        conn = self._get_connection()
        try:
            row = conn.execute(
                f"SELECT {flag} FROM chronicle_episodes WHERE episode_number = ?",
                (episode_number,),
            ).fetchone()

            if not row:
                return -1

            new_val = 0 if row[0] else 1
            conn.execute(
                f"UPDATE chronicle_episodes SET {flag} = ? WHERE episode_number = ?",
                (new_val, episode_number),
            )
            conn.commit()
            LOGGER.info("Toggled %s for episode %d: %d", flag, episode_number, new_val)
            return new_val
        finally:
            conn.close()

    # ==================== SYNC & VALIDATION ====================

    def validate_sync(self) -> Dict[str, List[str]]:
        """
        Validate synchronization between DB and filesystem.

        Returns:
            Dict with 'orphaned_files', 'missing_files', 'broken_refs' lists.
        """
        issues: Dict[str, List[str]] = {
            "orphaned_json": [],
            "missing_json": [],
            "orphaned_video": [],
            "missing_video": [],
        }

        conn = self._get_connection()
        try:
            # Check haiku assets
            haiku_assets = conn.execute("SELECT * FROM haiku_assets").fetchall()
            for asset in haiku_assets:
                # Check JSON
                json_path = Path(asset["json_path"])
                if not json_path.exists():
                    issues["missing_json"].append(str(json_path))

                # Check video if tracked
                if asset["video_path"]:
                    video_path = Path(asset["video_path"])
                    if not video_path.exists():
                        issues["missing_video"].append(str(video_path))

            # Check orphaned JSON files in haikus directory
            db_hashes = {a["commit_hash"] for a in haiku_assets}
            for json_file in self._haikus_dir.glob("haiku_*.json"):
                file_hash = json_file.stem.split("_")[-1]  # Extract hash from filename
                if not any(file_hash in h for h in db_hashes):
                    issues["orphaned_json"].append(str(json_file))

            # Check episode assets
            episode_assets = conn.execute("SELECT * FROM episode_assets").fetchall()
            for asset in episode_assets:
                # Check JSON
                json_path = Path(asset["json_path"])
                if not json_path.exists():
                    issues["missing_json"].append(str(json_path))

                # Check video if tracked
                if asset["video_path"]:
                    video_path = Path(asset["video_path"])
                    if not video_path.exists():
                        issues["missing_video"].append(str(video_path))

            # Check orphaned episode JSONs
            db_episodes = {a["episode_number"] for a in episode_assets}
            for json_file in self._episodes_dir.glob("episode_*.json"):
                ep_num = int(json_file.stem.split("_")[-1])
                if ep_num not in db_episodes:
                    issues["orphaned_json"].append(str(json_file))

            total = sum(len(v) for v in issues.values())
            LOGGER.info("Sync validation: %d issues found", total)
            return issues
        finally:
            conn.close()

    def sync_from_filesystem(self) -> Dict[str, int]:
        """
        Sync database from existing filesystem (for migration).

        Returns:
            Dict with counts of synced items.
        """
        counts = {"haikus": 0, "episodes": 0}

        conn = self._get_connection()
        try:
            # Scan haiku JSONs
            for json_file in self._haikus_dir.glob("haiku_*.json"):
                try:
                    data = json.loads(json_file.read_text())
                    commit_hash = data.get("commit_hash", "")
                    short_hash = data.get("short_hash", commit_hash[-4:])
                    chron_idx = data.get("chronological_index", 0)
                    branch = data.get("branch", "main").replace("/", "-")

                    # Insert if not exists
                    conn.execute("""
                        INSERT OR IGNORE INTO haiku_commits
                        (commit_hash, short_hash, commit_type, commit_msg, branch, author,
                         commit_date, chronological_index, title, subtitle, act1_title,
                         when_where, act2_title, who_whom, act3_title, what_why, verdict)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        commit_hash, short_hash, data.get("commit_type", "other"),
                        data.get("commit_msg", ""), data.get("branch", "main"),
                        data.get("author", ""), data.get("date", ""),
                        chron_idx, data.get("title", ""), data.get("subtitle", ""),
                        data.get("act1_title", ""), data.get("when_where", ""),
                        data.get("act2_title", ""), data.get("who_whom", ""),
                        data.get("act3_title", ""), data.get("what_why", ""),
                        data.get("verdict", ""),
                    ))

                    # Add asset tracking
                    conn.execute("""
                        INSERT OR IGNORE INTO haiku_assets
                        (commit_hash, short_hash, chronological_index, branch, json_path, synced_at)
                        VALUES (?, ?, ?, ?, ?, ?)
                    """, (commit_hash, short_hash, chron_idx, branch, str(json_file),
                          datetime.now().isoformat()))

                    counts["haikos"] += 1
                except Exception as e:
                    LOGGER.warning("Failed to sync haiku %s: %s", json_file, e)

            # Scan episode JSONs
            for json_file in self._episodes_dir.glob("episode_*.json"):
                try:
                    data = json.loads(json_file.read_text())
                    ep_num = data.get("episode_number", 0)
                    commit_hashes = data.get("commit_hashes", [])

                    conn.execute("""
                        INSERT OR IGNORE INTO chronicle_episodes
                        (episode_number, title, decade_summary, branch_note, max_ruling, commit_hashes)
                        VALUES (?, ?, ?, ?, ?, ?)
                    """, (
                        ep_num, data.get("title", ""), data.get("decade_summary", ""),
                        data.get("branch_note", ""), data.get("max_ruling", ""),
                        json.dumps(commit_hashes),
                    ))

                    conn.execute("""
                        INSERT OR IGNORE INTO episode_assets
                        (episode_number, json_path, synced_at)
                        VALUES (?, ?, ?)
                    """, (ep_num, str(json_file), datetime.now().isoformat()))

                    counts["episodes"] += 1
                except Exception as e:
                    LOGGER.warning("Failed to sync episode %s: %s", json_file, e)

            conn.commit()
            LOGGER.info("Synced from filesystem: %s", counts)
            return counts
        finally:
            conn.close()
