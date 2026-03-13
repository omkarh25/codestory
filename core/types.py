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


class CommitDict(TypedDict, total=False):
    """Git commit metadata."""
    hash: str
    type: str
    msg: str
    branch: str
    author: str
    date: str
