"""
Storyboard JSON generator for codeStory Director's Cut pipeline.

A storyboard is the central multistage processing config that drives the
video render pipeline.  It defines every shot, its duration, and the
audio configuration — acting as the contract between LLM generation and
ffmpeg rendering.

Pipeline:
  haiku JSON + episode JSON
       ↓  (ReleaseCutDirector LLM  —or—  deterministic default)
  storyboard.json   ← THIS MODULE WRITES THIS
       ↓  (ytpipeline.py / render/video.py reads this)
  PNG slides + ffmpeg + BGM
       ↓
  episode_XXX_directors_cut.mp4

Storyboard JSON schema (v1.0)
──────────────────────────────
{
  "version":       "1.0",
  "type":          "episode",          // "haiku" | "episode"
  "episode_index": 1,                  // (episode only)
  "commit_hash":   "abc1234",          // (haiku only)
  "render_profile": "short",           // "minimal" | "short"
  "generated_by":  "default",          // "default" | "ReleaseCutDirector"
  "audio": {
    "track_path":   "/path/to/bgm.caf",
    "volume":       0.3,
    "fade_in_s":    1.0,
    "fade_out_s":   1.5
  },
  "shots": [
    // TitleCard
    { "shot_id": "title_card", "type": "TitleCard",
      "duration_s": 6.0, "title": "...", "subtitle": "..." },

    // CaseRoll  (episode only)
    { "shot_id": "case_roll", "type": "CaseRoll",
      "duration_s": 6.0, "episode_title": "...",
      "case_titles": ["...", ...] },

    // CaseFile  (one per commit)
    { "shot_id": "case_001", "type": "CaseFile",
      "duration_s": 16.0, "commit_hash": "abc1234",
      "title": "...", "subtitle": "...",
      "acts": [
        {"label": "...", "body": "..."},
        {"label": "...", "body": "..."},
        {"label": "...", "body": "..."}
      ],
      "verdict": "..." },

    // VerdictCard
    { "shot_id": "episode_verdict", "type": "VerdictCard",
      "duration_s": 8.0, "ruling": "..." }
  ]
}
"""

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from codestory.core.logging import get_logger

LOGGER = get_logger(__name__)

# ─── Duration tables ──────────────────────────────────────────────────────────

#: Per-type CaseFile slide duration (seconds)
CASE_FILE_DURATION_MAP: Dict[str, float] = {
    "feat":     18.0,
    "fix":      16.0,
    "refactor": 15.0,
    "perf":     15.0,
    "build":    13.0,
    "chore":    12.0,
    "style":    12.0,
    "docs":     12.0,
    "test":     13.0,
    "ci":       12.0,
    "revert":   14.0,
    "other":    14.0,
}


def _case_duration(commit_type: str) -> float:
    """Return the default slide duration for a given commit type."""
    return CASE_FILE_DURATION_MAP.get(commit_type.lower(), 14.0)


# ─── Default (deterministic) storyboard builders ─────────────────────────────

def build_haiku_storyboard(
    haiku: Dict[str, Any],
    audio_cfg: Dict[str, Any],
    render_profile: str = "short",
) -> Dict[str, Any]:
    """
    Build a minimal storyboard for a single haiku commit.

    No LLM call needed — produces the 5-slide structure (header, 3 acts,
    verdict) that the existing ytpipeline already understands.

    Args:
        haiku:          Haiku DB row or LLM response dict.
        audio_cfg:      Audio config sub-dict from config.
        render_profile: "minimal" (no audio) or "short" (with BGM).

    Returns:
        Storyboard dict ready to be serialised as JSON or passed to the
        render pipeline.
    """
    commit_hash = (haiku.get("commit_hash") or haiku.get("hash", "unknown"))[:7]
    commit_type = haiku.get("commit_type") or haiku.get("type", "other")
    chron_idx = haiku.get("chronological_index", 0)

    slide_dur = float(haiku.get("slide_duration_s", 2.5))
    verdict_dur = float(haiku.get("verdict_duration_s", 4.0))

    act1_label = haiku.get("act1_title") or "THE SITUATION"
    act2_label = haiku.get("act2_title") or "THE PLAYERS"
    act3_label = haiku.get("act3_title") or "THE CONSEQUENCE"

    shots: List[Dict[str, Any]] = [
        {
            "shot_id":    "header",
            "type":       "HeaderSlide",
            "duration_s": slide_dur,
            "title":      haiku.get("title", ""),
            "subtitle":   haiku.get("subtitle", ""),
        },
        {
            "shot_id":    "act1",
            "type":       "ActSlide",
            "duration_s": slide_dur,
            "label":      f"ACT I: {act1_label}",
            "body":       haiku.get("when_where", ""),
        },
        {
            "shot_id":    "act2",
            "type":       "ActSlide",
            "duration_s": slide_dur,
            "label":      f"ACT II: {act2_label}",
            "body":       haiku.get("who_whom", ""),
        },
        {
            "shot_id":    "act3",
            "type":       "ActSlide",
            "duration_s": slide_dur,
            "label":      f"ACT III: {act3_label}",
            "body":       haiku.get("what_why", ""),
        },
        {
            "shot_id":    "verdict",
            "type":       "VerdictCard",
            "duration_s": verdict_dur,
            "ruling":     haiku.get("verdict", ""),
        },
    ]

    storyboard: Dict[str, Any] = {
        "version":          "1.0",
        "type":             "haiku",
        "commit_hash":      commit_hash,
        "chronological_index": chron_idx,
        "render_profile":   render_profile,
        "generated_by":     "default",
        "audio":            _audio_for_profile(render_profile, audio_cfg, is_episode=False),
        "total_shots":      len(shots),
        "shots":            shots,
    }

    LOGGER.debug("Built haiku storyboard for %s (%d shots)", commit_hash, len(shots))
    return storyboard


def build_episode_storyboard_default(
    episode: Dict[str, Any],
    haiku_rows: List[Dict[str, Any]],
    audio_cfg: Dict[str, Any],
    render_profile: str = "short",
) -> Dict[str, Any]:
    """
    Build an episode storyboard deterministically (no LLM).

    Shot order:
      1. TitleCard (6s)
      2. CaseRoll  (6s)  — fast-scroll list of case titles
      3. CaseFile × N    — each haiku (duration scaled by commit type)
      4. VerdictCard (8s)

    Args:
        episode:        Episode DB row or pipeline dict.
        haiku_rows:     List of haiku dicts for this episode (in order).
        audio_cfg:      Audio config sub-dict from config.
        render_profile: "minimal" or "short".

    Returns:
        Storyboard dict.
    """
    ep_num = episode.get("episode_number", 0)
    ep_title = episode.get("title", f"Episode {ep_num}")
    max_ruling = episode.get("max_ruling", "")

    case_titles = [h.get("title", f"Case #{i+1}") for i, h in enumerate(haiku_rows)]

    shots: List[Dict[str, Any]] = []

    # Shot 1 — TitleCard
    shots.append({
        "shot_id":    "title_card",
        "type":       "TitleCard",
        "duration_s": 6.0,
        "title":      ep_title,
        "subtitle":   episode.get("branch_note", ""),
    })

    # Shot 2 — CaseRoll
    shots.append({
        "shot_id":      "case_roll",
        "type":         "CaseRoll",
        "duration_s":   6.0,
        "episode_title": ep_title,
        "case_titles":  case_titles,
    })

    # Shots 3…N — CaseFile per haiku
    for idx, haiku in enumerate(haiku_rows):
        commit_type = haiku.get("commit_type") or haiku.get("type", "other")
        commit_hash = (haiku.get("commit_hash") or haiku.get("hash", ""))[:7]
        act1_label = haiku.get("act1_title") or "THE SITUATION"
        act2_label = haiku.get("act2_title") or "THE PLAYERS"
        act3_label = haiku.get("act3_title") or "THE CONSEQUENCE"

        shots.append({
            "shot_id":    f"case_{idx + 1:03d}",
            "type":       "CaseFile",
            "duration_s": _case_duration(commit_type),
            "commit_hash": commit_hash,
            "title":      haiku.get("title", ""),
            "subtitle":   haiku.get("subtitle", ""),
            "acts": [
                {"label": act1_label, "body": haiku.get("when_where", "")},
                {"label": act2_label, "body": haiku.get("who_whom", "")},
                {"label": act3_label, "body": haiku.get("what_why", "")},
            ],
            "verdict": haiku.get("verdict", ""),
        })

    # Final shot — VerdictCard
    shots.append({
        "shot_id":    "episode_verdict",
        "type":       "VerdictCard",
        "duration_s": 8.0,
        "ruling":     max_ruling,
    })

    total_dur = sum(s["duration_s"] for s in shots)
    LOGGER.info(
        "Built default episode storyboard #%d: %d shots, %.1fs total",
        ep_num, len(shots), total_dur,
    )

    return {
        "version":        "1.0",
        "type":           "episode",
        "episode_index":  ep_num,
        "title":          ep_title,
        "render_profile": render_profile,
        "generated_by":   "default",
        "audio":          _audio_for_profile(render_profile, audio_cfg, is_episode=True),
        "total_shots":    len(shots),
        "estimated_duration_s": total_dur,
        "shots":          shots,
    }


# ─── LLM-powered storyboard generator ────────────────────────────────────────

async def generate_episode_storyboard_llm(
    client: Any,
    model: str,
    episode: Dict[str, Any],
    haiku_rows: List[Dict[str, Any]],
    system_prompt: str,
    audio_cfg: Dict[str, Any],
    render_profile: str = "short",
) -> Dict[str, Any]:
    """
    Generate an episode storyboard via the ReleaseCutDirector LLM prompt.

    Falls back to the deterministic default if the LLM call fails.

    Args:
        client:         AsyncAnthropic client.
        model:          Model identifier string.
        episode:        Episode dict.
        haiku_rows:     Haiku dicts for this episode.
        system_prompt:  Content of ReleaseCutDirector.md.
        audio_cfg:      Audio config sub-dict from config.
        render_profile: "minimal" or "short".

    Returns:
        Storyboard dict with `generated_by` set to "ReleaseCutDirector".
    """
    ep_num = episode.get("episode_number", 0)

    # Build the case file list for the LLM
    cases_payload = []
    for h in haiku_rows:
        cases_payload.append({
            "commit_hash":  (h.get("commit_hash") or h.get("hash", ""))[:7],
            "commit_type":  h.get("commit_type") or h.get("type", "other"),
            "branch":       h.get("branch", "main"),
            "date":         (h.get("commit_date") or h.get("date", ""))[:10],
            "title":        h.get("title", ""),
            "subtitle":     h.get("subtitle", ""),
            "act1_title":   h.get("act1_title", ""),
            "when_where":   h.get("when_where", ""),
            "act2_title":   h.get("act2_title", ""),
            "who_whom":     h.get("who_whom", ""),
            "act3_title":   h.get("act3_title", ""),
            "what_why":     h.get("what_why", ""),
            "verdict":      h.get("verdict", ""),
        })

    user_prompt = json.dumps({
        "episode": {
            "episode_number": ep_num,
            "title":          episode.get("title", ""),
            "decade_summary": episode.get("decade_summary", ""),
            "branch_note":    episode.get("branch_note", ""),
            "max_ruling":     episode.get("max_ruling", ""),
        },
        "cases": cases_payload,
    }, indent=2)

    LOGGER.info("Calling ReleaseCutDirector LLM for episode %d storyboard", ep_num)

    try:
        response = await client.messages.create(
            model=model,
            max_tokens=3000,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
            temperature=0.7,
        )

        text_block = next(
            (b for b in response.content if getattr(b, "type", "") == "text"),
            None,
        )
        if text_block is None:
            raise ValueError("No text block in LLM response")

        raw = text_block.text.strip()
        raw = re.sub(r"^```[a-z]*\n?", "", raw)
        raw = re.sub(r"\n?```$", "", raw)

        storyboard = json.loads(raw)
        storyboard["version"] = "1.0"
        storyboard["type"] = "episode"
        storyboard["render_profile"] = render_profile
        storyboard["generated_by"] = "ReleaseCutDirector"
        storyboard["audio"] = _audio_for_profile(render_profile, audio_cfg, is_episode=True)

        total_dur = sum(s.get("duration_s", 0) for s in storyboard.get("shots", []))
        storyboard["estimated_duration_s"] = total_dur

        LOGGER.info(
            "ReleaseCutDirector storyboard: %d shots, %.1fs",
            len(storyboard.get("shots", [])), total_dur,
        )
        return storyboard

    except Exception as exc:
        LOGGER.error("LLM storyboard generation failed: %s — using default", exc)
        fallback = build_episode_storyboard_default(
            episode, haiku_rows, audio_cfg, render_profile
        )
        fallback["generated_by"] = "default_fallback"
        return fallback


# ─── Storyboard persistence ───────────────────────────────────────────────────

def save_storyboard(storyboard: Dict[str, Any], output_path: Path) -> Path:
    """
    Write a storyboard dict to a JSON file.

    Args:
        storyboard:  Storyboard dict to serialise.
        output_path: Destination .json file path.

    Returns:
        Path to the written file.
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(storyboard, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    LOGGER.info("Saved storyboard → %s", output_path.name)
    return output_path


def load_storyboard(storyboard_path: Path) -> Optional[Dict[str, Any]]:
    """
    Load a storyboard JSON file.

    Args:
        storyboard_path: Path to the .json storyboard file.

    Returns:
        Storyboard dict, or None if the file cannot be read.
    """
    storyboard_path = Path(storyboard_path)
    if not storyboard_path.exists():
        LOGGER.warning("Storyboard not found: %s", storyboard_path)
        return None

    try:
        return json.loads(storyboard_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        LOGGER.error("Failed to load storyboard %s: %s", storyboard_path, exc)
        return None


def storyboard_path_for_episode(assets_dir: Path, episode_number: int) -> Path:
    """Return the canonical storyboard path for an episode number."""
    return Path(assets_dir) / "storyboards" / f"storyboard_episode_{episode_number:03d}.json"


def storyboard_path_for_haiku(assets_dir: Path, chron_index: int, short_hash: str) -> Path:
    """Return the canonical storyboard path for a haiku."""
    return Path(assets_dir) / "storyboards" / f"storyboard_haiku_{chron_index:03d}_{short_hash}.json"


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _audio_for_profile(
    render_profile: str,
    audio_cfg: Dict[str, Any],
    is_episode: bool = False,
) -> Dict[str, Any]:
    """
    Return the audio config block for a storyboard.

    In "minimal" profile, track_path is set to None (silent render).
    In "short" profile, the configured track is used.

    Args:
        render_profile: "minimal" or "short".
        audio_cfg:      Audio config sub-dict from the main config.
        is_episode:     If True, prefer `episode_track_path`.

    Returns:
        Audio config dict for embedding in the storyboard.
    """
    if render_profile == "minimal":
        return {
            "track_path":  None,
            "volume":      0.0,
            "fade_in_s":   0.0,
            "fade_out_s":  0.0,
        }

    if is_episode:
        track = audio_cfg.get("episode_track_path") or audio_cfg.get("track_path")
    else:
        track = audio_cfg.get("track_path")

    return {
        "track_path":  track,
        "volume":      float(audio_cfg.get("volume", 0.3)),
        "fade_in_s":   float(audio_cfg.get("fade_in_s", 1.0)),
        "fade_out_s":  float(audio_cfg.get("fade_out_s", 1.5)),
    }
