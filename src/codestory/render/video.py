"""
Video rendering for codeStory YouTube Shorts.

Renders codeStory haikus (and optionally episodes) to MP4 video files
entirely headlessly — no user screen recording required.

Method: PyQt6 off-screen rendering via QWidget.grab() → PNG sequence → ffmpeg
"""

import argparse
import logging
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

# CRITICAL: Set offscreen mode for headless rendering
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from codestory.core.logging import get_logger
from codestory.core.config import load_config

LOGGER = get_logger(__name__)

# Import Qt constants from the viewer module
from codestory.viewer.qt_viewer import (
    HaikuPlayerWidget,
    VerdictWidget,
    HaikuState,
    BG_DARK,
    BG_CARD,
    DIVIDER_COL,
    TEXT_WHITE,
    TEXT_SUBTITLE,
    TEXT_BODY,
    TEXT_ACT_LABEL,
    TEXT_VERDICT_L,
    TEXT_VERDICT_B,
    TEXT_RULING,
    TEXT_EPISODE_T,
    _label,
    _divider,
)

# Repo root is parent of src/
_REPO_ROOT = Path(__file__).parent.parent.parent.parent


# ─── DB helpers ───────────────────────────────────────────────────────────────

def load_haiku_by_hash(db_path: str, commit_hash: str) -> Optional[Dict[str, Any]]:
    """Load a single haiku from DB by commit hash prefix."""
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
    """Load all haiku rows in chronological order."""
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
    """Load a single episode from DB."""
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

def _ensure_offscreen_app():
    """Ensure a QApplication exists for offscreen rendering."""
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def render_haiku_slides(
    haiku: Dict[str, Any],
    render_w: int,
    render_h: int,
) -> List[Path]:
    """Render all slides for a haiku to PNG files in a temp directory."""
    _ensure_offscreen_app()

    from PyQt6.QtWidgets import QWidget
    from PyQt6.QtCore import QSize

    tmp_dir = Path(tempfile.mkdtemp(prefix="codestory_yt_"))
    LOGGER.info("Rendering haiku slides to %s", tmp_dir)

    slides: List[Path] = []
    size = QSize(render_w, render_h)

    # Slides 0-3: haiku player in different states
    player = HaikuPlayerWidget()
    player.resize(size)
    player.load_haiku(haiku, 1, 1)

    # Slide 0: header only (IDLE state)
    slide0 = tmp_dir / "slide_00_header.png"
    _grab_widget(player, slide0)
    slides.append(slide0)

    # Simulate act reveals
    act_body_keys = ["when_where", "who_whom", "what_why"]
    act_title_keys = ["act1_title", "act2_title", "act3_title"]
    roman = ["I", "II", "III"]

    for act_idx in range(3):
        act_title = haiku.get(act_title_keys[act_idx]) or ""
        label_text = f"ACT {roman[act_idx]}: {act_title}" if act_title else f"ACT {roman[act_idx]}"
        w = player._act_widgets[act_idx]
        w["label"].setText(label_text)
        w["label"].show()
        w["body"].setText(haiku.get(act_body_keys[act_idx], ""))
        w["body"].show()
        player.repaint()
        slide_path = tmp_dir / f"slide_{act_idx + 1:02d}_act{act_idx + 1}.png"
        _grab_widget(player, slide_path)
        slides.append(slide_path)

    # Slide 4: verdict
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
    """Render Director's Cut slides for an episode to PNG files."""
    _ensure_offscreen_app()

    from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QFrame
    from PyQt6.QtCore import QSize, Qt

    tmp_dir = Path(tempfile.mkdtemp(prefix="codestory_ep_"))
    slides: List[Path] = []
    size = QSize(render_w, render_h)

    ep_num = episode.get("episode_number", 0)
    ep_title = episode.get("title", f"Episode {ep_num}")

    # Slide 0: TitleCard
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

    # Slide 1: CaseRoll
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

    # Slide 2: SummaryCard
    from codestory.viewer.qt_viewer import EpisodeCardWidget
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

    # Slide 3: VerdictCard
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


def _grab_widget(widget, output_path: Path) -> None:
    """Grab a widget as a QPixmap and save to PNG."""
    from PyQt6.QtWidgets import QApplication

    QApplication.processEvents()
    pixmap = widget.grab()
    pixmap.save(str(output_path), "PNG")
    LOGGER.debug("Grabbed widget → %s (%dx%d)", output_path.name,
                 pixmap.width(), pixmap.height())


# ─── ffmpeg assembly ──────────────────────────────────────────────────────────

def _check_ffmpeg() -> bool:
    """Check that ffmpeg is available in PATH."""
    return shutil.which("ffmpeg") is not None


def assemble_haiku_video(
    slides: List[Path],
    output_path: Path,
    cfg: Dict[str, Any],
    audio_cfg: Optional[Dict[str, Any]] = None,
) -> bool:
    """Assemble PNG slide sequence into an MP4 via ffmpeg, optionally with BGM."""
    if not _check_ffmpeg():
        LOGGER.error("ffmpeg not found in PATH")
        print("[video] ERROR: ffmpeg not found. Install via: brew install ffmpeg")
        return False

    fps = int(cfg.get("yt_fps", 30))
    slide_dur = float(cfg.get("yt_slide_duration_s", 2.5))
    verdict_dur = float(cfg.get("yt_verdict_duration_s", 4.0))
    resolution = cfg.get("yt_resolution", "1920x1080")

    if len(slides) == 5:
        durations = [slide_dur] * 4 + [verdict_dur]
    else:
        durations = [slide_dur] * max(0, len(slides) - 1) + [verdict_dur]
        durations = durations[:len(slides)]

    total_dur = sum(durations)

    tmp_dir = slides[0].parent
    concat_file = tmp_dir / "concat.txt"
    with open(concat_file, "w") as f:
        for slide, dur in zip(slides, durations):
            f.write(f"file '{slide}'\n")
            f.write(f"duration {dur}\n")
        f.write(f"file '{slides[-1]}'\n")

    output_path.parent.mkdir(parents=True, exist_ok=True)

    track_path = (audio_cfg or {}).get("track_path") if audio_cfg else None
    use_audio = bool(track_path and Path(track_path).exists())

    if track_path and not Path(track_path).exists():
        LOGGER.warning("BGM track not found: %s — rendering silent", track_path)

    if use_audio:
        volume = float(audio_cfg.get("volume", 0.3))
        fade_in = float(audio_cfg.get("fade_in_s", 1.0))
        fade_out = float(audio_cfg.get("fade_out_s", 1.5))
        fade_out_start = max(0.0, total_dur - fade_out)

        audio_filter = (
            f"[0:a]volume={volume},"
            f"afade=t=in:st=0:d={fade_in},"
            f"afade=t=out:st={fade_out_start:.3f}:d={fade_out},"
            f"atrim=duration={total_dur:.3f}"
            "[aout]"
        )

        cmd = [
            "ffmpeg", "-y",
            "-stream_loop", "-1",
            "-i", str(track_path),
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
    else:
        cmd = [
            "ffmpeg", "-y",
            "-f", "concat", "-safe", "0", "-i", str(concat_file),
            "-vf", f"scale={resolution},fps={fps},format=yuv420p",
            "-c:v", "libx264", "-preset", "fast", "-crf", "18",
            str(output_path),
        ]

    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, cwd=str(tmp_dir),
        )
        if result.returncode != 0:
            LOGGER.error("ffmpeg error:\n%s", result.stderr[-500:])
            return False
        LOGGER.info("ffmpeg success: %s", output_path)
        return True
    except Exception as exc:
        LOGGER.error("ffmpeg exception: %s", exc)
        return False


# ─── Public render functions ──────────────────────────────────────────────────

def _resolve_audio_cfg(cfg: Dict[str, Any], is_episode: bool = False) -> Optional[Dict[str, Any]]:
    """Return audio config for the current render profile, or None if minimal."""
    render_cfg = cfg.get("render", {})
    profile = render_cfg.get("profile", "short")

    if profile == "minimal":
        return None

    audio_cfg = dict(cfg.get("audio", {}))
    if is_episode:
        ep_track = audio_cfg.pop("episode_track_path", None)
        if ep_track:
            audio_cfg["track_path"] = ep_track
    else:
        audio_cfg.pop("episode_track_path", None)

    return audio_cfg


def _load_episode_case_titles(db_path: str, episode: Dict[str, Any]) -> List[str]:
    """Load case file titles for the haikus in an episode."""
    import json
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
    """Render a single haiku to MP4 with optional Director's Cut BGM + casefile MD."""
    _ensure_offscreen_app()

    short_hash = (haiku.get("commit_hash") or "unknown")[:7]
    chron_idx = haiku.get("chronological_index", 0)
    branch = (haiku.get("branch") or "main").replace("/", "-")
    output_dir = Path(cfg.get("yt_output_dir", str(_REPO_ROOT / "Assets" / "YtShorts")))
    output_dir.mkdir(parents=True, exist_ok=True)

    filename = f"haiku_{chron_idx:03d}_{branch}_{short_hash}.mp4"
    output_path = output_dir / filename

    render_cfg = cfg.get("render", {})
    profile = render_cfg.get("profile", "short")
    write_md = render_cfg.get("write_casefile_md", True)
    audio_cfg = _resolve_audio_cfg(cfg, is_episode=False)

    if output_path.exists():
        LOGGER.info("Video already exists, skipping: %s", filename)
        print(f"[video] Skipping (exists): {filename}")
        return output_path

    render_w = int(cfg.get("yt_render_width", 1920))
    render_h = int(cfg.get("yt_render_height", 1080))

    bgm_name = Path(audio_cfg["track_path"]).name if audio_cfg else "silent"
    print(f"[video] Rendering haiku {chron_idx:03d} ({short_hash}) [{profile}, BGM: {bgm_name}]...")
    LOGGER.info("Rendering haiku: #%d %s profile=%s bgm=%s", chron_idx, short_hash, profile, bgm_name)

    try:
        slides = render_haiku_slides(haiku, render_w, render_h)
        success = assemble_haiku_video(slides, output_path, cfg, audio_cfg=audio_cfg)

        if success:
            print(f"[video] ✓ {filename}")
            if slides:
                shutil.rmtree(slides[0].parent, ignore_errors=True)

            # Director's Cut casefile markdown
            if write_md and profile != "minimal":
                try:
                    from codestory.render.markdown import write_cinematic_casefile
                    md_dir = output_dir / "casefiles"
                    commit = {
                        "hash": haiku.get("commit_hash", ""),
                        "msg": haiku.get("commit_msg", ""),
                        "branch": haiku.get("branch", "main"),
                        "author": haiku.get("author", ""),
                        "date": haiku.get("commit_date", ""),
                        "type": haiku.get("commit_type", "other"),
                    }
                    md_path = write_cinematic_casefile(md_dir, commit, haiku, chron_idx)
                    print(f"[video] ✍  {md_path.name}")
                    LOGGER.info("Wrote Director's Cut casefile: %s", md_path.name)
                except ImportError:
                    LOGGER.debug("render.markdown not available — skipping casefile MD")
                except Exception as exc:
                    LOGGER.warning("Casefile MD failed: %s", exc)

            return output_path
        else:
            print(f"[video] ✗ Failed: {filename}")
            return None
    except Exception as exc:
        LOGGER.error("render_haiku failed for %s: %s", short_hash, exc)
        print(f"[video] ERROR: {exc}")
        return None


def render_episode(episode: Dict[str, Any], cfg: Dict[str, Any]) -> Optional[Path]:
    """Render a single episode to a Director's Cut MP4 with 4 cinematic slides."""
    ep_num = episode.get("episode_number", 0)
    output_dir = Path(cfg.get("yt_output_dir", str(_REPO_ROOT / "Assets" / "YtShorts")))
    output_dir.mkdir(parents=True, exist_ok=True)

    filename = f"episode_{ep_num:03d}.mp4"
    output_path = output_dir / filename

    render_cfg = cfg.get("render", {})
    profile = render_cfg.get("profile", "short")
    audio_cfg = _resolve_audio_cfg(cfg, is_episode=True)

    if output_path.exists():
        LOGGER.info("Video already exists: %s", filename)
        print(f"[video] Skipping (exists): {filename}")
        return output_path

    render_w = int(cfg.get("yt_render_width", 1920))
    render_h = int(cfg.get("yt_render_height", 1080))

    bgm_name = Path(audio_cfg["track_path"]).name if audio_cfg else "silent"
    print(f"[video] Rendering episode {ep_num:03d} [{profile}, BGM: {bgm_name}]...")
    LOGGER.info("Rendering episode %d profile=%s bgm=%s", ep_num, profile, bgm_name)

    try:
        db_path = cfg.get("db_path", "")
        case_titles = _load_episode_case_titles(db_path, episode) if db_path else []
        LOGGER.info("Episode %d: %d case titles loaded", ep_num, len(case_titles))

        slides = render_episode_slides(
            episode, render_w, render_h,
            case_titles=case_titles or None,
        )

        n_slides = len(slides)
        slide_dur = float(cfg.get("yt_slide_duration_s", 2.5))
        verdict_dur = float(cfg.get("yt_verdict_duration_s", 4.0))
        episode_cfg = dict(cfg)
        episode_cfg["yt_slide_duration_s"] = slide_dur * 2.2
        episode_cfg["yt_verdict_duration_s"] = verdict_dur * 2.0

        success = assemble_haiku_video(
            slides, output_path, episode_cfg, audio_cfg=audio_cfg
        )

        if success:
            print(f"[video] ✓ {filename}  ({n_slides} slides)")
            if slides:
                shutil.rmtree(slides[0].parent, ignore_errors=True)
            return output_path

        print(f"[video] ✗ Failed: {filename}")
        return None
    except Exception as exc:
        LOGGER.error("render_episode failed for episode %d: %s", ep_num, exc)
        print(f"[video] ERROR: {exc}")
        return None


def render_all(config: Dict[str, Any]) -> List[str]:
    """Render all unrendered haikus and episodes to video."""
    LOGGER.info("Running video rendering pipeline with config: %s", config.get("db_path"))

    if not _check_ffmpeg():
        print("ERROR: ffmpeg not found. Install via: brew install ffmpeg")
        return []

    db_path = config.get("db_path", "")
    yt_dir = Path(config.get("yt_output_dir", str(_REPO_ROOT / "Assets" / "YtShorts")))
    yt_dir.mkdir(parents=True, exist_ok=True)

    # Load and filter haikus
    haikus = load_all_haikus(db_path)
    to_render = []
    for h in haikus:
        chron = h.get("chronological_index", 0)
        branch = (h.get("branch") or "main").replace("/", "-")
        short = (h.get("commit_hash") or "")[:7]
        fname = f"haiku_{chron:03d}_{branch}_{short}.mp4"
        if not (yt_dir / fname).exists():
            to_render.append(h)

    if not to_render:
        LOGGER.info("All haikus already rendered")
        return []

    print(f"[video] Rendering {len(to_render)} haiku(s)...")
    success_count = 0
    for haiku in to_render:
        result = render_haiku(haiku, config)
        if result:
            success_count += 1

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
                render_episode(ep, config)
    except sqlite3.Error as exc:
        LOGGER.error("DB error loading episodes: %s", exc)

    print(f"\n[video] Done. {success_count}/{len(to_render)} haikus rendered.")
    print(f"[video] Output directory: {yt_dir}")
    return []


# ─── CLI ──────────────────────────────────────────────────────────────────────

def main() -> int:
    """Main CLI entry point for video rendering."""
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtWidgets import QApplication
    if QApplication.instance() is None:
        QApplication([])

    parser = argparse.ArgumentParser(
        description="codeStory YouTube Shorts Pipeline"
    )
    parser.add_argument("--haiku", default=None, metavar="HASH",
                        help="Render specific commit hash")
    parser.add_argument("--episode", default=None, type=int, metavar="N",
                        help="Render specific episode number")
    parser.add_argument("--all", action="store_true",
                        help="Render all haikus and episodes")
    parser.add_argument("--max", default=None, type=int, metavar="N",
                        help="Max haikus to render")
    parser.add_argument("--db-path", default=None, metavar="PATH",
                        help="Override database path")
    parser.add_argument("--list", action="store_true",
                        help="List renderable items")
    parser.add_argument("--render-profile", choices=["minimal", "short"],
                        default=None, metavar="PROFILE")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
    )

    cfg = load_config()

    if args.db_path:
        cfg["db_path"] = args.db_path

    if args.render_profile:
        cfg.setdefault("render", {})["profile"] = args.render_profile

    if not _check_ffmpeg():
        print("ERROR: ffmpeg not found. Install via: brew install ffmpeg")
        return 1

    db_path = cfg["db_path"]

    if args.haiku:
        haiku = load_haiku_by_hash(db_path, args.haiku)
        if not haiku:
            print(f"ERROR: Haiku not found for hash '{args.haiku}'")
            return 1
        result = render_haiku(haiku, cfg)
        return 0 if result else 1

    if args.episode:
        episode = load_episode(db_path, args.episode)
        if not episode:
            print(f"ERROR: Episode {args.episode} not found")
            return 1
        result = render_episode(episode, cfg)
        return 0 if result else 1

    haikus = load_all_haikus(db_path)
    yt_dir = Path(cfg.get("yt_output_dir", str(_REPO_ROOT / "Assets" / "YtShorts")))
    yt_dir.mkdir(parents=True, exist_ok=True)

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
        print(f"[video] {len(to_render)} haiku(s) queued for rendering:")
        for h in to_render:
            print(f"  #{h.get('chronological_index', 0):03d}  {(h.get('commit_hash') or '')[:7]}  {h.get('commit_msg', '')[:60]}")
        return 0

    if not to_render:
        print("[video] All haikus already rendered. Nothing to do.")
        return 0

    render_all(cfg)
    return 0


if __name__ == "__main__":
    sys.exit(main())
