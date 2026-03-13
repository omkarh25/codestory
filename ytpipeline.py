"""
ytpipeline.py — The codeStory YouTube Shorts Pipeline

Renders codeStory haikus (and optionally episodes) to MP4 video files
entirely headlessly — no user screen recording required.

Method: PyQt6 off-screen rendering via QWidget.grab() → PNG sequence → ffmpeg

Flow per haiku:
  1. Load haiku from DB
  2. For each "slide state" (header, act1, act2, act3, verdict):
     - Apply state to HaikuPlayerWidget / VerdictWidget
     - Call QWidget.grab() to capture a QPixmap
     - Save as PNG to a temp directory
  3. Pass the PNG sequence to ffmpeg with configured slide durations
  4. ffmpeg outputs MP4 to Assets/YtShorts/

Headless rendering notes:
  - Uses QApplication with offscreen platform (QT_QPA_PLATFORM=offscreen)
  - Each "slide" is the FINAL state (typewriter already complete)
    for clean video frames; transitions are handled by ffmpeg fade filter
  - All sizing, colours, and fonts match the live PyQt6 viewer exactly
    because the same widgets are reused

Config keys (config.json → tmChronicles):
  yt_slide_duration_s   float  2.5   seconds per act slide
  yt_verdict_duration_s float  4.0   seconds for verdict slide
  yt_fps                int    30    frames per second
  yt_resolution         str    "1920x1080"   output resolution
  yt_fade_frames        int    8     cross-fade frames between slides
  yt_output_dir         str    "Assets/YtShorts"

Usage (CLI):
  python ytpipeline.py                     # render all un-rendered haikus
  python ytpipeline.py --haiku abc123      # render specific commit hash
  python ytpipeline.py --episode 1         # render episode 1
  python ytpipeline.py --all               # render everything
  python ytpipeline.py --max 3             # render up to 3 haikus

Usage (programmatic):
  from ytpipeline import render_haiku, render_episode
  render_haiku(haiku_dict, cfg)
  render_episode(episode_dict, haiku_list, cfg)
"""

import argparse
import json
import logging
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

# CRITICAL: Set offscreen mode AND create QApplication BEFORE any Qt imports
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

# Create QApplication at module load time before codeQT imports anything
from PyQt6.QtWidgets import QApplication
_qt_app = QApplication.instance()
if _qt_app is None:
    _qt_app = QApplication([])

LOGGER = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parent


# ─── Config ───────────────────────────────────────────────────────────────────

def load_config(overrides: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Load configuration from config.json with ytpipeline-specific defaults.

    Reads both legacy tmChronicles keys and new codestory keys (audio, render).

    Args:
        overrides: Optional key/value overrides.

    Returns:
        Merged config dict.
    """
    defaults: Dict[str, Any] = {
        "db_path":              str(_REPO_ROOT / "tmChron.db"),
        "output_dir":           str(_REPO_ROOT / "Assets" / "haikuJSON"),
        "yt_output_dir":        str(_REPO_ROOT / "Assets" / "YtShorts"),
        "yt_slide_duration_s":  2.5,
        "yt_verdict_duration_s": 4.0,
        "yt_fps":               30,
        "yt_resolution":        "1920x1080",
        "yt_fade_frames":       8,
        "yt_render_width":      1920,
        "yt_render_height":     1080,
        # Director's Cut audio defaults (GarageBand Chillwave loops — royalty-free)
        "audio": {
            "track_path": "/Library/Audio/Apple Loops/Apple/07 Chillwave/Kyoto Night Synth.caf",
            "episode_track_path": "/Library/Audio/Apple Loops/Apple/07 Chillwave/Ghost Harmonics Synth.caf",
            "volume": 0.3,
            "fade_in_s": 1.0,
            "fade_out_s": 1.5,
        },
        # Render profile: "minimal" (silent, fast) | "short" (BGM + casefile MD)
        "render": {
            "profile": "short",
            "write_casefile_md": True,
        },
    }
    config_path = _REPO_ROOT / "config.json"
    try:
        with open(config_path) as f:
            raw = json.load(f)
        # Support both legacy "tmChronicles" and new "codestory" config keys
        cfg = raw.get("codestory", raw.get("tmChronicles", {}))
        for key in ("db_path", "output_dir", "yt_output_dir"):
            if key in cfg and not Path(cfg[key]).is_absolute():
                cfg[key] = str(_REPO_ROOT / cfg[key])
        # Deep-merge nested dicts (audio, render) rather than replacing them
        for nested_key in ("audio", "render"):
            if nested_key in cfg and isinstance(cfg[nested_key], dict):
                defaults[nested_key].update(cfg[nested_key])
                del cfg[nested_key]
        defaults.update(cfg)
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        LOGGER.warning("config.json not loaded: %s — using defaults", exc)
    if overrides:
        defaults.update({k: v for k, v in overrides.items() if v is not None})
    return defaults


# ─── DB helpers ───────────────────────────────────────────────────────────────

def load_haiku_by_hash(db_path: str, commit_hash: str) -> Optional[Dict[str, Any]]:
    """Load a single haiku from DB by commit hash prefix.

    Args:
        db_path:     Path to tmChron.db.
        commit_hash: Full or short (7+) commit hash.

    Returns:
        Haiku dict or None if not found.
    """
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM haiku_commits WHERE commit_hash LIKE ?",
            (f"{commit_hash}%",),
        ).fetchone()
        conn.close()
        return dict(row) if row else None
    except sqlite3.Error as exc:
        LOGGER.error("DB error loading haiku: %s", exc)
        return None


def load_all_haikus(db_path: str) -> List[Dict[str, Any]]:
    """Load all haiku rows in chronological order.

    Args:
        db_path: Path to tmChron.db.

    Returns:
        List of haiku dicts ordered by chronological_index.
    """
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """SELECT * FROM haiku_commits
               ORDER BY CASE WHEN chronological_index > 0
                        THEN chronological_index ELSE id END ASC"""
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except sqlite3.Error as exc:
        LOGGER.error("DB error loading haikus: %s", exc)
        return []


def load_episode(db_path: str, episode_number: int) -> Optional[Dict[str, Any]]:
    """Load a single episode from DB.

    Args:
        db_path:        Path to tmChron.db.
        episode_number: Episode number to load.

    Returns:
        Episode dict or None.
    """
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM chronicle_episodes WHERE episode_number = ?",
            (episode_number,),
        ).fetchone()
        conn.close()
        return dict(row) if row else None
    except sqlite3.Error as exc:
        LOGGER.error("DB error loading episode: %s", exc)
        return None


# ─── Slide renderer ───────────────────────────────────────────────────────────

def _ensure_offscreen_app() -> "QApplication":
    """Ensure a QApplication exists for offscreen rendering.

    Sets QT_QPA_PLATFORM=offscreen so no display is required.

    Returns:
        QApplication instance.
    """
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance()
    if app is None:
        # Create with empty argv to avoid GUI initialization issues
        app = QApplication([])
    return app


def render_haiku_slides(
    haiku: Dict[str, Any],
    render_w: int,
    render_h: int,
) -> List[Path]:
    """Render all slides for a haiku to PNG files in a temp directory.

    Creates 5 slides in order:
      0 — header_only (title + subtitle + metadata, no acts)
      1 — act1 (header + ACT I revealed)
      2 — act2 (header + ACT I + ACT II revealed)
      3 — act3 (header + ACT I + ACT II + ACT III revealed)
      4 — verdict (full-screen verdict panel)

    Uses the live codeQT widgets with QWidget.grab() so renders are
    pixel-perfect matches of the interactive UI.

    Args:
        haiku:    Haiku dict from DB.
        render_w: Output pixel width.
        render_h: Output pixel height.

    Returns:
        List of 5 PNG file Paths in slide order.
    """
    # Ensure QApplication exists BEFORE importing widgets
    _ensure_offscreen_app()

    from PyQt6.QtWidgets import QWidget
    from PyQt6.QtCore import QSize
    from codeQT import HaikuPlayerWidget, VerdictWidget, HaikuState

    tmp_dir = Path(tempfile.mkdtemp(prefix="codestory_yt_"))
    LOGGER.info("Rendering haiku slides to %s", tmp_dir)

    slides: List[Path] = []
    size = QSize(render_w, render_h)

    # ── Slides 0-3: haiku player in different states ──────────────────────────
    player = HaikuPlayerWidget()
    player.resize(size)
    player.load_haiku(haiku, 1, 1)

    # Slide 0: header only (IDLE state — no acts shown)
    slide0 = tmp_dir / "slide_00_header.png"
    _grab_widget(player, slide0)
    slides.append(slide0)

    # Simulate act reveals by directly injecting state
    act_body_keys = ["when_where", "who_whom", "what_why"]
    act_title_keys = ["act1_title", "act2_title", "act3_title"]
    roman = ["I", "II", "III"]

    for act_idx in range(3):
        # Set act label text (typewriter complete)
        act_title = haiku.get(act_title_keys[act_idx]) or ""
        label_text = f"ACT {roman[act_idx]}: {act_title}" if act_title else f"ACT {roman[act_idx]}"
        w = player._act_widgets[act_idx]
        w["label"].setText(label_text)
        w["label"].show()
        # Reveal body text
        w["body"].setText(haiku.get(act_body_keys[act_idx], ""))
        w["body"].show()
        # Force re-render
        player.repaint()
        slide_path = tmp_dir / f"slide_{act_idx + 1:02d}_act{act_idx + 1}.png"
        _grab_widget(player, slide_path)
        slides.append(slide_path)

    # ── Slide 4: verdict ──────────────────────────────────────────────────────
    verdict_w = VerdictWidget()
    verdict_w.resize(size)
    verdict_w._lbl_title.setText("🔑  VERDICT")
    verdict_w._lbl_body.setText(f'"{haiku.get("verdict", "")}"')
    verdict_w._lbl_body.show()
    verdict_w._state = HaikuState.VERDICT_READY
    verdict_w.repaint()

    slide4 = tmp_dir / "slide_04_verdict.png"
    _grab_widget(verdict_w, slide4)
    slides.append(slide4)

    LOGGER.info("Rendered %d haiku slides to %s", len(slides), tmp_dir)
    return slides


def render_episode_slides(
    episode: Dict[str, Any],
    render_w: int,
    render_h: int,
    case_titles: Optional[List[str]] = None,
) -> List[Path]:
    """Render Director's Cut slides for an episode to PNG files.

    Creates 4 cinematic slides:
      0 — TitleCard    : episode number + title (full-bleed dark void)
      1 — CaseRoll     : fast-scroll list of all case file titles
      2 — SummaryCard  : decade_summary paragraph (episode narrative arc)
      3 — VerdictCard  : MAX'S RULING full-screen emphasis

    Args:
        episode:     Episode dict from DB.
        render_w:    Output pixel width.
        render_h:    Output pixel height.
        case_titles: Optional list of case file titles for CaseRoll slide.
                     If None, the CaseRoll slide is skipped (fallback to 3 slides).

    Returns:
        List of PNG Paths (3 or 4 slides).
    """
    _ensure_offscreen_app()

    from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QFrame, QLabel
    from PyQt6.QtCore import QSize, Qt
    from codeQT import (
        BG_DARK, BG_CARD, DIVIDER_COL, TEXT_WHITE, TEXT_EPISODE_T,
        TEXT_BODY, TEXT_SUBTITLE, TEXT_RULING, _label, _divider,
    )

    tmp_dir = Path(tempfile.mkdtemp(prefix="codestory_ep_"))
    slides: List[Path] = []
    size = QSize(render_w, render_h)

    ep_num   = episode.get("episode_number", 0)
    ep_title = episode.get("title", f"Episode {ep_num}")

    # ── Slide 0: TitleCard — cold open ────────────────────────────────────────
    title_w = QWidget()
    title_w.resize(size)
    title_w.setStyleSheet(f"background:{BG_DARK};")
    tl = QVBoxLayout(title_w)
    tl.setContentsMargins(0, 0, 0, 0)
    tl.addStretch(3)

    ep_num_lbl = _label(
        f"EPISODE {ep_num:02d}",
        TEXT_SUBTITLE, 18, bold=False,
        align=Qt.AlignmentFlag.AlignCenter,
    )
    ep_num_lbl.setStyleSheet(
        f"color:{TEXT_SUBTITLE}; letter-spacing:6px;"
    )
    tl.addWidget(ep_num_lbl)
    tl.addSpacing(16)

    tl.addWidget(_label(
        ep_title,
        TEXT_WHITE, 36, bold=True,
        align=Qt.AlignmentFlag.AlignCenter,
    ))
    tl.addSpacing(12)

    branch_note = episode.get("branch_note", "")
    if branch_note:
        tl.addWidget(_label(
            branch_note,
            TEXT_SUBTITLE, 16, italic=True,
            align=Qt.AlignmentFlag.AlignCenter,
        ))

    tl.addStretch(4)
    title_w.repaint()
    slide0 = tmp_dir / "slide_00_title.png"
    _grab_widget(title_w, slide0)
    slides.append(slide0)

    # ── Slide 1: CaseRoll — scroll of case titles ──────────────────────────────
    if case_titles:
        roll_w = QWidget()
        roll_w.resize(size)
        roll_w.setStyleSheet(f"background:{BG_DARK};")
        rl = QVBoxLayout(roll_w)
        rl.setContentsMargins(160, 80, 160, 80)
        rl.setSpacing(8)

        rl.addWidget(_label(
            ep_title.upper(),
            TEXT_SUBTITLE, 13, bold=False,
            align=Qt.AlignmentFlag.AlignLeft,
        ))
        rl.addWidget(_divider())
        rl.addSpacing(12)

        for i, ct in enumerate(case_titles[:12]):
            row_lbl = _label(
                f"  {i+1:02d}.  {ct}",
                TEXT_BODY, 15,
                align=Qt.AlignmentFlag.AlignLeft,
            )
            rl.addWidget(row_lbl)

        rl.addStretch()
        roll_w.repaint()
        slide1 = tmp_dir / "slide_01_caseroll.png"
        _grab_widget(roll_w, slide1)
        slides.append(slide1)

    # ── Slide 2: SummaryCard — decade narrative ────────────────────────────────
    from codeQT import EpisodeCardWidget
    card_wrap = QWidget()
    card_wrap.resize(size)
    card_wrap.setStyleSheet(f"background:{BG_DARK};")
    cl = QVBoxLayout(card_wrap)
    cl.setContentsMargins(120, 100, 120, 100)
    cl.addWidget(EpisodeCardWidget(episode))
    cl.addStretch()
    card_wrap.repaint()
    slide_n = tmp_dir / f"slide_{len(slides):02d}_summary.png"
    _grab_widget(card_wrap, slide_n)
    slides.append(slide_n)

    # ── Slide 3: VerdictCard — MAX'S RULING ───────────────────────────────────
    ruling_w = QWidget()
    ruling_w.resize(size)
    ruling_w.setStyleSheet(f"background:{BG_DARK};")
    vl = QVBoxLayout(ruling_w)
    vl.setContentsMargins(0, 0, 0, 0)
    vl.addStretch(2)

    panel = QFrame()
    panel.setStyleSheet(
        f"background:{BG_CARD}; border:1px solid {DIVIDER_COL}; border-radius:8px;"
    )
    pl = QVBoxLayout(panel)
    pl.setContentsMargins(80, 60, 80, 60)
    pl.setSpacing(20)
    pl.addWidget(_label("⚖  MAX'S RULING", TEXT_RULING, 16, bold=True))
    pl.addWidget(_label(
        f'"{episode.get("max_ruling", "")}"',
        TEXT_WHITE, 20, bold=True, italic=True,
        align=Qt.AlignmentFlag.AlignCenter,
    ))

    container = QHBoxLayout()
    container.setContentsMargins(100, 0, 100, 0)
    container.addWidget(panel)
    vl.addLayout(container)
    vl.addStretch(3)
    ruling_w.repaint()
    verdict_path = tmp_dir / f"slide_{len(slides):02d}_ruling.png"
    _grab_widget(ruling_w, verdict_path)
    slides.append(verdict_path)

    LOGGER.info("Rendered %d episode slides to %s", len(slides), tmp_dir)
    return slides


def _grab_widget(widget: "QWidget", output_path: Path) -> None:
    """Grab a widget as a QPixmap and save to PNG.

    Args:
        widget:      The Qt widget to capture.
        output_path: Path to write the PNG file.
    """
    from PyQt6.QtWidgets import QApplication

    QApplication.processEvents()
    pixmap = widget.grab()
    pixmap.save(str(output_path), "PNG")
    LOGGER.debug("Grabbed widget → %s (%dx%d)", output_path.name,
                 pixmap.width(), pixmap.height())


# ─── ffmpeg assembly ──────────────────────────────────────────────────────────

def _check_ffmpeg() -> bool:
    """Check that ffmpeg is available in PATH.

    Returns:
        True if ffmpeg is found, False otherwise.
    """
    return shutil.which("ffmpeg") is not None


def assemble_haiku_video(
    slides: List[Path],
    output_path: Path,
    cfg: Dict[str, Any],
    audio_cfg: Optional[Dict[str, Any]] = None,
) -> bool:
    """Assemble PNG slide sequence into an MP4 via ffmpeg, optionally with BGM.

    Slide timing:
      - Slides 0-3 (acts): yt_slide_duration_s each
      - Slide 4 (verdict): yt_verdict_duration_s

    When `audio_cfg` is provided and `track_path` points to a readable file,
    the track is looped via ``-stream_loop -1`` and faded in/out using
    ffmpeg's ``afade`` filter.  Falls back to silent render gracefully.

    Args:
        slides:      Ordered list of PNG slide paths (5 slides).
        output_path: MP4 output file path.
        cfg:         Config dict with yt_* keys.
        audio_cfg:   Optional audio config dict (track_path, volume, fade_in_s,
                     fade_out_s).  Pass None or omit for silent render.

    Returns:
        True on success, False on ffmpeg failure.
    """
    if not _check_ffmpeg():
        LOGGER.error("ffmpeg not found in PATH")
        print("[ytpipeline] ERROR: ffmpeg not found. Install via: brew install ffmpeg")
        return False

    fps         = int(cfg.get("yt_fps", 30))
    slide_dur   = float(cfg.get("yt_slide_duration_s", 2.5))
    verdict_dur = float(cfg.get("yt_verdict_duration_s", 4.0))
    resolution  = cfg.get("yt_resolution", "1920x1080")

    # Duration list: first N-1 slides get slide_dur, last (verdict) gets verdict_dur
    if len(slides) == 5:
        durations = [slide_dur] * 4 + [verdict_dur]
    else:
        durations = [slide_dur] * max(0, len(slides) - 1) + [verdict_dur]
        durations = durations[:len(slides)]

    total_dur = sum(durations)

    # Build concat list file in the same temp dir as the PNGs
    tmp_dir = slides[0].parent
    concat_file = tmp_dir / "concat.txt"
    with open(concat_file, "w") as f:
        for slide, dur in zip(slides, durations):
            f.write(f"file '{slide}'\n")
            f.write(f"duration {dur}\n")
        # ffmpeg concat demuxer requires a final entry with no duration
        f.write(f"file '{slides[-1]}'\n")

    output_path.parent.mkdir(parents=True, exist_ok=True)

    # ── Determine whether to mix in BGM ──────────────────────────────────────
    track_path = (audio_cfg or {}).get("track_path") if audio_cfg else None
    use_audio = bool(track_path and Path(track_path).exists())

    if track_path and not Path(track_path).exists():
        LOGGER.warning("BGM track not found: %s — rendering silent", track_path)

    if use_audio:
        volume       = float(audio_cfg.get("volume", 0.3))
        fade_in      = float(audio_cfg.get("fade_in_s", 1.0))
        fade_out     = float(audio_cfg.get("fade_out_s", 1.5))
        fade_out_start = max(0.0, total_dur - fade_out)

        # afade filters: fade in at t=0, fade out near end, trim to exact duration
        audio_filter = (
            f"[0:a]volume={volume},"
            f"afade=t=in:st=0:d={fade_in},"
            f"afade=t=out:st={fade_out_start:.3f}:d={fade_out},"
            f"atrim=duration={total_dur:.3f}"
            "[aout]"
        )

        cmd = [
            "ffmpeg", "-y",
            # input 0: BGM looped infinitely (trimmed by atrim above)
            "-stream_loop", "-1",
            "-i", str(track_path),
            # input 1: PNG slide sequence
            "-f", "concat", "-safe", "0",
            "-i", str(concat_file),
            "-filter_complex", audio_filter,
            "-map", "1:v",
            "-map", "[aout]",
            "-vf", f"scale={resolution},fps={fps},format=yuv420p",
            "-c:v", "libx264", "-preset", "fast", "-crf", "18",
            "-c:a", "aac", "-b:a", "128k",
            str(output_path),
        ]
        LOGGER.info(
            "ffmpeg with BGM: track=%s vol=%.1f dur=%.1fs",
            Path(track_path).name, volume, total_dur,
        )
    else:
        # Silent render (minimal profile or missing track)
        cmd = [
            "ffmpeg", "-y",
            "-f", "concat", "-safe", "0", "-i", str(concat_file),
            "-vf", f"scale={resolution},fps={fps},format=yuv420p",
            "-c:v", "libx264", "-preset", "fast", "-crf", "18",
            str(output_path),
        ]
        LOGGER.info("ffmpeg silent: %d slides, %.1fs total", len(slides), total_dur)

    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, cwd=str(tmp_dir),
        )
        if result.returncode != 0:
            LOGGER.error("ffmpeg error:\n%s", result.stderr[-500:])
            print(f"[ytpipeline] ffmpeg error: {result.stderr[-200:]}")
            return False
        LOGGER.info("ffmpeg success: %s", output_path)
        return True
    except Exception as exc:
        LOGGER.error("ffmpeg exception: %s", exc)
        return False


# ─── Public render functions ──────────────────────────────────────────────────

def _resolve_audio_cfg(cfg: Dict[str, Any], is_episode: bool = False) -> Optional[Dict[str, Any]]:
    """Return audio config for the current render profile, or None if minimal.

    In "minimal" profile, always returns None (silent render).
    In "short" profile, returns the audio sub-dict from cfg with the
    appropriate track_path (haiku vs episode BGM).

    Args:
        cfg:        Full config dict.
        is_episode: If True, prefer episode_track_path over track_path.

    Returns:
        Audio config dict, or None for silent render.
    """
    render_cfg  = cfg.get("render", {})
    profile     = render_cfg.get("profile", "short")

    if profile == "minimal":
        LOGGER.debug("Render profile=minimal — skipping BGM")
        return None

    audio_cfg = dict(cfg.get("audio", {}))
    if is_episode:
        ep_track = audio_cfg.pop("episode_track_path", None)
        if ep_track:
            audio_cfg["track_path"] = ep_track
        LOGGER.debug("Episode BGM: %s", audio_cfg.get("track_path"))
    else:
        audio_cfg.pop("episode_track_path", None)
        LOGGER.debug("Haiku BGM: %s", audio_cfg.get("track_path"))

    return audio_cfg


def _load_episode_case_titles(db_path: str, episode: Dict[str, Any]) -> List[str]:
    """Load case file titles for the haikus in an episode.

    Args:
        db_path: SQLite DB path.
        episode: Episode dict (needs commit_hashes JSON field).

    Returns:
        List of haiku title strings in chronological order.
    """
    raw = episode.get("commit_hashes", "[]")
    if isinstance(raw, str):
        try:
            hashes = json.loads(raw)
        except json.JSONDecodeError:
            return []
    else:
        hashes = list(raw)

    if not hashes:
        return []

    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        titles: List[str] = []
        for h in hashes:
            row = conn.execute(
                "SELECT title FROM haiku_commits WHERE commit_hash = ?", (h,)
            ).fetchone()
            if row and row["title"]:
                titles.append(row["title"])
        conn.close()
        return titles
    except sqlite3.Error as exc:
        LOGGER.warning("Could not load case titles: %s", exc)
        return []


def render_haiku(haiku: Dict[str, Any], cfg: Dict[str, Any]) -> Optional[Path]:
    """Render a single haiku to MP4 with optional Director's Cut BGM + casefile MD.

    Generates 5 slides (header, 3 acts, verdict) and assembles them into
    an MP4.  In "short" render profile (default), Kyoto Night Synth loops
    as BGM and a companion Director's Cut casefile .md is written alongside.

    Args:
        haiku: Haiku dict from DB.
        cfg:   Config dict with yt_* render settings, audio, and render keys.

    Returns:
        Path to the output MP4 file, or None on failure.
    """
    _ensure_offscreen_app()

    short_hash = (haiku.get("commit_hash") or "unknown")[:7]
    chron_idx  = haiku.get("chronological_index", 0)
    branch     = (haiku.get("branch") or "main").replace("/", "-")
    output_dir = Path(cfg.get("yt_output_dir", str(_REPO_ROOT / "Assets" / "YtShorts")))
    output_dir.mkdir(parents=True, exist_ok=True)

    filename = f"haiku_{chron_idx:03d}_{branch}_{short_hash}.mp4"
    output_path = output_dir / filename

    render_cfg   = cfg.get("render", {})
    profile      = render_cfg.get("profile", "short")
    write_md     = render_cfg.get("write_casefile_md", True)
    audio_cfg    = _resolve_audio_cfg(cfg, is_episode=False)

    if output_path.exists():
        LOGGER.info("Video already exists, skipping: %s", filename)
        print(f"[ytpipeline] Skipping (exists): {filename}")
        return output_path

    render_w = int(cfg.get("yt_render_width", 1920))
    render_h = int(cfg.get("yt_render_height", 1080))

    bgm_name = Path(audio_cfg["track_path"]).name if audio_cfg else "silent"
    print(f"[ytpipeline] Rendering haiku {chron_idx:03d} ({short_hash}) [{profile}, BGM: {bgm_name}]...")
    LOGGER.info("Rendering haiku: #%d %s profile=%s bgm=%s", chron_idx, short_hash, profile, bgm_name)

    try:
        slides  = render_haiku_slides(haiku, render_w, render_h)
        success = assemble_haiku_video(slides, output_path, cfg, audio_cfg=audio_cfg)

        if success:
            print(f"[ytpipeline] ✓ {filename}")
            if slides:
                shutil.rmtree(slides[0].parent, ignore_errors=True)

            # ── Director's Cut casefile markdown ─────────────────────────────
            if write_md and profile != "minimal":
                try:
                    from codestory.render.markdown import write_cinematic_casefile
                    md_dir = output_dir / "casefiles"
                    commit = {
                        "hash":   haiku.get("commit_hash", ""),
                        "msg":    haiku.get("commit_msg", ""),
                        "branch": haiku.get("branch", "main"),
                        "author": haiku.get("author", ""),
                        "date":   haiku.get("commit_date", ""),
                        "type":   haiku.get("commit_type", "other"),
                    }
                    md_path = write_cinematic_casefile(md_dir, commit, haiku, chron_idx)
                    print(f"[ytpipeline] ✍  {md_path.name}")
                    LOGGER.info("Wrote Director's Cut casefile: %s", md_path.name)
                except ImportError:
                    LOGGER.debug("render.markdown not available — skipping casefile MD")
                except Exception as exc:
                    LOGGER.warning("Casefile MD failed: %s", exc)

            return output_path
        else:
            print(f"[ytpipeline] ✗ Failed: {filename}")
            return None
    except Exception as exc:
        LOGGER.error("render_haiku failed for %s: %s", short_hash, exc)
        print(f"[ytpipeline] ERROR: {exc}")
        return None


def render_episode(
    episode: Dict[str, Any],
    cfg: Dict[str, Any],
) -> Optional[Path]:
    """Render a single episode to a Director's Cut MP4 with 4 cinematic slides.

    Slide order:
      0 — TitleCard    : cold open with episode number + title
      1 — CaseRoll     : fast-scroll list of 10 case file titles
      2 — SummaryCard  : decade_summary narrative
      3 — VerdictCard  : MAX'S RULING full-bleed emphasis

    Ghost Harmonics Synth is used as BGM (more dramatic than the haiku track).

    Args:
        episode: Episode dict from DB.
        cfg:     Config dict with yt_* render settings, audio, and render keys.

    Returns:
        Path to the output MP4 file, or None on failure.
    """
    ep_num = episode.get("episode_number", 0)
    output_dir = Path(cfg.get("yt_output_dir", str(_REPO_ROOT / "Assets" / "YtShorts")))
    output_dir.mkdir(parents=True, exist_ok=True)

    filename = f"episode_{ep_num:03d}.mp4"
    output_path = output_dir / filename

    render_cfg = cfg.get("render", {})
    profile    = render_cfg.get("profile", "short")
    audio_cfg  = _resolve_audio_cfg(cfg, is_episode=True)

    if output_path.exists():
        LOGGER.info("Video already exists: %s", filename)
        print(f"[ytpipeline] Skipping (exists): {filename}")
        return output_path

    render_w = int(cfg.get("yt_render_width", 1920))
    render_h = int(cfg.get("yt_render_height", 1080))

    bgm_name = Path(audio_cfg["track_path"]).name if audio_cfg else "silent"
    print(f"[ytpipeline] Rendering episode {ep_num:03d} [{profile}, BGM: {bgm_name}]...")
    LOGGER.info("Rendering episode %d profile=%s bgm=%s", ep_num, profile, bgm_name)

    try:
        # Load case titles for CaseRoll slide
        db_path      = cfg.get("db_path", "")
        case_titles  = _load_episode_case_titles(db_path, episode) if db_path else []
        LOGGER.info("Episode %d: %d case titles loaded", ep_num, len(case_titles))

        slides = render_episode_slides(
            episode, render_w, render_h,
            case_titles=case_titles or None,
        )

        # Episode per-slide durations: TitleCard + CaseRoll short, summary longer, ruling long
        n_slides     = len(slides)
        slide_dur    = float(cfg.get("yt_slide_duration_s", 2.5))
        verdict_dur  = float(cfg.get("yt_verdict_duration_s", 4.0))
        episode_cfg  = dict(cfg)
        episode_cfg["yt_slide_duration_s"]  = slide_dur * 2.2   # ~5.5s per slide
        episode_cfg["yt_verdict_duration_s"] = verdict_dur * 2.0  # ~8s for ruling

        success = assemble_haiku_video(
            slides, output_path, episode_cfg, audio_cfg=audio_cfg
        )

        if success:
            print(f"[ytpipeline] ✓ {filename}  ({n_slides} slides)")
            if slides:
                shutil.rmtree(slides[0].parent, ignore_errors=True)
            return output_path

        print(f"[ytpipeline] ✗ Failed: {filename}")
        return None
    except Exception as exc:
        LOGGER.error("render_episode failed for episode %d: %s", ep_num, exc)
        print(f"[ytpipeline] ERROR: {exc}")
        return None


# ─── CLI ──────────────────────────────────────────────────────────────────────

def main() -> int:
    """Main CLI entry point for ytpipeline.

    Returns:
        Exit code (0 = success).
    """
    # Ensure QApplication is created BEFORE any other imports
    # (especially before loading codeQT which may instantiate widgets)
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtWidgets import QApplication
    if QApplication.instance() is None:
        QApplication(sys.argv)

    parser = argparse.ArgumentParser(
        description="codeStory YouTube Shorts Pipeline — headless haiku → MP4",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
examples:
  python ytpipeline.py                 # render all new haikus
  python ytpipeline.py --all           # render all haikus + episodes
  python ytpipeline.py --haiku abc123  # render specific commit hash
  python ytpipeline.py --episode 1     # render episode 1
  python ytpipeline.py --max 3         # render up to 3 haikus
  python ytpipeline.py --list          # list what would be rendered
        """,
    )
    parser.add_argument("--haiku",   default=None, metavar="HASH",
                        help="Render specific commit hash (prefix OK)")
    parser.add_argument("--episode", default=None, type=int, metavar="N",
                        help="Render specific episode number")
    parser.add_argument("--all",     action="store_true",
                        help="Render all haikus and episodes")
    parser.add_argument("--max",     default=None, type=int, metavar="N",
                        help="Max haikus to render per run")
    parser.add_argument("--list",    action="store_true",
                        help="List renderable items without rendering")
    parser.add_argument(
        "--render-profile",
        choices=["minimal", "short"],
        default=None,
        metavar="PROFILE",
        help="minimal (silent, fast) | short (BGM + casefile MD, default)",
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
    )

    cfg = load_config()

    # Apply render-profile CLI override (takes precedence over config file)
    if args.render_profile:
        cfg.setdefault("render", {})["profile"] = args.render_profile
        LOGGER.info("Render profile overridden to: %s", args.render_profile)

    if not _check_ffmpeg():
        print("ERROR: ffmpeg not found. Install via: brew install ffmpeg")
        return 1

    db_path = cfg["db_path"]

    # ── Single haiku ──────────────────────────────────────────────────────────
    if args.haiku:
        haiku = load_haiku_by_hash(db_path, args.haiku)
        if not haiku:
            print(f"ERROR: Haiku not found for hash '{args.haiku}'")
            return 1
        result = render_haiku(haiku, cfg)
        return 0 if result else 1

    # ── Single episode ────────────────────────────────────────────────────────
    if args.episode:
        episode = load_episode(db_path, args.episode)
        if not episode:
            print(f"ERROR: Episode {args.episode} not found")
            return 1
        result = render_episode(episode, cfg)
        return 0 if result else 1

    # ── Batch haikus ──────────────────────────────────────────────────────────
    haikus = load_all_haikus(db_path)
    yt_dir = Path(cfg.get("yt_output_dir", str(_REPO_ROOT / "Assets" / "YtShorts")))
    yt_dir.mkdir(parents=True, exist_ok=True)

    # Filter to un-rendered haikus
    to_render = []
    for h in haikus:
        chron = h.get("chronological_index", 0)
        branch = (h.get("branch") or "main").replace("/", "-")
        short = (h.get("commit_hash") or "")[:7]
        fname = f"haiku_{chron:03d}_{branch}_{short}.mp4"
        if not (yt_dir / fname).exists():
            to_render.append(h)

    if args.max:
        to_render = to_render[:args.max]

    if args.list:
        print(f"[ytpipeline] {len(to_render)} haiku(s) queued for rendering:")
        for h in to_render:
            print(f"  #{h.get('chronological_index', 0):03d}  {(h.get('commit_hash') or '')[:7]}  {h.get('commit_msg', '')[:60]}")
        return 0

    if not to_render:
        print("[ytpipeline] All haikus already rendered. Nothing to do.")
        return 0

    print(f"[ytpipeline] Rendering {len(to_render)} haiku(s)...")
    success_count = 0
    for haiku in to_render:
        result = render_haiku(haiku, cfg)
        if result:
            success_count += 1

    if args.all:
        # Also render episodes
        try:
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            episodes = [dict(r) for r in conn.execute(
                "SELECT * FROM chronicle_episodes ORDER BY episode_number ASC"
            ).fetchall()]
            conn.close()
            for ep in episodes:
                ep_fname = f"episode_{ep['episode_number']:03d}.mp4"
                if not (yt_dir / ep_fname).exists():
                    render_episode(ep, cfg)
        except sqlite3.Error as exc:
            LOGGER.error("DB error loading episodes: %s", exc)

    print(f"\n[ytpipeline] Done. {success_count}/{len(to_render)} haikus rendered.")
    print(f"[ytpipeline] Output directory: {yt_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
