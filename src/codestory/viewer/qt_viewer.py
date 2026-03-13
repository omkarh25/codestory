"""
PyQt6 viewer for codeStory.

Cinematic dark-cinema interface for the codeStory haiku + episode experience.
"""

import enum
import logging
import sqlite3
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from PyQt6.QtCore import (
    QRunnable, QTimer, Qt, QThreadPool, QObject,
    pyqtSignal, pyqtSlot,
)
from PyQt6.QtCore import QPropertyAnimation, QEasingCurve, pyqtProperty, QParallelAnimationGroup
from PyQt6.QtGui import QColor, QFont, QKeyEvent, QPalette
from PyQt6.QtWidgets import (
    QApplication, QFrame, QHBoxLayout, QLabel, QMainWindow,
    QScrollArea, QSizePolicy,
    QStackedWidget, QVBoxLayout, QWidget,
)

from codestory.core.logging import get_logger

LOGGER = get_logger(__name__)

# ─── Colour palette ───────────────────────────────────────────────────────────
BG_DARK = "#0a1628"
BG_CARD = "#0d1f3c"
BG_VERDICT = "#080f1e"
BG_META = "#0b1a30"
DIVIDER_COL = "#1e3a5f"
TEXT_WHITE = "#f0f4ff"
TEXT_SUBTITLE = "#7a9cc0"
TEXT_BODY = "#b8cce8"
TEXT_ACT_LABEL = "#4a9eff"
TEXT_VERDICT_L = "#ff8c42"
TEXT_VERDICT_B = "#ffffff"
TEXT_HASH = "#4a6a8a"
TEXT_META_KEY = "#8aaccc"
TEXT_META_VAL = "#c8ddf0"
TEXT_META_CODE = "#6abf69"
TEXT_RULING = "#ff6b35"
TEXT_EPISODE_T = "#e8d5b7"

TYPEWRITER_INTERVAL_MS = 30


def _get_time_period(hour: int) -> str:
    """Get time period text based on hour (24-hour format) - 3 words for drama."""
    if 5 <= hour < 8:
        return "Before Dawn"
    elif 8 <= hour < 12:
        return "Morning Light"
    elif 12 <= hour < 14:
        return "High Noon"
    elif 14 <= hour < 17:
        return "Afternoon Shadows"
    elif 17 <= hour < 20:
        return "Evening Gathers"
    elif 20 <= hour < 22:
        return "Night Falls"
    elif 22 <= hour < 24:
        return "Late Night"
    else:  # 0-5
        return "Witching Hour"


def _format_datetime(iso_date: str) -> str:
    """Format ISO date string to human-readable format with day of week and time period."""
    if not iso_date:
        return ""
    try:
        from datetime import datetime
        dt = datetime.fromisoformat(iso_date.replace(" +0530", "+05:30").replace(" +0000", "+00:00"))
        time_period = _get_time_period(dt.hour)
        time_str = dt.strftime("%I:%M %p").lower()
        return dt.strftime("%d %b %Y %a ") + f"{time_period} {time_str}"
    except Exception:
        try:
            from datetime import datetime
            dt = datetime.strptime(iso_date[:10], "%Y-%m-%d")
            return dt.strftime("%d %b %Y %a")
        except Exception:
            return iso_date[:10]


GIT_CRIME_LEXICON_DISPLAY = {
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
    "now": "The still point — Before the next crime",
}


# ─── Font manager ─────────────────────────────────────────────────────────────

class FontManager:
    """Global font scale manager for Cmd+/- adjustability."""

    _scale: float = 1.0
    _MIN: float = 0.6
    _MAX: float = 2.0

    @classmethod
    def scale(cls, base_size: int) -> int:
        return max(8, int(base_size * cls._scale))

    @classmethod
    def increase(cls) -> None:
        cls._scale = min(cls._MAX, round(cls._scale + 0.1, 1))
        LOGGER.debug("Font scale increased to %.1f", cls._scale)

    @classmethod
    def decrease(cls) -> None:
        cls._scale = max(cls._MIN, round(cls._scale - 0.1, 1))
        LOGGER.debug("Font scale decreased to %.1f", cls._scale)

    @classmethod
    def reset(cls) -> None:
        cls._scale = 1.0
        LOGGER.debug("Font scale reset to 1.0")

    @classmethod
    def current(cls) -> float:
        return cls._scale


# ─── DB helpers ───────────────────────────────────────────────────────────────

class DatabaseReader:
    """Reads haiku and episode data from the database."""

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path

    def load_haikus(self) -> List[Dict[str, Any]]:
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

    def load_moments(self) -> List[Dict[str, Any]]:
        """Load all Now moments ordered by capture time (oldest first)."""
        if not Path(self._db_path).exists():
            return []
        try:
            conn = sqlite3.connect(self._db_path)
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM now_moments ORDER BY captured_at ASC"
            ).fetchall()
            conn.close()
            return [dict(row) for row in rows]
        except sqlite3.OperationalError as exc:
            LOGGER.error("DB read error (moments): %s", exc)
            return []


class DatabaseWriter:
    """Handles flag toggle writes to the database."""

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path

    def toggle_haiku_flag(self, commit_hash: str, flag: str) -> int:
        if flag not in ("is_hearted", "is_starred", "is_saved"):
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
        if flag not in ("is_hearted", "is_starred", "is_saved"):
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

    def toggle_moment_flag(self, moment_id: int, flag: str) -> int:
        """Toggle a flag on a Now moment row."""
        if flag not in ("is_hearted", "is_starred", "is_saved"):
            return -1
        try:
            conn = sqlite3.connect(self._db_path)
            row = conn.execute(
                f"SELECT {flag} FROM now_moments WHERE id = ?",
                (moment_id,),
            ).fetchone()
            if row is None:
                conn.close()
                return -1
            new_val = 0 if row[0] else 1
            conn.execute(
                f"UPDATE now_moments SET {flag} = ? WHERE id = ?",
                (new_val, moment_id),
            )
            conn.commit()
            conn.close()
            LOGGER.info("Moment %d: %s = %d", moment_id, flag, new_val)
            return new_val
        except sqlite3.Error as exc:
            LOGGER.error("DB moment flag write error: %s", exc)
            return -1


# ─── Typewriter effect ────────────────────────────────────────────────────────

class TypewriterEffect(QObject):
    """Character-by-character text reveal via QTimer."""

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
        self._timer.stop()
        self._full_text = text
        self._current = ""
        self._pos = 0
        self._timer.start(interval_ms)

    def skip(self) -> None:
        self._timer.stop()
        self._current = self._full_text
        self._pos = len(self._full_text)
        self.text_updated.emit(self._current)
        self.finished.emit()

    def is_running(self) -> bool:
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
    finished = pyqtSignal(str, int)
    error = pyqtSignal(str, str)


class PipelineWorker(QRunnable):
    """Runs haiku or episode pipeline off the main thread."""

    def __init__(self, pipeline: str, cfg: Dict[str, Any]) -> None:
        super().__init__()
        self._pipeline = pipeline
        self._cfg = cfg
        self.signals = PipelineWorkerSignals()

    @pyqtSlot()
    def run(self) -> None:
        try:
            if self._pipeline == "haiku":
                from codestory.pipeline.haiku import generate_haikus
            else:
                from codestory.pipeline.episode import generate_episodes
            
            results = generate_haikus(config=self._cfg) if self._pipeline == "haiku" else generate_episodes(config=self._cfg)
            self.signals.finished.emit(self._pipeline, len(results))
        except Exception as exc:
            LOGGER.error("PipelineWorker error: %s", exc)
            self.signals.error.emit(self._pipeline, str(exc))


# ─── Label factory ───────────────────────────────────────────────────────────

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
    """Factory for styled, font-managed QLabel widgets."""
    lbl = QLabel(text)
    lbl.setStyleSheet(f"color: {color}; background: transparent;")
    font = lbl.font()
    font.setPointSize(FontManager.scale(size))
    if bold:
        font.setWeight(QFont.Weight.Bold)
    font.setItalic(italic)
    if monospace:
        font.setFamilies(["Menlo", "Monaco", "Courier New", "monospace"])
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
    """Build the flags badge string for active flags."""
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
    IDLE = 0
    TYPING_ACT1 = 1
    ACT1_READY = 2
    TYPING_ACT2 = 3
    ACT2_READY = 4
    TYPING_ACT3 = 5
    ACT3_READY = 6
    TYPING_VERDICT = 7
    VERDICT_READY = 8


# ─── Haiku player ─────────────────────────────────────────────────────────────

class HaikuPlayerWidget(QWidget):
    """3-act haiku player — accumulates acts on screen via SPACE progression."""

    request_verdict = pyqtSignal(dict)
    flags_changed = pyqtSignal()

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._haiku: Optional[Dict[str, Any]] = None
        self._state = HaikuState.IDLE
        self._typewriter = TypewriterEffect(self)
        self._typewriter.text_updated.connect(self._on_typewriter_update)
        self._typewriter.finished.connect(self._on_typewriter_done)
        self._build_ui()

    def _build_ui(self) -> None:
        self.setStyleSheet(f"background-color: {BG_DARK};")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet(f"background: {BG_DARK}; border: none;")
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        scroll.verticalScrollBar().setFocusPolicy(Qt.FocusPolicy.NoFocus)

        content = QWidget()
        content.setStyleSheet(f"background: {BG_DARK};")
        content.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._content = QVBoxLayout(content)
        self._content.setContentsMargins(60, 44, 60, 40)
        self._content.setSpacing(0)

        # Meta row
        meta_row = QHBoxLayout()
        meta_row.setContentsMargins(0, 0, 0, 0)
        self._lbl_meta = _label("", TEXT_HASH, 10)
        self._lbl_flags = _label("", "#f0a040", 13, align=Qt.AlignmentFlag.AlignRight)
        meta_row.addWidget(self._lbl_meta)
        meta_row.addStretch()
        meta_row.addWidget(self._lbl_flags)
        self._content.addLayout(meta_row)
        self._content.addSpacing(8)

        # Title
        self._lbl_title = _label("", TEXT_WHITE, 22, bold=True)
        self._content.addWidget(self._lbl_title)

        # Subtitle
        self._lbl_subtitle = _label("", TEXT_SUBTITLE, 13, italic=True)
        self._lbl_subtitle.setContentsMargins(0, 4, 0, 14)
        self._content.addWidget(self._lbl_subtitle)

        # Metadata block
        meta_block = QWidget()
        meta_block.setStyleSheet(f"background-color: {BG_META}; border-radius: 4px; padding: 4px;")
        meta_layout = QVBoxLayout(meta_block)
        meta_layout.setContentsMargins(14, 10, 14, 10)
        meta_layout.setSpacing(4)

        self._lbl_date = self._meta_row_widget()
        self._lbl_commit = self._meta_row_widget()
        self._lbl_branch = self._meta_row_widget()
        self._lbl_type = self._meta_row_widget()
        self._lbl_author = self._meta_row_widget()

        for w in (self._lbl_date, self._lbl_commit, self._lbl_branch, self._lbl_type, self._lbl_author):
            meta_layout.addWidget(w)

        self._content.addWidget(meta_block)
        self._content.addSpacing(18)
        self._content.addWidget(_divider())
        self._content.addSpacing(22)

        # Acts
        self._act_widgets: List[Dict[str, QLabel]] = []
        for _ in range(3):
            lbl = _label("", TEXT_ACT_LABEL, 13, bold=True)
            lbl.setContentsMargins(0, 0, 0, 6)
            body = QLabel()
            body.setTextFormat(Qt.TextFormat.RichText)
            body.setWordWrap(True)
            body.setStyleSheet(
                f"color: {TEXT_BODY}; background: transparent; "
                "padding-left: 14px; "
                f"border-left: 3px solid {DIVIDER_COL};"
            )
            font = body.font()
            font.setPointSize(FontManager.scale(14))
            body.setFont(font)
            body.setContentsMargins(0, 4, 0, 26)
            lbl.hide()
            body.hide()
            self._content.addWidget(lbl)
            self._content.addWidget(body)
            self._act_widgets.append({"label": lbl, "body": body})

        self._content.addWidget(_divider())
        self._content.addStretch(1)

        scroll.setWidget(content)
        outer.addWidget(scroll)

        # Hint bar
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
        lbl = QLabel()
        lbl.setTextFormat(Qt.TextFormat.RichText)
        lbl.setWordWrap(True)
        lbl.setStyleSheet("background: transparent;")
        font = lbl.font()
        font.setPointSize(FontManager.scale(12))
        lbl.setFont(font)
        return lbl

    def _meta_html(self, key: str, value: str, monospace: bool = False) -> str:
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
        self._haiku = haiku
        self._state = HaikuState.IDLE

        commit_hash = haiku.get("commit_hash") or haiku.get("hash", "?")
        short_hash = commit_hash[:7]
        branch = haiku.get("branch", "main") or "main"
        raw_date = haiku.get("commit_date") or haiku.get("date", "")
        date = _format_datetime(raw_date)
        commit_msg = haiku.get("commit_msg") or haiku.get("commit_message", "")
        author = haiku.get("author", "")
        commit_type = (haiku.get("commit_type") or "other").lower()
        chron_idx = haiku.get("chronological_index", index)

        self._lbl_meta.setText(f"Case {chron_idx} of {total}  ·  {short_hash}  ·  {branch}  ·  {date}")
        self._lbl_flags.setText(_flag_badge(haiku))

        self._lbl_title.setText(haiku.get("title", f"CASE FILE — {short_hash}"))
        self._lbl_subtitle.setText(haiku.get("subtitle", commit_msg[:100]))

        crime_text = GIT_CRIME_LEXICON_DISPLAY.get(commit_type, commit_type.upper())
        type_display = (
            f'<span style="color:{TEXT_META_CODE};font-family:monospace;">{commit_type.upper()}</span>'
            f' — <span style="color:{TEXT_META_VAL};font-style:italic;">{crime_text}</span>'
        )
        self._lbl_date.setText(self._meta_html("Date", date))
        self._lbl_commit.setText(self._meta_html("Commit", commit_msg[:90], monospace=True))
        self._lbl_branch.setText(self._meta_html("Branch", f'<code style="color:{TEXT_META_CODE};">{branch}</code>'))
        self._lbl_type.setText(f'<span style="color:{TEXT_META_KEY};font-weight:bold;">Type:</span> {type_display}')
        self._lbl_author.setText(self._meta_html("Author", author))

        for w in self._act_widgets:
            w["label"].hide()
            w["label"].setText("")
            w["body"].hide()
            w["body"].setText("")

        LOGGER.debug("HaikuPlayer loaded: #%d %s", chron_idx, short_hash)

    def refresh_flags(self) -> None:
        if self._haiku:
            self._lbl_flags.setText(_flag_badge(self._haiku))

    def get_commit_hash(self) -> Optional[str]:
        return self._haiku.get("commit_hash") if self._haiku else None

    def advance(self) -> None:
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
        if not self._haiku:
            return
        roman = ["I", "II", "III"][act_idx]
        key = ["act1_title", "act2_title", "act3_title"][act_idx]
        act_title = self._haiku.get(key) or ""
        text = f"ACT {roman}: {act_title}" if act_title else f"ACT {roman}"
        w = self._act_widgets[act_idx]
        w["label"].setText("")
        w["label"].show()
        self._typewriter.start(text)

    def _on_typewriter_update(self, text: str) -> None:
        m = {HaikuState.TYPING_ACT1: 0, HaikuState.TYPING_ACT2: 1, HaikuState.TYPING_ACT3: 2}
        idx = m.get(self._state)
        if idx is not None:
            self._act_widgets[idx]["label"].setText(text)

    @staticmethod
    def _act_body_html(text: str) -> str:
        import html
        if not text:
            return ""
        escaped = html.escape(text)
        paragraphs = escaped.split("\n\n") if "\n\n" in escaped else [escaped]
        parts = []
        for para in paragraphs:
            para = para.replace("\n", "<br/>")
            parts.append(f'<p style="margin:0 0 10px 0; line-height:1.7;">{para}</p>')
        body_html = "".join(parts)
        return (
            f'<span style="font-size:{FontManager.scale(14)}pt; color:{TEXT_BODY}; line-height:1.7;">'
            f'{body_html}</span>'
        )

    def _on_typewriter_done(self) -> None:
        if not self._haiku:
            return
        mapping = {
            HaikuState.TYPING_ACT1: (0, "when_where", HaikuState.ACT1_READY),
            HaikuState.TYPING_ACT2: (1, "who_whom", HaikuState.ACT2_READY),
            HaikuState.TYPING_ACT3: (2, "what_why", HaikuState.ACT3_READY),
        }
        m = mapping.get(self._state)
        if m:
            idx, key, next_state = m
            raw_text = self._haiku.get(key, "")
            self._act_widgets[idx]["body"].setText(self._act_body_html(raw_text))
            self._act_widgets[idx]["body"].show()
            self._state = next_state


# ─── Verdict widget ───────────────────────────────────────────────────────────

class VerdictWidget(QWidget):
    """Full-screen verdict slide."""

    finished = pyqtSignal()
    go_back = pyqtSignal()

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._state = HaikuState.IDLE
        self._typewriter = TypewriterEffect(self)
        self._typewriter.text_updated.connect(self._on_update)
        self._typewriter.finished.connect(self._on_done)
        self._build_ui()

    def _build_ui(self) -> None:
        self.setStyleSheet(f"background-color: {BG_VERDICT};")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addStretch(2)

        panel = QFrame()
        panel.setStyleSheet(
            f"background-color: {BG_CARD}; border: 1px solid {DIVIDER_COL}; border-radius: 8px;"
        )
        panel.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        pl = QVBoxLayout(panel)
        pl.setContentsMargins(60, 50, 60, 50)
        pl.setSpacing(20)

        self._lbl_title = _label("", TEXT_VERDICT_L, 16, bold=True)
        self._lbl_body = _label("", TEXT_VERDICT_B, 18, italic=True, align=Qt.AlignmentFlag.AlignCenter)
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
        self._state = HaikuState.TYPING_VERDICT
        self._lbl_title.setText("")
        self._lbl_body.hide()
        self._lbl_body.setText(f'"{haiku.get("verdict", "")}"')
        self._typewriter.start("🔑  VERDICT")

    def advance(self) -> None:
        if self._typewriter.is_running():
            self._typewriter.skip()
        elif self._state == HaikuState.VERDICT_READY:
            self.finished.emit()

    def _on_update(self, text: str) -> None:
        self._lbl_title.setText(text)

    def _on_done(self) -> None:
        self._lbl_body.show()
        self._state = HaikuState.VERDICT_READY


# ─── Dolly Zoom Verdict for Now Moments ───────────────────────────────────────

class DollyZoomVerdict(QWidget):
    """
    Full-screen verdict slide with dolly zoom effect for Now Moments.

    The dolly zoom (Vertigo effect) creates a sense of cosmic expansion:
    - Letter spacing increases (text stretches apart)
    - Container margins expand outward (space breathes)
    - Font size grows dramatically (18pt → 28pt) for impact
    - Italic fades to bold weight for final punch
    
    This gives the "still point" moment that cosmic, transcendent feel.
    """

    finished = pyqtSignal()
    go_back = pyqtSignal()

    # Tuning parameters for cinematic effect
    LETTER_SPACING_END = 8.0
    CONTAINER_SCALE_END = 2.5
    FONT_SIZE_START = 18
    FONT_SIZE_END = 28
    ANIMATION_DURATION_MS = 1800
    PAUSE_BEFORE_ZOOM_MS = 300

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._state = HaikuState.IDLE
        self._typewriter = TypewriterEffect(self)
        self._typewriter.text_updated.connect(self._on_typewriter_update)
        self._typewriter.finished.connect(self._on_typewriter_done)
        
        # Dolly zoom animatable properties
        self._letter_spacing = 0.0
        self._container_scale = 1.0
        self._verdict_font_size = self.FONT_SIZE_START
        
        self._build_ui()

    def _build_ui(self) -> None:
        self.setStyleSheet(f"background-color: {BG_VERDICT};")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addStretch(2)

        panel = QFrame()
        panel.setObjectName("verdict_panel")
        panel.setStyleSheet(
            f"background-color: {BG_CARD}; border: 1px solid {DIVIDER_COL}; border-radius: 8px;"
        )
        panel.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._panel = panel
        pl = QVBoxLayout(panel)
        pl.setContentsMargins(60, 50, 60, 50)
        pl.setSpacing(20)
        self._panel_layout = pl

        self._lbl_title = _label("", TEXT_VERDICT_L, 16, bold=True)
        # Start italic, will animate to bold
        self._lbl_body = _label("", TEXT_VERDICT_B, self.FONT_SIZE_START, italic=True, align=Qt.AlignmentFlag.AlignCenter)
        self._lbl_body.hide()
        pl.addWidget(self._lbl_title)
        pl.addWidget(self._lbl_body)

        container = QHBoxLayout()
        container.setContentsMargins(80, 0, 80, 0)
        self._container_layout = container
        container.addWidget(panel)
        outer.addLayout(container)
        outer.addStretch(3)

        hint = QWidget()
        hint.setFixedHeight(30)
        hint.setStyleSheet(f"background: {BG_CARD};")
        hl = QHBoxLayout(hint)
        hl.setContentsMargins(20, 0, 20, 0)
        hl.addWidget(_label(
            "SPACE next moment   ← back to acts   L ♥   S ⭐   B 💾   Q quit",
            TEXT_HASH, 9, align=Qt.AlignmentFlag.AlignCenter,
        ))
        outer.addWidget(hint)

    # --- Animatable property: letter spacing ---
    def get_letter_spacing(self) -> float:
        return self._letter_spacing

    def set_letter_spacing(self, value: float) -> None:
        self._letter_spacing = value
        font = self._lbl_body.font()
        font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, value)
        self._lbl_body.setFont(font)

    letterSpacing = pyqtProperty(float, get_letter_spacing, set_letter_spacing)

    # --- Animatable property: container scale ---
    def get_container_scale(self) -> float:
        return self._container_scale

    def set_container_scale(self, value: float) -> None:
        self._container_scale = value
        # Margins expand outward
        margin = int(80 * value)
        self._container_layout.setContentsMargins(margin, 0, margin, 0)

    containerScale = pyqtProperty(float, get_container_scale, set_container_scale)

    # --- Animatable property: verdict font size ---
    def get_verdict_font_size(self) -> int:
        return self._verdict_font_size

    def set_verdict_font_size(self, value: int) -> None:
        self._verdict_font_size = value
        font = self._lbl_body.font()
        font.setPointSize(value)
        # Transition from italic to bold as size grows
        if value >= self.FONT_SIZE_END:
            font.setItalic(False)
            font.setWeight(QFont.Weight.Bold)
        else:
            font.setItalic(True)
            font.setWeight(QFont.Weight.Normal)
        self._lbl_body.setFont(font)

    verdictFontSize = pyqtProperty(int, get_verdict_font_size, set_verdict_font_size)

    def _play_dolly_zoom(self) -> None:
        """Play the dolly zoom animation."""
        # Letter spacing: 0 → 8 (text stretches apart)
        anim_spacing = QPropertyAnimation(self, b"letterSpacing")
        anim_spacing.setDuration(self.ANIMATION_DURATION_MS)
        anim_spacing.setStartValue(0.0)
        anim_spacing.setEndValue(self.LETTER_SPACING_END)
        anim_spacing.setEasingCurve(QEasingCurve.Type.OutCubic)

        # Container: 1.0 → 2.5 (space expands outward)
        anim_scale = QPropertyAnimation(self, b"containerScale")
        anim_scale.setDuration(self.ANIMATION_DURATION_MS)
        anim_scale.setStartValue(1.0)
        anim_scale.setEndValue(self.CONTAINER_SCALE_END)
        anim_scale.setEasingCurve(QEasingCurve.Type.OutCubic)

        # Font size: 18 → 28 (grows for dramatic impact)
        anim_font = QPropertyAnimation(self, b"verdictFontSize")
        anim_font.setDuration(self.ANIMATION_DURATION_MS)
        anim_font.setStartValue(self.FONT_SIZE_START)
        anim_font.setEndValue(self.FONT_SIZE_END)
        anim_font.setEasingCurve(QEasingCurve.Type.OutCubic)

        # Run all simultaneously
        self._dolly_group = QParallelAnimationGroup()
        self._dolly_group.addAnimation(anim_spacing)
        self._dolly_group.addAnimation(anim_scale)
        self._dolly_group.addAnimation(anim_font)
        self._dolly_group.start()
        LOGGER.debug("Dolly zoom started for Now moment verdict (font 18->28, italic->bold)")

    def show_verdict(self, haiku: Dict[str, Any]) -> None:
        """Show the verdict with typewriter, then dolly zoom."""
        # Reset dolly zoom state
        self._letter_spacing = 0.0
        self._container_scale = 1.0
        self._verdict_font_size = self.FONT_SIZE_START
        self._container_layout.setContentsMargins(80, 0, 80, 0)
        
        # Reset font to italic small
        font = self._lbl_body.font()
        font.setPointSize(self.FONT_SIZE_START)
        font.setItalic(True)
        font.setWeight(QFont.Weight.Normal)
        self._lbl_body.setFont(font)
        
        self._state = HaikuState.TYPING_VERDICT
        self._lbl_title.setText("")
        self._lbl_body.hide()
        self._lbl_body.setText(f'"{haiku.get("verdict", "")}"')
        self._typewriter.start("🔑  VERDICT")

    def advance(self) -> None:
        if self._typewriter.is_running():
            self._typewriter.skip()
        elif self._state == HaikuState.VERDICT_READY:
            self.finished.emit()

    def _on_typewriter_update(self, text: str) -> None:
        self._lbl_title.setText(text)

    def _on_typewriter_done(self) -> None:
        """After typewriter finishes, show body then trigger dolly zoom after pause."""
        self._lbl_body.show()
        self._state = HaikuState.VERDICT_READY
        # Trigger dolly zoom after brief pause for cinematic effect
        QTimer.singleShot(self.PAUSE_BEFORE_ZOOM_MS, self._play_dolly_zoom)



# ─── Episode viewer ───────────────────────────────────────────────────────────


class EpisodeCardWidget(QFrame):
    """A single episode card in the scrollable episode viewer."""

    def __init__(self, episode: Dict[str, Any], parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._build(episode)

    def _build(self, ep: Dict[str, Any]) -> None:
        self.setStyleSheet(
            f"background-color: {BG_CARD}; border: 1px solid {DIVIDER_COL}; border-radius: 6px;"
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 26, 32, 26)
        layout.setSpacing(10)

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
        self._lbl = _label("⏳  Generating...", TEXT_ACT_LABEL, 18, align=Qt.AlignmentFlag.AlignCenter)
        self._lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        l.addWidget(self._lbl)
        l.addWidget(_label("MAX THE DESTROYER is at work.", TEXT_SUBTITLE, 13, align=Qt.AlignmentFlag.AlignCenter))

    def set_message(self, msg: str) -> None:
        self._lbl.setText(msg)


# ─── Moment adapter ───────────────────────────────────────────────────────────

def _adapt_moment_to_haiku(moment: Dict[str, Any]) -> Dict[str, Any]:
    """
    Adapt a now_moments row into a haiku-compatible dict for HaikuPlayerWidget.

    Maps moment fields so the existing 3-act player renders them unchanged.
    Uses a 'moment:<id>' fake commit_hash to route flag operations correctly.

    Args:
        moment: Row dict from now_moments table.

    Returns:
        Haiku-compatible dict loadable by HaikuPlayerWidget.load_haiku().
    """
    moment_id = moment.get("id", 0)
    return {
        "commit_hash":        f"moment:{moment_id}",   # Routed to toggle_moment_flag
        "short_hash":         f"⚡{moment_id:04d}",
        "commit_type":        "now",
        "commit_msg":         moment.get("subtitle", ""),
        "branch":             "⚡ now",
        "author":             "MAX THE DESTROYER",
        "commit_date":        moment.get("captured_at", ""),
        "chronological_index": moment_id,
        "title":              moment.get("title", f"NOW — Moment {moment_id}"),
        "subtitle":           moment.get("subtitle", ""),
        "act1_title":         moment.get("act1_title", ""),
        "when_where":         moment.get("when_where", ""),
        "act2_title":         moment.get("act2_title", ""),
        "who_whom":           moment.get("who_whom", ""),
        "act3_title":         moment.get("act3_title", ""),
        "what_why":           moment.get("what_why", ""),
        "verdict":            moment.get("verdict", ""),
        "is_hearted":         moment.get("is_hearted", 0),
        "is_starred":         moment.get("is_starred", 0),
        "is_saved":           moment.get("is_saved", 0),
        # Keep original ID for flag writes
        "_moment_id":         moment_id,
    }


# ─── Main window ──────────────────────────────────────────────────────────────

class MainWindow(QMainWindow):
    """
    Top-level window managing all views and keyboard routing.

    Supports three primary viewing modes:
    - Haiku chronicle  (H key) — IDX_HAIKU / IDX_VERDICT
    - Episode acts     (E key) — IDX_EPISODE
    - Now moments      (N key) — IDX_MOMENTS / IDX_MOMENTS_VERDICT
    """

    IDX_HAIKU = 0
    IDX_VERDICT = 1
    IDX_EPISODE = 2
    IDX_EMPTY = 3
    IDX_LOADING = 4
    IDX_MOMENTS = 5
    IDX_MOMENTS_VERDICT = 6

    def __init__(
        self,
        cfg: Dict[str, Any],
        start_index: Optional[int] = None,
        start_moment_id: Optional[int] = None,
    ) -> None:
        """
        Initialise the main window.

        Args:
            cfg: Full codeStory config dict.
            start_index: Optional haiku index to open at launch.
            start_moment_id: Optional moment DB id to open at launch (triggers moments mode).
        """
        super().__init__()
        self._cfg = cfg
        self._db_reader = DatabaseReader(cfg["db_path"])
        self._db_writer = DatabaseWriter(cfg["db_path"])

        # Haiku state
        self._haikus: List[Dict[str, Any]] = []
        self._haiku_idx: int = 0
        self._start_index = start_index

        # Moments state
        self._moments: List[Dict[str, Any]] = []
        self._moment_idx: int = 0
        self._start_moment_id = start_moment_id

        self._current_episode_number: int = 0
        self._pool = QThreadPool()
        self._build_ui()
        self._refresh_data()

    def _build_ui(self) -> None:
        """Build the QStackedWidget with all viewer panels."""
        self.setWindowTitle("codeStory — The Chronicles")
        self.setMinimumSize(900, 600)
        self.setStyleSheet(f"background:{BG_DARK};")
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        self._stack = QStackedWidget()
        self._stack.setStyleSheet(f"background:{BG_DARK};")

        # Haiku panels (indices 0, 1)
        self._haiku_player = HaikuPlayerWidget()
        self._verdict_w = VerdictWidget()

        # Shared panels (indices 2–4)
        self._episode_view = EpisodeViewerWidget()
        self._empty_w = EmptyStateWidget()
        self._loading_w = LoadingWidget()

        # Moments panels (indices 5, 6) — separate player to avoid state conflicts
        self._moments_player = HaikuPlayerWidget()
        self._moments_verdict_w = DollyZoomVerdict()  # Cosmi


        for widget in (
            self._haiku_player,      # 0
            self._verdict_w,         # 1
            self._episode_view,      # 2
            self._empty_w,           # 3
            self._loading_w,         # 4
            self._moments_player,    # 5
            self._moments_verdict_w, # 6
        ):
            self._stack.addWidget(widget)

        self.setCentralWidget(self._stack)

        # Haiku wiring
        self._haiku_player.request_verdict.connect(self._show_verdict)
        self._verdict_w.finished.connect(self._next_haiku)
        self._verdict_w.go_back.connect(self._show_haiku_view)

        # Moments wiring
        self._moments_player.request_verdict.connect(self._show_moment_verdict)
        self._moments_verdict_w.finished.connect(self._next_moment)
        self._moments_verdict_w.go_back.connect(self._show_moment_view)

    def _refresh_data(self) -> None:
        """Reload all data from the DB and update all views."""
        self._haikus = self._db_reader.load_haikus()
        self._moments = self._db_reader.load_moments()
        episodes = self._db_reader.load_episodes()
        self._episode_view.load_episodes(episodes)

        LOGGER.info(
            "Refreshed: %d haikus, %d moments, %d episodes",
            len(self._haikus), len(self._moments), len(episodes),
        )

        # If launched via --now, go straight to moments view
        if self._start_moment_id is not None:
            target_id = self._start_moment_id
            self._start_moment_id = None
            # Find the moment's index by id
            for i, m in enumerate(self._moments):
                if m.get("id") == target_id:
                    self._moment_idx = i
                    break
            else:
                self._moment_idx = max(0, len(self._moments) - 1)

            if self._moments:
                self._load_moment()
                self._show_moment_view()
                return

        # Default: show haiku view (or empty state)
        if not self._haikus:
            self._stack.setCurrentIndex(self.IDX_EMPTY)
        else:
            if self._start_index is not None:
                self._haiku_idx = min(self._start_index, len(self._haikus) - 1)
                self._start_index = None
            else:
                self._haiku_idx = len(self._haikus) - 1
            self._load_haiku()
            self._show_haiku_view()

    # ── Haiku navigation ──────────────────────────────────────────────────────

    def _load_haiku(self) -> None:
        """Load the current haiku into the player widget."""
        if not self._haikus:
            return
        h = self._haikus[self._haiku_idx]
        self._haiku_player.load_haiku(h, self._haiku_idx + 1, len(self._haikus))

    def _show_haiku_view(self) -> None:
        """Switch stack to the haiku player panel."""
        self._stack.setCurrentIndex(self.IDX_HAIKU)
        self.setFocus()

    def _show_verdict(self, haiku: Dict[str, Any]) -> None:
        """Show the verdict screen for a haiku."""
        self._stack.setCurrentIndex(self.IDX_VERDICT)
        self._verdict_w.show_verdict(haiku)

    def _next_haiku(self, step: int = 1) -> None:
        """Advance to the next haiku (wraps around)."""
        if self._haikus:
            self._haiku_idx = (self._haiku_idx + step) % len(self._haikus)
            self._load_haiku()
            self._show_haiku_view()

    def _prev_haiku(self, step: int = 1) -> None:
        """Go back to the previous haiku (wraps around)."""
        if self._haikus:
            self._haiku_idx = (self._haiku_idx - step) % len(self._haikus)
            self._load_haiku()
            self._show_haiku_view()

    # ── Moments navigation ────────────────────────────────────────────────────

    def _load_moment(self) -> None:
        """Adapt the current moment and load it into the moments player."""
        if not self._moments:
            return
        m = self._moments[self._moment_idx]
        adapted = _adapt_moment_to_haiku(m)
        self._moments_player.load_haiku(adapted, self._moment_idx + 1, len(self._moments))
        LOGGER.debug("Moments player loaded: idx=%d id=%s", self._moment_idx, m.get("id"))

    def _show_moment_view(self) -> None:
        """Switch stack to the moments player panel."""
        self._stack.setCurrentIndex(self.IDX_MOMENTS)
        self.setFocus()

    def _show_moment_verdict(self, haiku: Dict[str, Any]) -> None:
        """Show the verdict screen for the current moment."""
        self._stack.setCurrentIndex(self.IDX_MOMENTS_VERDICT)
        self._moments_verdict_w.show_verdict(haiku)

    def _next_moment(self, step: int = 1) -> None:
        """Advance to the next Now moment (wraps around)."""
        if self._moments:
            self._moment_idx = (self._moment_idx + step) % len(self._moments)
            self._load_moment()
            self._show_moment_view()

    def _prev_moment(self, step: int = 1) -> None:
        """Go back to the previous Now moment (wraps around)."""
        if self._moments:
            self._moment_idx = (self._moment_idx - step) % len(self._moments)
            self._load_moment()
            self._show_moment_view()

    def _enter_moments_mode(self) -> None:
        """Switch to the Now moments view. Loads most recent moment if none active."""
        if not self._moments:
            LOGGER.info("No moments yet — run 'codestory --now' first")
            return
        # Stay on current moment index if already browsing; else go to latest
        if self._stack.currentIndex() not in (self.IDX_MOMENTS, self.IDX_MOMENTS_VERDICT):
            self._moment_idx = len(self._moments) - 1
        self._load_moment()
        self._show_moment_view()

    # ── Pipeline ──────────────────────────────────────────────────────────────

    def _run_pipeline(self, pipeline: str) -> None:
        """Kick off a haiku or episode generation worker thread."""
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
        LOGGER.info("Pipeline '%s' done — %d items", pipeline, count)
        self._refresh_data()

    @pyqtSlot(str, str)
    def _on_pipeline_error(self, pipeline: str, error: str) -> None:
        LOGGER.error("Pipeline '%s' error: %s", pipeline, error)
        self._loading_w.set_message(f"❌  {error[:80]}")
        QTimer.singleShot(3000, self._refresh_data)

    # ── Flag handling ─────────────────────────────────────────────────────────

    def _toggle_flag(self, flag: str) -> None:
        """
        Toggle a heart/star/save flag for the currently visible item.

        Routes to the correct DB writer depending on whether we are in
        haiku mode or moments mode.
        """
        idx = self._stack.currentIndex()
        icon = {"is_hearted": "♥", "is_starred": "⭐", "is_saved": "💾"}.get(flag, "")

        if idx in (self.IDX_MOMENTS, self.IDX_MOMENTS_VERDICT):
            # Flag the current moment
            commit_hash = self._moments_player.get_commit_hash() or ""
            if commit_hash.startswith("moment:") and self._moments:
                moment_id = int(commit_hash.split(":")[1])
                new_val = self._db_writer.toggle_moment_flag(moment_id, flag)
                if new_val >= 0:
                    self._moments[self._moment_idx][flag] = new_val
                    self._moments_player.refresh_flags()
                    LOGGER.info("Moment flag %s %s for id=%d", icon,
                                "added" if new_val else "removed", moment_id)

        elif idx in (self.IDX_HAIKU, self.IDX_VERDICT):
            # Flag the current haiku
            commit_hash = self._haiku_player.get_commit_hash()
            if commit_hash and self._haikus:
                new_val = self._db_writer.toggle_haiku_flag(commit_hash, flag)
                self._haikus[self._haiku_idx][flag] = new_val
                self._haiku_player.refresh_flags()
                LOGGER.info("Haiku flag %s %s for %s", icon,
                            "added" if new_val else "removed", commit_hash[:7])

    # ── Keyboard routing ──────────────────────────────────────────────────────

    def keyPressEvent(self, event: QKeyEvent) -> None:
        """Handle all keyboard navigation and commands."""
        key = event.key()
        mods = event.modifiers()
        idx = self._stack.currentIndex()
        is_cmd = bool(mods & Qt.KeyboardModifier.ControlModifier)

        # ── Global commands ────────────────────────────────────────────────
        if key in (Qt.Key.Key_Q, Qt.Key.Key_Escape):
            QApplication.quit()
            return

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

        # ── View switching ─────────────────────────────────────────────────
        if key == Qt.Key.Key_H and self._haikus:
            self._show_haiku_view()
            return
        if key == Qt.Key.Key_E:
            self._stack.setCurrentIndex(self.IDX_EPISODE)
            return
        if key == Qt.Key.Key_N:
            self._enter_moments_mode()
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

        # ── Flags ─────────────────────────────────────────────────────────
        if key == Qt.Key.Key_L:
            self._toggle_flag("is_hearted")
            return
        if key == Qt.Key.Key_S and not is_cmd:
            self._toggle_flag("is_starred")
            return
        if key == Qt.Key.Key_B:
            self._toggle_flag("is_saved")
            return

        # ── Per-view navigation ────────────────────────────────────────────
        nav_step = 5 if event.isAutoRepeat() else 1

        if idx == self.IDX_HAIKU:
            if key == Qt.Key.Key_Space:
                self._haiku_player.advance()
            elif key == Qt.Key.Key_Right:
                self._next_haiku(nav_step)
            elif key == Qt.Key.Key_Left:
                self._prev_haiku(nav_step)

        elif idx == self.IDX_VERDICT:
            if key == Qt.Key.Key_Space:
                self._verdict_w.advance()
            elif key == Qt.Key.Key_Left:
                self._show_haiku_view()

        elif idx == self.IDX_MOMENTS:
            if key == Qt.Key.Key_Space:
                self._moments_player.advance()
            elif key == Qt.Key.Key_Right:
                self._next_moment(nav_step)
            elif key == Qt.Key.Key_Left:
                self._prev_moment(nav_step)

        elif idx == self.IDX_MOMENTS_VERDICT:
            if key == Qt.Key.Key_Space:
                self._moments_verdict_w.advance()
            elif key == Qt.Key.Key_Left:
                self._show_moment_view()

        else:
            if key == Qt.Key.Key_Space and self._haikus:
                self._show_haiku_view()

        super().keyPressEvent(event)


# ─── Public entry points ──────────────────────────────────────────────────────

def launch_app(cfg: Dict[str, Any], start_index: Optional[int] = None) -> int:
    """
    Launch the codeStory PyQt6 viewer in fullscreen.

    Args:
        cfg: Full codeStory config dict.
        start_index: Optional haiku index to open at launch.

    Returns:
        Application exit code.
    """
    LOGGER.info("Launching codeStory viewer — db=%s", cfg.get("db_path"))

    app = QApplication.instance() or QApplication(sys.argv)

    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor(BG_DARK))
    palette.setColor(QPalette.ColorRole.WindowText, QColor(TEXT_WHITE))
    palette.setColor(QPalette.ColorRole.Base, QColor(BG_CARD))
    palette.setColor(QPalette.ColorRole.Text, QColor(TEXT_BODY))
    app.setPalette(palette)

    window = MainWindow(cfg, start_index=start_index)
    window.showFullScreen()
    return app.exec()


def launch_app_now(cfg: Dict[str, Any], moment_id: Optional[int] = None) -> int:
    """
    Launch the codeStory viewer in Now-moments mode.

    Opens directly to the Now moments view, navigated to the given moment_id
    (or to the most recent moment if moment_id is None).

    Args:
        cfg: Full codeStory config dict.
        moment_id: DB id of the moment to display first.

    Returns:
        Application exit code.
    """
    LOGGER.info("Launching codeStory viewer in NOW mode — moment_id=%s", moment_id)

    app = QApplication.instance() or QApplication(sys.argv)

    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor(BG_DARK))
    palette.setColor(QPalette.ColorRole.WindowText, QColor(TEXT_WHITE))
    palette.setColor(QPalette.ColorRole.Base, QColor(BG_CARD))
    palette.setColor(QPalette.ColorRole.Text, QColor(TEXT_BODY))
    app.setPalette(palette)

    window = MainWindow(cfg, start_moment_id=moment_id)
    window.showFullScreen()
    return app.exec()
