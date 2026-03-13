"""
Director's Cut casefile markdown writer for codeStory.

Generates cinematic `casefile_XXX_branch_hash.md` companion documents
alongside each MP4 render.  These are structured for human reading
AND for downstream processing (Remotion, static sites, etc.).
"""

from pathlib import Path
from typing import Any, Dict

from codestory.core.logging import get_logger
from codestory.pipeline.git import GIT_CRIME_LEXICON

LOGGER = get_logger(__name__)


def write_cinematic_casefile(
    output_dir: Path,
    commit: Dict[str, Any],
    haiku: Dict[str, Any],
    chronological_index: int,
) -> Path:
    """
    Write a Director's Cut casefile markdown for a single commit haiku.

    The output file is named `casefile_NNN_branch_hash.md` and placed in
    `output_dir`.  The layout mirrors the cinematic MP4 slides:
      - Full-bleed title + tagline
      - Metadata strip (date, branch, type, author)
      - ACT I / II / III (each with its noir title from the LLM)
      - VERDICT block

    Args:
        output_dir:          Directory to write the .md file into.
        commit:              Commit metadata dict (hash, msg, branch, author, date, type).
        haiku:               Haiku content dict from DB or LLM response.
        chronological_index: Chronological position in repo history.

    Returns:
        Path to the written .md file.
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Normalise keys — DB rows use "commit_hash"/"commit_msg", pipeline uses "hash"/"msg"
    commit_hash = commit.get("hash") or commit.get("commit_hash", "unknown")
    short_hash = commit_hash[:7]
    commit_msg = commit.get("msg") or commit.get("commit_msg", "")
    branch = commit.get("branch", "main")
    branch_safe = branch.replace("/", "-")
    author = commit.get("author", "Unknown")
    date_raw = commit.get("date") or commit.get("commit_date", "")
    date_str = date_raw[:10] if date_raw else "unknown"
    commit_type = commit.get("type") or commit.get("commit_type", "other")
    narrative_role = GIT_CRIME_LEXICON.get(commit_type, "Unknown crime")

    filename = output_dir / f"casefile_{chronological_index:03d}_{branch_safe}_{short_hash}.md"

    # Act labels — prefer LLM-generated noir titles, fall back to roman numerals
    act1_label = (haiku.get("act1_title") or "THE SITUATION").upper()
    act2_label = (haiku.get("act2_title") or "THE PLAYERS").upper()
    act3_label = (haiku.get("act3_title") or "THE CONSEQUENCE").upper()

    title = haiku.get("title", f"CASE FILE — #{chronological_index:03d}")
    subtitle = haiku.get("subtitle", "")
    when_where = haiku.get("when_where", "")
    who_whom = haiku.get("who_whom", "")
    what_why = haiku.get("what_why", "")
    verdict = haiku.get("verdict", "")

    content = f"""\
# {title}

*{subtitle}*

---

| Field      | Value |
|------------|-------|
| **Date**   | `{date_str}` |
| **Commit** | `{commit_msg}` |
| **Branch** | `{branch}` |
| **Type**   | `{commit_type.upper()}` — *{narrative_role}* |
| **Author** | {author} |
| **Hash**   | `{short_hash}` |
| **#**      | {chronological_index:03d} |

---

### ACT I — {act1_label}

{when_where}

### ACT II — {act2_label}

{who_whom}

### ACT III — {act3_label}

{what_why}

---

### VERDICT

> {verdict}

---

*codeStory — Director's Cut · Case #{chronological_index:03d}*
"""

    filename.write_text(content, encoding="utf-8")
    LOGGER.info("Wrote Director's Cut casefile: %s", filename.name)
    return filename
