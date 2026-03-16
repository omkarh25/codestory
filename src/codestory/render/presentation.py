"""Shared presentation view-model builders for case-file renderers.

This module provides a single formatting contract so multiple viewers
(PyQt and HTMX) render the same canonical header and act metadata.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict

from codestory.core.logging import get_logger

LOGGER = get_logger(__name__)


GIT_CRIME_LEXICON_DISPLAY: Dict[str, str] = {
    "feat": "Rising action — He acquired a new weapon",
    "fix": "Damage control — The alibi was falling apart",
    "chore": "The grind montage — Three days. No sleep. Just code.",
    "refactor": "Identity crisis — He tore it all down and rebuilt himself",
    "docs": "The confession — He documented the crime in detail",
    "test": "Paranoia — He built a lie detector",
    "revert": "The flashback — He undid it. But you can't unring a bell.",
    "merge": "The conspiracy deepens — Two worlds collided.",
    "style": "Vanity — He polished the evidence",
    "ci": "The system closing in — Automated judgment approached",
    "build": "The forge — Infrastructure hammered into shape",
    "perf": "The chase — He made it faster to avoid himself",
    "hotfix": "2 AM damage control — Emergency. No witnesses.",
    "init": "The origin — The first sin.",
    "wip": "The unfinished crime — Left at the scene, half-done",
    "now": "The still point — Full presence. Nothing outside this moment.",
    "present": "Active awareness — The work window is open. Not past. Not future.",
    "eternal": "The long operation — Building something that outlasts the branch.",
    "infinite": "Deep recursion — No exit planned. No exit needed.",
    "absolute": "Final distillation — Nothing left to remove. The work is complete.",
}


def _get_time_period(hour: int) -> str:
    """Return noir-style time period text from hour."""
    if 5 <= hour < 8:
        return "Before Dawn"
    if 8 <= hour < 12:
        return "Morning Light"
    if 12 <= hour < 14:
        return "High Noon"
    if 14 <= hour < 17:
        return "Afternoon Shadows"
    if 17 <= hour < 20:
        return "Evening Gathers"
    if 20 <= hour < 22:
        return "Night Falls"
    if 22 <= hour < 24:
        return "Late Night"
    return "Witching Hour"


def format_case_datetime(iso_date: str) -> str:
    """Format ISO date string to the shared viewer display format."""
    if not iso_date:
        return ""
    try:
        dt = datetime.fromisoformat(
            iso_date.replace(" +0530", "+05:30").replace(" +0000", "+00:00")
        )
        return (
            dt.strftime("%d %b %Y %a ")
            + f"{_get_time_period(dt.hour)} "
            + dt.strftime("%I:%M %p").lower()
        )
    except Exception:
        try:
            dt = datetime.strptime(iso_date[:10], "%Y-%m-%d")
            return dt.strftime("%d %b %Y %a")
        except Exception:
            LOGGER.debug("Could not parse commit date '%s', using fallback", iso_date)
            return iso_date[:10]


def build_case_file_presentation(
    haiku: Dict[str, Any],
    index: int,
    total: int,
) -> Dict[str, Any]:
    """Build canonical case-file presentation data from a haiku row."""
    commit_hash = haiku.get("commit_hash") or haiku.get("hash", "?")
    short_hash = (commit_hash or "?")[:7]
    branch = haiku.get("branch", "main") or "main"
    commit_type = (haiku.get("commit_type") or "other").lower()
    raw_date = haiku.get("commit_date") or haiku.get("date", "")
    formatted_date = format_case_datetime(raw_date)
    commit_msg = haiku.get("commit_msg") or haiku.get("commit_message", "")
    author = haiku.get("author", "Unknown")
    chron_idx = haiku.get("chronological_index") or index

    crime_text = GIT_CRIME_LEXICON_DISPLAY.get(commit_type, commit_type.upper())

    return {
        "case_number": chron_idx,
        "case_index": index,
        "total_cases": total,
        "commit_hash": commit_hash,
        "short_hash": short_hash,
        "branch": branch,
        "commit_type": commit_type,
        "commit_type_label": commit_type.upper(),
        "crime_text": crime_text,
        "raw_date": raw_date,
        "formatted_date": formatted_date,
        "commit_msg": commit_msg,
        "author": author,
        "title": haiku.get("title", f"CASE FILE — {short_hash}"),
        "subtitle": haiku.get("subtitle", ""),
        "act1_title": haiku.get("act1_title", ""),
        "when_where": haiku.get("when_where", ""),
        "act2_title": haiku.get("act2_title", ""),
        "who_whom": haiku.get("who_whom", ""),
        "act3_title": haiku.get("act3_title", ""),
        "what_why": haiku.get("what_why", ""),
        "verdict": haiku.get("verdict", ""),
    }
