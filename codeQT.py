"""
codeQT.py — The codeStory Cinematic Viewer

PyQt6 dark-cinema interface for the codeStory haiku + episode experience.

Haiku Mode — The 3-Act Player:
  Each haiku accumulates on screen progressively as the user presses SPACE.
  Act labels ("ACT I: The Dystopian Mind") are revealed via typewriter effect.
  Act body text is revealed instantly.
  The VERDICT gets its own full-screen dramatic slide.
  Rich case-file header shows Date / Commit / Branch / Type / Author.

Episode Mode — The Case Files:
  Scrollable noir case-file layout showing all episode acts with their verdicts.

Keyboard shortcuts:
  SPACE        — Advance (next act / skip typewriter / next haiku)
  ← / →        — Navigate between haikus
  H            — Switch to Haiku mode
  E            — Switch to Episode mode
  G            — Generate new haikus (background worker)
  P            — Generate new episode (background worker)
  R            — Refresh DB data
  F            — Toggle fullscreen
  L            — Toggle ♥  heart  (stackable with ⭐ 💾)
  S            — Toggle ⭐ star   (stackable with ♥  💾)
  B            — Toggle 💾 save   (stackable with ♥  ⭐)
  Cmd + =      — Increase font size
  Cmd + -      — Decrease font size
  Cmd + 0      — Reset font size
  Q / ESC      — Quit

Usage:
    from codeQT import launch_app
    launch_app(config_dict)
"""

import enum
import json
import logging
import sqlite3
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from PyQt6.QtCore import (
    QRunnable, QTimer, Qt, QThreadPool, QObject,
    pyqtSignal, pyqtSlot,
)
from PyQt6.QtGui import QColor, QFont, QKeyEvent, QPalette, QKeySequence
from PyQt6.QtWidgets import (
    QApplication, QFrame, QHBoxLayout, QLabel, QMainWindow,
    QScrollArea, QSizePolicy,
    QStackedWidget, QVBoxLayout, QWidget,
)

LOGGER = logging.getLogger(__name__)

# ─── Colour palette ───────────────────────────────────────────────────────────
BG_DARK        = "#0a1628"
BG_CARD        = "#0d1f3c"
BG_VERDICT     = "#080f1e"
BG_META        = "#0b1a30"
DIVIDER_COL    = "#1e3a5f"
TEXT_WHITE     = "#f0f4ff"
TEXT_SUBTITLE  = "#7a9cc0"
TEXT_BODY      = "#b8cce8"
TEXT_ACT_LABEL = "#4a9eff"
TEXT_VERDICT_L = "#ff8c42"
TEXT_VERDICT_B = "#ffffff"
TEXT_HASH      = "#4a6a8a"
TEXT_META_KEY  = "#8aaccc"
TEXT_META_VAL  = "#c8ddf0"
TEXT_META_CODE = "#6abf69"
TEXT_RULING    = "#ff6b35"
TEXT_EPISODE_T = "#e8d5b7"

TYPEWRITER_INTERVAL_MS = 30

GIT_CRIME_LEXICON_DISPLAY = {
    "feat":     "Rising action — He acquired a new weapon",
    "fix":      "Damage control — The alibi was falling apart",
    "chore":    "The grind montage — Three days. No sleep. Just code.",
    "refactor": "Identity crisis — He tore it all down and rebuilt himself",
    "docs":     "The confession — He documented the crime in detail",
    "test":     "Paranoia — He built a lie detector",
    "revert":   "The flashback — He undid it. But you can't unring a bell.",
    "merge":    "The conspiracy deepens — Two worlds collided.",
    "style":    "Vanity — He polished the evidence",
    "ci":       "The system closing in — Automated judgment approached",
    "build":    "The forge — Infrastructure hammered into shape",
    "perf":     "The chase — He made it faster to avoid himself",
    "hotfix":   "2 AM damage control — Emergency. No witnesses.",
    "init":     "The origin — The first sin.",
    "wip":      "The unfinished crime — Left at the scene, half-done",
}


# ─── Font manager ─────────────────────────────────────────────────────────────

class FontManager:
    """Global font scale manager for Cmd+/- adjustability.

    Class-level state so all widgets share the same scale.
    """

    _scale: float = 1.0
    _MIN: float = 0.6
    _MAX: float = 2.0

    @classmethod
    def scale(cls, base_size: int) -> int:
        """Return a scaled font size.

        Args:
            base_size: Base point size before scaling.

        Returns:
            Scaled integer point size (minimum 8pt).
        """
        return max(8, int(base_size * cls._scale))

    @classmethod
    def increase(cls) -> None:
        """Increase font scale by 10%, capped at MAX."""
        cls._scale = min(cls._MAX, round(cls._scale + 0.1, 1))
        LOGGER.debug("Font scale increased to %.1f", cls._scale)

    @classmethod
    def decrease(cls) -> None:
        """Decrease font scale by 10%, floored at MIN."""
        cls._scale = max(cls._MIN, round(cls._scale - 0.1, 1))
        LOGGER.debug("Font scale decreased to %.1f", cls._scale)

    @classmethod
    def reset(cls) -> None:
        """Reset font scale to 1.0 (default)."""
        cls._scale = 1.0
        LOGGER.debug("Font scale reset to 1.0")

    @classmethod
    def current(cls) -> float:
        """Return the current scale factor."""
        return cls._scale


# ─── DB helpers ───────────────────────────────────────────────────────────────

class DatabaseReader:
    """Reads haiku and episode data from tmChron.db."""

    def __init__(self, db_path: str) -> None:
        """Initialise with path to tmChron.db.

        Args:
            db_path: Absolute path to the SQLite database file.
        """
        self._db_path = db_path

    def load_haikus(self) -> List[Dict[str, Any]]:
        """Load all haiku rows ordered chronologically (oldest first).

        Returns:
            List of haiku dicts. Empty list if DB missing or empty.
        """
        if not Path(self._db_path).exists():
            return []
        try:
            conn = sqlite3.connect(self._db_path)
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """SELECT * FROM haiku_commits
                   ORDER BY CASE WHEN chronological_index > 0
                            THEN chronological_index ELSE id END ASC"""
            ).fetchall()
            conn.close()
            return [dict(row) for row in rows]
        except sqlite3.OperationalError as exc:
            LOGGER.error("DB read error (haikus): %s", exc)
            return []

    def load_episodes(self) -> List[Dict[str, Any]]:
        """Load all episode rows ordered by episode_number ascending.

        Returns:
            List of episode dicts. Empty list if DB missing or empty.
        """
        if not Path(self._db_path).exists():
            return []
        try:
            conn = sqlite3.connect(self._db_path)
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM chronicle_episodes ORDER BY episode_number ASC"
            ).fetchall()
            conn.close()
            return [dict(row) for row in rows]
        except sqlite3.OperationalError as exc:
            LOGGER.error("DB read error (episodes): %s", exc)
            return []


class DatabaseWriter:
    """Handles flag toggle writes (is_hearted, is_starred, is_saved) to tmChron.db."""

    def __init__(self, db_path: str) -> None:
        """Initialise with path to tmChron.db.

        Args:
            db_path: Absolute path to the SQLite database file.
        """
        self._db_path = db_path

    def toggle_haiku_flag(self, commit_hash: str, flag: str) -> int:
        """Toggle a boolean flag on a haiku row and return the new value.

        Args:
            commit_hash: Full commit hash of the haiku.
            flag:        Column name: "is_hearted", "is_starred", or "is_saved".

        Returns:
            New flag value (0 or 1). Returns -1 on error.
        """
        if flag not in ("is_hearted", "is_starred", "is_saved"):
            LOGGER.warning("Invalid haiku flag: %s", flag)
            return -1
        try:
            conn = sqlite3.connect(self._db_path)
            row = conn.execute(
                f"SELECT {flag} FROM haiku_commits WHERE commit_hash = ?",
                (commit_hash,),
            ).fetchone()
            if row is None:
                conn.close()
                return -1
            new_val = 0 if row[0] else 1
            conn.execute(
                f"UPDATE haiku_commits SET {flag} = ? WHERE commit_hash = ?",
                (new_val, commit_hash),
            )
            conn.commit()
            conn.close()
            LOGGER.info("Haiku %s: %s = %d", commit_hash[:7], flag, new_val)
            return new_val
        except sqlite3.Error as exc:
            LOGGER.error("DB flag write error: %s", exc)
            return -1

    def toggle_episode_flag(self, episode_number: int, flag: str) -> int:
        """Toggle a boolean flag on an episode row and return the new value.

        Args:
            episode_number: Episode number.
            flag:           Column name: "is_hearted", "is_starred", or "is_saved".

        Returns:
            New flag value (0 or 1). Returns -1 on error.
        """
        if flag not in ("is_hearted", "is_starred", "is_saved"):
            LOGGER.warning("Invalid episode flag: %s", flag)
            return -1
        try:
            conn = sqlite3.connect(self._db_path)
            row = conn.execute(
                f"SELECT {flag} FROM chronicle_episodes WHERE episode_number = ?",
                (episode_number,),
            ).fetchone()
            if row is None:
                conn.close()
                return -1
            new_val = 0 if row[0] else 1
            conn.execute(
                f"UPDATE chronicle_episodes SET {flag} = ? WHERE episode_number = ?",
                (new_val, episode_number),
            )
            conn.commit()
            conn.close()
            LOGGER.info("Episode %d: %s = %d", episode_number, flag, new_val)
            return new_val
        except sqlite3.Error as exc:
            LOGGER.error("DB episode flag write error: %s", exc)
            return -1


# ─── Typewriter effect ────────────────────────────────────────────────────────

class TypewriterEffect(QObject):
    """Character-by-character text reveal via QTimer.

    Signals:
        text_updated(str): emitted after each character.
        finished():        emitted when full text has been revealed.
    """

    text_updated = pyqtSignal(str)
    finished = pyqtSignal()

    def __init__(self, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._full_text = ""
        self._current = ""
        self._pos = 0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)

    def start(self, text: str, interval_ms: int = TYPEWRITER_INTERVAL_MS) -> None:
        """Begin typewriting text.

        Args:
            text:        Full text to reveal.
            interval_ms: Milliseconds per character.
        """
        self._timer.stop()
        self._full_text = text
        self._current = ""
        self._pos = 0
        self._timer.start(interval_ms)

    def skip(self) -> None:
        """Immediately complete the animation."""
        self._timer.stop()
        self._current = self._full_text
        self._pos = len(self._full_text)
        self.text_updated.emit(self._current)
        self.finished.emit()

    def is_running(self) -> bool:
        """Return True if animation is active."""
        return self._timer.isActive()

    @pyqtSlot()
    def _tick(self) -> None:
        if self._pos < len(self._full_text):
            self._current += self._full_text[self._pos]
            self._pos += 1
            self.text_updated.emit(self._current)
        else:
            self._timer.stop()
            self.finished.emit()


# ─── Pipeline worker ──────────────────────────────────────────────────────────

class PipelineWorkerSignals(QObject):
    """Signals for PipelineWorker."""
    finished = pyqtSignal(str, int)
    error    = pyqtSignal(str, str)


class PipelineWorker(QRunnable):
    """Runs haiku or episode pipeline off the main thread.

    Args:
        pipeline: "haiku" or "episode"
        cfg:      Config dict forwarded to fetch_actions().
    """

    def __init__(self, pipeline: str, cfg: Dict[str, Any]) -> None:
        super().__init__()
        self._pipeline = pipeline
        self._cfg = cfg
        self.signals = PipelineWorkerSignals()

    @pyqtSlot()
    def run(self) -> None:
        """Execute the pipeline and emit finished or error signal."""
        try:
            if self._pipeline == "haiku":
                from git_commit_haiku import fetch_actions
            else:
                from changelog_episodes import fetch_actions
            results = fetch_actions(config=self._cfg)
            self.signals.finished.emit(self._pipeline, len(results))
        except Exception as exc:
            LOGGER.error("PipelineWorker error: %s", exc)
            self.signals.error.emit(self._pipeline, str(exc))


# ─── Label factory ────────────────────────────────────────────────────────────

def _label(
    text: str = "",
    color: str = TEXT_WHITE,
    size: int = 14,
    bold: bool = False,
    italic: bool = False,
    align: Qt.AlignmentFlag = Qt.AlignmentFlag.AlignLeft,
    word_wrap: bool = True,
    monospace: bool = False,
) -> QLabel:
    """Factory for styled, font-managed QLabel widgets.

    Args:
        text:      Initial label text.
        color:     CSS colour string.
        size:      Base point size (scaled by FontManager).
        bold:      Bold weight.
        italic:    Italic style.
        align:     Text alignment.
        word_wrap: Enable word wrap.
        monospace: Use system monospace font.

    Returns:
        Configured QLabel.
    """
    lbl = QLabel(text)
    lbl.setStyleSheet(f"color: {color}; background: transparent;")
    font = lbl.font()
    font.setPointSize(FontManager.scale(size))
    if bold:
        font.setWeight(QFont.Weight.Bold)
    font.setItalic(italic)
    if monospace:
        font.setFamily("Menlo, Monaco, Courier New, monospace")
        font.setStyleHint(QFont.StyleHint.Monospace)
    lbl.setFont(font)
    lbl.setAlignment(align)
    lbl.setWordWrap(word_wrap)
    return lbl


def _divider() -> QFrame:
    """Create a thin horizontal divider line."""
    line = QFrame()
    line.setFrameShape(QFrame.Shape.HLine)
    line.setStyleSheet(f"background-color: {DIVIDER_COL}; border: none;")
    line.setFixedHeight(1)
    return line


def _flag_badge(haiku: Dict[str, Any]) -> str:
    """Build the flags badge string for active flags.

    Args:
        haiku: Haiku dict with is_hearted, is_starred, is_saved fields.

    Returns:
        Space-separated emoji string (e.g. "⭐ ♥  💾") or "" if none.
    """
    parts = []
    if haiku.get("is_starred"):
        parts.append("⭐")
    if haiku.get("is_hearted"):
        parts.append("♥")
    if haiku.get("is_saved"):
        parts.append("💾")
    return "  ".join(parts)


# ─── Haiku state machine ─────────────────────────────────────────────────────

class HaikuState(enum.IntEnum):
    """State machine for the 3-act haiku player."""
    IDLE           = 0
    TYPING_ACT1    = 1
    ACT1_READY     = 2
    TYPING_ACT2    = 3
    ACT2_READY     = 4
    TYPING_ACT3    = 5
    ACT3_READY     = 6
    TYPING_VERDICT = 7
    VERDICT_READY  = 8


# ─── Haiku player ─────────────────────────────────────────────────────────────

class HaikuPlayerWidget(QWidget):
    """3-act haiku player — accumulates acts on screen via SPACE progression.

    Signals:
        request_verdict(dict): Emit to switch to verdict slide.
        flags_changed():       Emit after a flag is toggled (triggers meta refresh).
    """

    request_verdict = pyqtSignal(dict)
    flags_changed   = pyqtSignal()

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._haiku: Optional[Dict[str, Any]] = None
        self._state = HaikuState.IDLE
        self._typewriter = TypewriterEffect(self)
        self._typewriter.text_updated.connect(self._on_typewriter_update)
        self._typewriter.finished.connect(self._on_typewriter_done)
        self._build_ui()

    def _build_ui(self) -> None:
        """Construct the full layout: header, metadata, acts, hint bar."""
        self.setStyleSheet(f"background-color: {BG_DARK};")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # ── Scrollable content ────────────────────────────────────────────────
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet(f"background: {BG_DARK}; border: none;")
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        content = QWidget()
        content.setStyleSheet(f"background: {BG_DARK};")
        self._content = QVBoxLayout(content)
        self._content.setContentsMargins(60, 44, 60, 40)
        self._content.setSpacing(0)

        # ── Top meta row: index/hash on left, flags on right ─────────────────
        meta_row = QHBoxLayout()
        meta_row.setContentsMargins(0, 0, 0, 0)
        self._lbl_meta = _label("", TEXT_HASH, 10)
        self._lbl_flags = _label("", "#f0a040", 13,
                                  align=Qt.AlignmentFlag.AlignRight)
        meta_row.addWidget(self._lbl_meta)
        meta_row.addStretch()
        meta_row.addWidget(self._lbl_flags)
        self._content.addLayout(meta_row)
        self._content.addSpacing(8)

        # ── Case file title ───────────────────────────────────────────────────
        self._lbl_title = _label("", TEXT_WHITE, 22, bold=True)
        self._content.addWidget(self._lbl_title)

        # ── Subtitle ─────────────────────────────────────────────────────────
        self._lbl_subtitle = _label("", TEXT_SUBTITLE, 13, italic=True)
        self._lbl_subtitle.setContentsMargins(0, 4, 0, 14)
        self._content.addWidget(self._lbl_subtitle)

        # ── Metadata block (Date / Commit / Branch / Type / Author) ──────────
        meta_block = QWidget()
        meta_block.setStyleSheet(
            f"background-color: {BG_META}; border-radius: 4px; padding: 4px;"
        )
        meta_layout = QVBoxLayout(meta_block)
        meta_layout.setContentsMargins(14, 10, 14, 10)
        meta_layout.setSpacing(4)

        self._lbl_date   = self._meta_row_widget()
        self._lbl_commit = self._meta_row_widget()
        self._lbl_branch = self._meta_row_widget()
        self._lbl_type   = self._meta_row_widget()
        self._lbl_author = self._meta_row_widget()

        for w in (self._lbl_date, self._lbl_commit, self._lbl_branch,
                  self._lbl_type, self._lbl_author):
            meta_layout.addWidget(w)

        self._content.addWidget(meta_block)
        self._content.addSpacing(18)
        self._content.addWidget(_divider())
        self._content.addSpacing(22)

        # ── Acts (hidden until revealed) ──────────────────────────────────────
        self._act_widgets: List[Dict[str, QLabel]] = []
        for _ in range(3):
            lbl = _label("", TEXT_ACT_LABEL, 13, bold=True)
            lbl.setContentsMargins(0, 0, 0, 6)
            body = _label("", TEXT_BODY, 14)
            body.setContentsMargins(0, 0, 0, 26)
            lbl.hide()
            body.hide()
            self._content.addWidget(lbl)
            self._content.addWidget(body)
            self._act_widgets.append({"label": lbl, "body": body})

        self._content.addWidget(_divider())
        self._content.addStretch(1)

        scroll.setWidget(content)
        outer.addWidget(scroll)

        # ── Hint bar ─────────────────────────────────────────────────────────
        hint = QWidget()
        hint.setFixedHeight(30)
        hint.setStyleSheet(f"background: {BG_CARD};")
        hint_row = QHBoxLayout(hint)
        hint_row.setContentsMargins(20, 0, 20, 0)
        _h = _label(
            "SPACE advance   ←→ navigate   L ♥   S ⭐   B 💾   "
            "H haiku   E episodes   G generate   Cmd±font   Q quit",
            TEXT_HASH, 9, align=Qt.AlignmentFlag.AlignCenter,
        )
        hint_row.addWidget(_h)
        outer.addWidget(hint)

    def _meta_row_widget(self) -> QLabel:
        """Create a rich-text capable label for the metadata block.

        Returns:
            QLabel configured for rich-text HTML metadata display.
        """
        lbl = QLabel()
        lbl.setTextFormat(Qt.TextFormat.RichText)
        lbl.setWordWrap(True)
        lbl.setStyleSheet("background: transparent;")
        font = lbl.font()
        font.setPointSize(FontManager.scale(12))
        lbl.setFont(font)
        return lbl

    def _meta_html(self, key: str, value: str, monospace: bool = False) -> str:
        """Format a metadata key-value pair as HTML.

        Args:
            key:       Metadata field name (e.g. "Date").
            value:     Field value.
            monospace: Display value in monospace font.

        Returns:
            HTML string for display in a QLabel.
        """
        val_style = (
            f"font-family: 'Menlo', 'Monaco', monospace; color: {TEXT_META_CODE};"
            if monospace
            else f"color: {TEXT_META_VAL};"
        )
        return (
            f'<span style="color:{TEXT_META_KEY}; font-weight:bold;">{key}:</span> '
            f'<span style="{val_style}">{value}</span>'
        )

    def load_haiku(self, haiku: Dict[str, Any], index: int, total: int) -> None:
        """Load a haiku and reset to IDLE state.

        Args:
            haiku: Haiku dict from DB.
            index: 1-based position in sorted haiku list.
            total: Total haiku count.
        """
        self._haiku = haiku
        self._state = HaikuState.IDLE

        commit_hash = haiku.get("commit_hash") or haiku.get("hash", "?")
        short_hash  = commit_hash[:7]
        branch      = haiku.get("branch", "main") or "main"
        date        = (haiku.get("commit_date") or haiku.get("date", ""))[:10]
        commit_msg  = haiku.get("commit_msg") or haiku.get("commit_message", "")
        author      = haiku.get("author", "")
        commit_type = (haiku.get("commit_type") or "other").lower()
        chron_idx   = haiku.get("chronological_index", index)

        # Navigation meta
        self._lbl_meta.setText(
            f"#{chron_idx}  ·  {short_hash}  ·  {branch}  ·  {date}"
        )
        self._lbl_flags.setText(_flag_badge(haiku))

        # Title + subtitle
        self._lbl_title.setText(haiku.get("title", f"CASE FILE — {short_hash}"))
        self._lbl_subtitle.setText(haiku.get("subtitle", commit_msg[:100]))

        # Metadata block
        crime_text = GIT_CRIME_LEXICON_DISPLAY.get(commit_type, commit_type.upper())
        type_display = (
            f'<span style="color:{TEXT_META_CODE};font-family:monospace;">'
            f'{commit_type.upper()}</span>'
            f' — <span style="color:{TEXT_META_VAL};font-style:italic;">{crime_text}</span>'
        )
        self._lbl_date.setText(self._meta_html("Date", date))
        self._lbl_commit.setText(self._meta_html("Commit", commit_msg[:90], monospace=True))
        self._lbl_branch.setText(self._meta_html("Branch", f'<code style="color:{TEXT_META_CODE};">{branch}</code>'))
        self._lbl_type.setText(
            f'<span style="color:{TEXT_META_KEY};font-weight:bold;">Type:</span> {type_display}'
        )
        self._lbl_author.setText(self._meta_html("Author", author))

        # Reset acts
        for w in self._act_widgets:
            w["label"].hide()
            w["label"].setText("")
            w["body"].hide()
            w["body"].setText("")

        LOGGER.debug("HaikuPlayer loaded: #%d %s", chron_idx, short_hash)

    def refresh_flags(self) -> None:
        """Re-read flag state from current haiku and update the badge display."""
        if self._haiku:
            self._lbl_flags.setText(_flag_badge(self._haiku))

    def get_commit_hash(self) -> Optional[str]:
        """Return the current haiku's commit hash, or None."""
        return self._haiku.get("commit_hash") if self._haiku else None

    def advance(self) -> None:
        """Handle SPACE: skip typewriter if running, else advance state machine."""
        if self._typewriter.is_running():
            self._typewriter.skip()
            return

        if self._state == HaikuState.IDLE:
            self._state = HaikuState.TYPING_ACT1
            self._start_act(0)
        elif self._state == HaikuState.ACT1_READY:
            self._state = HaikuState.TYPING_ACT2
            self._start_act(1)
        elif self._state == HaikuState.ACT2_READY:
            self._state = HaikuState.TYPING_ACT3
            self._start_act(2)
        elif self._state == HaikuState.ACT3_READY:
            if self._haiku:
                self.request_verdict.emit(self._haiku)

    def _start_act(self, act_idx: int) -> None:
        """Start typewriting an act label.

        Args:
            act_idx: 0/1/2 for Acts I/II/III.
        """
        if not self._haiku:
            return
        roman = ["I", "II", "III"][act_idx]
        key   = ["act1_title", "act2_title", "act3_title"][act_idx]
        act_title = self._haiku.get(key) or ""
        text = f"ACT {roman}: {act_title}" if act_title else f"ACT {roman}"
        w = self._act_widgets[act_idx]
        w["label"].setText("")
        w["label"].show()
        self._typewriter.start(text)

    def _on_typewriter_update(self, text: str) -> None:
        """Update the active act label during typewriter animation."""
        m = {HaikuState.TYPING_ACT1: 0, HaikuState.TYPING_ACT2: 1, HaikuState.TYPING_ACT3: 2}
        idx = m.get(self._state)
        if idx is not None:
            self._act_widgets[idx]["label"].setText(text)

    def _on_typewriter_done(self) -> None:
        """Reveal act body text after typewriter completes."""
        if not self._haiku:
            return
        mapping = {
            HaikuState.TYPING_ACT1: (0, "when_where", HaikuState.ACT1_READY),
            HaikuState.TYPING_ACT2: (1, "who_whom",   HaikuState.ACT2_READY),
            HaikuState.TYPING_ACT3: (2, "what_why",   HaikuState.ACT3_READY),
        }
        m = mapping.get(self._state)
        if m:
            idx, key, next_state = m
            self._act_widgets[idx]["body"].setText(self._haiku.get(key, ""))
            self._act_widgets[idx]["body"].show()
            self._state = next_state


# ─── Verdict widget ───────────────────────────────────────────────────────────

class VerdictWidget(QWidget):
    """Full-screen verdict slide — typewriter label, then instant body reveal.

    Signals:
        finished(): SPACE after verdict → next haiku.
        go_back():  ← pressed → back to acts.
    """

    finished = pyqtSignal()
    go_back  = pyqtSignal()

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._state = HaikuState.IDLE
        self._typewriter = TypewriterEffect(self)
        self._typewriter.text_updated.connect(self._on_update)
        self._typewriter.finished.connect(self._on_done)
        self._build_ui()

    def _build_ui(self) -> None:
        """Build centred verdict panel on dark background."""
        self.setStyleSheet(f"background-color: {BG_VERDICT};")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addStretch(2)

        panel = QFrame()
        panel.setStyleSheet(
            f"background-color: {BG_CARD}; "
            f"border: 1px solid {DIVIDER_COL}; "
            "border-radius: 8px;"
        )
        panel.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        pl = QVBoxLayout(panel)
        pl.setContentsMargins(60, 50, 60, 50)
        pl.setSpacing(20)

        self._lbl_title = _label("", TEXT_VERDICT_L, 16, bold=True)
        self._lbl_body  = _label("", TEXT_VERDICT_B, 18, italic=True,
                                  align=Qt.AlignmentFlag.AlignCenter)
        self._lbl_body.hide()
        pl.addWidget(self._lbl_title)
        pl.addWidget(self._lbl_body)

        container = QHBoxLayout()
        container.setContentsMargins(80, 0, 80, 0)
        container.addWidget(panel)
        outer.addLayout(container)
        outer.addStretch(3)

        hint = QWidget()
        hint.setFixedHeight(30)
        hint.setStyleSheet(f"background: {BG_CARD};")
        hl = QHBoxLayout(hint)
        hl.setContentsMargins(20, 0, 20, 0)
        hl.addWidget(_label(
            "SPACE next haiku   ← back to acts   L ♥   S ⭐   B 💾   Q quit",
            TEXT_HASH, 9, align=Qt.AlignmentFlag.AlignCenter,
        ))
        outer.addWidget(hint)

    def show_verdict(self, haiku: Dict[str, Any]) -> None:
        """Begin verdict animation for the given haiku.

        Args:
            haiku: Haiku dict containing the verdict text.
        """
        self._state = HaikuState.TYPING_VERDICT
        self._lbl_title.setText("")
        self._lbl_body.hide()
        self._lbl_body.setText(f'"{haiku.get("verdict", "")}"')
        self._typewriter.start("🔑  VERDICT")

    def advance(self) -> None:
        """SPACE: skip typewriter or move to next haiku."""
        if self._typewriter.is_running():
            self._typewriter.skip()
        elif self._state == HaikuState.VERDICT_READY:
            self.finished.emit()

    def _on_update(self, text: str) -> None:
        self._lbl_title.setText(text)

    def _on_done(self) -> None:
        self._lbl_body.show()
        self._state = HaikuState.VERDICT_READY


# ─── Episode viewer ───────────────────────────────────────────────────────────

class EpisodeCardWidget(QFrame):
    """A single episode card in the scrollable episode viewer."""

    def __init__(self, episode: Dict[str, Any], parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._build(episode)

    def _build(self, ep: Dict[str, Any]) -> None:
        """Construct the episode card.

        Args:
            ep: Episode data dict.
        """
        self.setStyleSheet(
            f"background-color: {BG_CARD}; "
            f"border: 1px solid {DIVIDER_COL}; "
            "border-radius: 6px;"
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 26, 32, 26)
        layout.setSpacing(10)

        # Title row with flag badge
        title_row = QHBoxLayout()
        title_lbl = _label(ep.get("title", "UNTITLED"), TEXT_EPISODE_T, 17, bold=True)
        title_row.addWidget(title_lbl)
        title_row.addStretch()
        badge = _flag_badge(ep)
        if badge:
            title_row.addWidget(_label(badge, "#f0a040", 13))
        layout.addLayout(title_row)
        layout.addWidget(_divider())
        layout.addSpacing(6)

        if ep.get("decade_summary"):
            layout.addWidget(_label(ep["decade_summary"], TEXT_BODY, 13))
            layout.addSpacing(8)
        if ep.get("branch_note"):
            layout.addWidget(_label(ep["branch_note"], TEXT_SUBTITLE, 12, italic=True))
            layout.addSpacing(10)

        layout.addWidget(_divider())
        layout.addSpacing(6)
        layout.addWidget(_label("⚖  MAX'S RULING", TEXT_RULING, 11, bold=True))
        ruling = _label(f'"{ep.get("max_ruling", "")}"', TEXT_WHITE, 14, bold=True, italic=True)
        ruling.setContentsMargins(0, 4, 0, 0)
        layout.addWidget(ruling)


class EpisodeViewerWidget(QWidget):
    """Scrollable episode case-file viewer."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._build_ui()

    def _build_ui(self) -> None:
        """Build scrollable layout."""
        self.setStyleSheet(f"background-color: {BG_DARK};")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        header = QWidget()
        header.setFixedHeight(56)
        header.setStyleSheet(f"background:{BG_CARD}; border-bottom:1px solid {DIVIDER_COL};")
        hl = QHBoxLayout(header)
        hl.setContentsMargins(30, 0, 30, 0)
        self._header_lbl = _label("📜  THE CHRONICLES  —  EPISODE ACTS", TEXT_WHITE, 15, bold=True)
        hl.addWidget(self._header_lbl)
        outer.addWidget(header)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet(f"background:{BG_DARK}; border:none;")

        self._scroll_w = QWidget()
        self._scroll_w.setStyleSheet(f"background:{BG_DARK};")
        self._cards = QVBoxLayout(self._scroll_w)
        self._cards.setContentsMargins(40, 28, 40, 28)
        self._cards.setSpacing(18)
        self._cards.addStretch(1)
        scroll.setWidget(self._scroll_w)
        outer.addWidget(scroll)

        hint = QWidget()
        hint.setFixedHeight(30)
        hint.setStyleSheet(f"background:{BG_CARD};")
        hint_l = QHBoxLayout(hint)
        hint_l.setContentsMargins(20, 0, 20, 0)
        hint_l.addWidget(_label(
            "H haiku   G generate haikus   P generate episode   R refresh   Q quit",
            TEXT_HASH, 9, align=Qt.AlignmentFlag.AlignCenter,
        ))
        outer.addWidget(hint)

    def load_episodes(self, episodes: List[Dict[str, Any]]) -> None:
        """Populate the episode card list.

        Args:
            episodes: List of episode dicts from DB.
        """
        while self._cards.count() > 1:
            item = self._cards.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        if not episodes:
            self._cards.insertWidget(0, _label(
                "No episodes yet.\n\nGenerate 10+ haikus first, then press P.",
                TEXT_SUBTITLE, 14, align=Qt.AlignmentFlag.AlignCenter,
            ))
        else:
            for ep in reversed(episodes):
                self._cards.insertWidget(0, EpisodeCardWidget(ep))

        n = len(episodes)
        self._header_lbl.setText(
            f"📜  THE CHRONICLES  —  {n} EPISODE ACT{'S' if n != 1 else ''}"
        )


# ─── Empty + Loading widgets ──────────────────────────────────────────────────

class EmptyStateWidget(QWidget):
    """Shown when no haikus exist yet."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setStyleSheet(f"background:{BG_DARK};")
        l = QVBoxLayout(self)
        l.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon = _label("🎬", TEXT_WHITE, 48, align=Qt.AlignmentFlag.AlignCenter)
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        l.addWidget(icon)
        l.addSpacing(20)
        msg = _label(
            "No haikus yet.\n\nPress  G  to generate haikus from your git history.",
            TEXT_SUBTITLE, 15, align=Qt.AlignmentFlag.AlignCenter,
        )
        msg.setAlignment(Qt.AlignmentFlag.AlignCenter)
        l.addWidget(msg)
        l.addSpacing(12)
        l.addWidget(_label(
            "Make sure config.json points to your repo and llm.env has ANTHROPIC_API_KEY.",
            TEXT_HASH, 11, align=Qt.AlignmentFlag.AlignCenter,
        ))


class LoadingWidget(QWidget):
    """Overlay shown while a pipeline is generating."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setStyleSheet(f"background:{BG_DARK};")
        l = QVBoxLayout(self)
        l.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._lbl = _label("⏳  Generating...", TEXT_ACT_LABEL, 18,
                            align=Qt.AlignmentFlag.AlignCenter)
        self._lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        l.addWidget(self._lbl)
        l.addWidget(_label("MAX THE DESTROYER is at work.", TEXT_SUBTITLE, 13,
                            align=Qt.AlignmentFlag.AlignCenter))

    def set_message(self, msg: str) -> None:
        """Update loading message text.

        Args:
            msg: New status text.
        """
        self._lbl.setText(msg)


# ─── Main window ──────────────────────────────────────────────────────────────

class MainWindow(QMainWindow):
    """Top-level window managing all views and keyboard routing.

    View indices (QStackedWidget):
      0 — HaikuPlayerWidget
      1 — VerdictWidget
      2 — EpisodeViewerWidget
      3 — EmptyStateWidget
      4 — LoadingWidget
    """

    IDX_HAIKU   = 0
    IDX_VERDICT = 1
    IDX_EPISODE = 2
    IDX_EMPTY   = 3
    IDX_LOADING = 4

    def __init__(self, cfg: Dict[str, Any], start_index: Optional[int] = None) -> None:
        """Initialise the main window.

        Args:
            cfg: Full config dict (db_path required).
            start_index: Optional 0-based index to start at. If None, starts at newest haiku.
        """
        super().__init__()
        self._cfg = cfg
        self._db_reader = DatabaseReader(cfg["db_path"])
        self._db_writer = DatabaseWriter(cfg["db_path"])
        self._haikus: List[Dict[str, Any]] = []
        self._haiku_idx: int = 0
        self._start_index = start_index
        self._current_episode_number: int = 0
        self._pool = QThreadPool()
        self._build_ui()
        self._refresh_data()

    def _build_ui(self) -> None:
        """Build the main window."""
        self.setWindowTitle("codeStory — The Chronicles")
        self.setMinimumSize(900, 600)
        self.setStyleSheet(f"background:{BG_DARK};")

        self._stack = QStackedWidget()
        self._stack.setStyleSheet(f"background:{BG_DARK};")

        self._haiku_player  = HaikuPlayerWidget()
        self._verdict_w     = VerdictWidget()
        self._episode_view  = EpisodeViewerWidget()
        self._empty_w       = EmptyStateWidget()
        self._loading_w     = LoadingWidget()

        self._stack.addWidget(self._haiku_player)   # 0
        self._stack.addWidget(self._verdict_w)      # 1
        self._stack.addWidget(self._episode_view)   # 2
        self._stack.addWidget(self._empty_w)        # 3
        self._stack.addWidget(self._loading_w)      # 4

        self.setCentralWidget(self._stack)

        self._haiku_player.request_verdict.connect(self._show_verdict)
        self._verdict_w.finished.connect(self._next_haiku)
        self._verdict_w.go_back.connect(self._show_haiku_view)

    def _refresh_data(self) -> None:
        """Reload all data from DB and update views."""
        self._haikus  = self._db_reader.load_haikus()
        episodes      = self._db_reader.load_episodes()
        self._episode_view.load_episodes(episodes)

        if not self._haikus:
            self._stack.setCurrentIndex(self.IDX_EMPTY)
        else:
            # If start_index is set (from commit flow), use it; otherwise use newest haiku
            if self._start_index is not None:
                self._haiku_idx = min(self._start_index, len(self._haikus) - 1)
                self._start_index = None  # Clear after first load
            else:
                self._haiku_idx = len(self._haikus) - 1  # Start at newest
            self._load_haiku()
            self._show_haiku_view()

    def _load_haiku(self) -> None:
        """Load current haiku into the player widget."""
        if not self._haikus:
            return
        h = self._haikus[self._haiku_idx]
        self._haiku_player.load_haiku(h, self._haiku_idx + 1, len(self._haikus))

    def _show_haiku_view(self) -> None:
        self._stack.setCurrentIndex(self.IDX_HAIKU)

    def _show_verdict(self, haiku: Dict[str, Any]) -> None:
        """Switch to verdict slide and animate.

        Args:
            haiku: Haiku dict with verdict text.
        """
        self._stack.setCurrentIndex(self.IDX_VERDICT)
        self._verdict_w.show_verdict(haiku)

    def _next_haiku(self) -> None:
        """Advance to next haiku (wraps)."""
        if self._haikus:
            self._haiku_idx = (self._haiku_idx + 1) % len(self._haikus)
            self._load_haiku()
            self._show_haiku_view()

    def _prev_haiku(self) -> None:
        """Go to previous haiku (wraps)."""
        if self._haikus:
            self._haiku_idx = (self._haiku_idx - 1) % len(self._haikus)
            self._load_haiku()
            self._show_haiku_view()

    def _run_pipeline(self, pipeline: str) -> None:
        """Start a background pipeline worker.

        Args:
            pipeline: "haiku" or "episode"
        """
        self._loading_w.set_message(
            "⏳  Generating haikus..." if pipeline == "haiku" else "⏳  Generating episode..."
        )
        self._stack.setCurrentIndex(self.IDX_LOADING)
        worker = PipelineWorker(pipeline, self._cfg)
        worker.signals.finished.connect(self._on_pipeline_done)
        worker.signals.error.connect(self._on_pipeline_error)
        self._pool.start(worker)

    @pyqtSlot(str, int)
    def _on_pipeline_done(self, pipeline: str, count: int) -> None:
        """Handle pipeline success.

        Args:
            pipeline: "haiku" or "episode"
            count:    Number of items generated.
        """
        LOGGER.info("Pipeline '%s' done — %d items", pipeline, count)
        self._refresh_data()

    @pyqtSlot(str, str)
    def _on_pipeline_error(self, pipeline: str, error: str) -> None:
        """Handle pipeline error — show message and auto-recover.

        Args:
            pipeline: "haiku" or "episode"
            error:    Error message.
        """
        LOGGER.error("Pipeline '%s' error: %s", pipeline, error)
        self._loading_w.set_message(f"❌  {error[:80]}")
        QTimer.singleShot(3000, self._refresh_data)

    def _toggle_flag(self, flag: str) -> None:
        """Toggle a ♥/⭐/💾 flag on the current item (haiku or episode).

        Works in both haiku and verdict views (acts on the current haiku),
        and in episode view (acts on the first/focused episode — future refinement).

        Args:
            flag: "is_hearted", "is_starred", or "is_saved"
        """
        idx = self._stack.currentIndex()

        if idx in (self.IDX_HAIKU, self.IDX_VERDICT):
            commit_hash = self._haiku_player.get_commit_hash()
            if commit_hash and self._haikus:
                new_val = self._db_writer.toggle_haiku_flag(commit_hash, flag)
                # Update in-memory haiku dict
                self._haikus[self._haiku_idx][flag] = new_val
                self._haiku_player.refresh_flags()
                icon = {"is_hearted": "♥", "is_starred": "⭐", "is_saved": "💾"}.get(flag, "")
                status = "added" if new_val else "removed"
                LOGGER.info("Flag %s %s for haiku %s", icon, status, commit_hash[:7])

    # ── Keyboard handler ──────────────────────────────────────────────────────

    def keyPressEvent(self, event: QKeyEvent) -> None:
        """Route all keyboard shortcuts.

        Args:
            event: Qt key press event.
        """
        key  = event.key()
        mods = event.modifiers()
        idx  = self._stack.currentIndex()
        is_cmd = bool(mods & Qt.KeyboardModifier.ControlModifier)

        # ── Quit ─────────────────────────────────────────────────────────────
        if key in (Qt.Key.Key_Q, Qt.Key.Key_Escape):
            QApplication.quit()
            return

        # ── Font size (Cmd + / Cmd -) ─────────────────────────────────────────
        if is_cmd and key in (Qt.Key.Key_Equal, Qt.Key.Key_Plus):
            FontManager.increase()
            self._refresh_data()
            return
        if is_cmd and key == Qt.Key.Key_Minus:
            FontManager.decrease()
            self._refresh_data()
            return
        if is_cmd and key == Qt.Key.Key_0:
            FontManager.reset()
            self._refresh_data()
            return

        # ── Mode switches ─────────────────────────────────────────────────────
        if key == Qt.Key.Key_H and self._haikus:
            self._show_haiku_view()
            return
        if key == Qt.Key.Key_E:
            self._stack.setCurrentIndex(self.IDX_EPISODE)
            return
        if key == Qt.Key.Key_G:
            self._run_pipeline("haiku")
            return
        if key == Qt.Key.Key_P:
            self._run_pipeline("episode")
            return
        if key == Qt.Key.Key_R:
            self._refresh_data()
            return
        if key == Qt.Key.Key_F:
            self.showNormal() if self.isFullScreen() else self.showFullScreen()
            return

        # ── Flag toggles (any view) ───────────────────────────────────────────
        if key == Qt.Key.Key_L:
            self._toggle_flag("is_hearted")
            return
        if key == Qt.Key.Key_S and not is_cmd:
            self._toggle_flag("is_starred")
            return
        if key == Qt.Key.Key_B:
            self._toggle_flag("is_saved")
            return

        # ── View-specific ─────────────────────────────────────────────────────
        if idx == self.IDX_HAIKU:
            if key == Qt.Key.Key_Space:
                self._haiku_player.advance()
            elif key == Qt.Key.Key_Right:
                self._next_haiku()
            elif key == Qt.Key.Key_Left:
                self._prev_haiku()
        elif idx == self.IDX_VERDICT:
            if key == Qt.Key.Key_Space:
                self._verdict_w.advance()
            elif key == Qt.Key.Key_Left:
                self._show_haiku_view()
        else:
            if key == Qt.Key.Key_Space and self._haikus:
                self._show_haiku_view()

        super().keyPressEvent(event)


# ─── Public entry point ───────────────────────────────────────────────────────

def launch_app(cfg: Dict[str, Any]) -> int:
    """Launch the codeStory PyQt6 application in fullscreen.

    Args:
        cfg: Full config dict (db_path required).

    Returns:
        Qt application exit code.
    """
    LOGGER.info("Launching codeStory viewer (fullscreen) — db=%s", cfg.get("db_path"))

    app = QApplication.instance() or QApplication(sys.argv)

    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window,     QColor(BG_DARK))
    palette.setColor(QPalette.ColorRole.WindowText, QColor(TEXT_WHITE))
    palette.setColor(QPalette.ColorRole.Base,       QColor(BG_CARD))
    palette.setColor(QPalette.ColorRole.Text,       QColor(TEXT_BODY))
    app.setPalette(palette)

    window = MainWindow(cfg)
    window.showFullScreen()     # ← always opens fullscreen
    return app.exec()


# ─── Standalone ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import json as _json
    from pathlib import Path as _Path

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )

    _root = _Path(__file__).resolve().parent
    _cfg: Dict[str, Any] = {
        "db_path":            str(_root / "tmChron.db"),
        "output_dir":         str(_root / "Assets" / "haikuJSON"),
        "repo_path":          str(_root),
        "haiku_provider":     "anthropic",
        "haiku_model":        "claude-haiku-4-5-20251001",
        "haiku_depth":        "git_commit",
        "episode_provider":   "anthropic",
        "episode_model":      "claude-haiku-4-5-20251001",
        "episode_depth":      "git_commit",
        "max_haiku_per_run":  12,
        "haiku_per_episode":  10,
    }
    _config_path = _root / "config.json"
    try:
        with open(_config_path) as f:
            raw = _json.load(f)
        _s = raw.get("tmChronicles", {})
        for k in ("db_path", "output_dir", "repo_path"):
            if k in _s and not _Path(_s[k]).is_absolute():
                _s[k] = str(_root / _s[k])
        _cfg.update(_s)
    except (FileNotFoundError, _json.JSONDecodeError):
        pass

    sys.exit(launch_app(_cfg))
