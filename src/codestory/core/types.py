"""
Shared data types across codeStory modules.

Provides common type definitions to reduce coupling between modules
and improve testability (Dependency Inversion Principle).
"""

from typing import TypedDict, Optional, List


class HaikuDict(TypedDict, total=False):
    """Haiku record from database or LLM output."""
    id: int
    commit_hash: str
    short_hash: str
    commit_type: str
    commit_msg: str
    branch: str
    author: str
    commit_date: str
    chronological_index: int
    title: str
    subtitle: str
    act1_title: str
    when_where: str
    act2_title: str
    who_whom: str
    act3_title: str
    what_why: str
    verdict: str
    is_hearted: int
    is_starred: int
    is_saved: int
    compiled_into_episode: int
    created_at: str


class EpisodeDict(TypedDict, total=False):
    """Episode record from database or LLM output."""
    id: int
    episode_number: int
    title: str
    decade_summary: str
    branch_note: str
    max_ruling: str
    commit_hashes: List[str]
    is_hearted: int
    is_starred: int
    is_saved: int
    created_at: str


class CommitDict(TypedDict, total=False):
    """Git commit metadata."""
    hash: str
    type: str
    msg: str
    branch: str
    author: str
    date: str


class HaikuAssetDict(TypedDict, total=False):
    """Haiku asset tracking in database."""
    id: int
    commit_hash: str
    short_hash: str
    chronological_index: int
    branch: str
    json_path: str
    video_path: Optional[str]
    synced_at: Optional[str]
    created_at: str


class EpisodeAssetDict(TypedDict, total=False):
    """Episode asset tracking in database."""
    id: int
    episode_number: int
    json_path: str
    video_path: Optional[str]
    synced_at: Optional[str]
    created_at: str


class ConfigDict(TypedDict, total=False):
    """Configuration dictionary."""
    repo_path: str
    db_path: str
    output_dir: str
    haiku: dict
    episode: dict
    yt_shorts: dict
