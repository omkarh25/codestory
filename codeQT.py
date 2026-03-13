"""
codeQT.py — The codeStory Cinematic Viewer

PyQt6 dark-cinema interface for the codeStory haiku + episode experience.

Haiku Mode — The 3-Act Player:
  Each haiku accumulates on screen progressively as the user presses SPACE.
  Act labels ("ACT I: The Dystopian Mind") are revealed via typewriter effect.
  Act body text is revealed instantly.
  The VERDICT gets its own full-screen dramatic slide.

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
    QRunnable, QThread, QTimer, Qt, QThreadPool, QObject,
    pyqtSignal, pyqtSlot,
)
from PyQt6.QtGui import QColor, QFont, QKeyEvent, QPalette, QFontDatabase
from PyQt6.QtWidgets import (
    QApplication, QFrame, QHBoxLayout, QLabel, QMainWindow,
    QProgressBar, QPushButton, QScrollArea, QSizePolicy,
    QStackedWidget, QStatusBar, QVBoxLayout, QWidget,
)

LOGGER = logging.getLogger(__name__)

# ─── Colour palette ───────────────────────────────────────────────────────────
BG_DARK        = "#0a1628"   # main background
BG_CARD        = "#0d1f3c"   # episode/verdict card background
BG_VERDICT     = "#080f1e"   # verdict slide background
DIVIDER_COL    = "#1e3a5f"   # horizontal rule colour
TEXT_WHITE     = "#f0f4ff"   # primary text
TEXT_SUBTITLE  = "#7a9cc0"   # subtitle / muted text
TEXT_BODY      = "#b8cce8"   # act body text
TEXT_ACT_LABEL = "#4a9eff"   # act number + title (electric blue)
TEXT_VERDICT_L = "#ff8c42"   # verdict label accent (warm orange)
TEXT_VERDICT_B = "#ffffff"   # verdict body text
TEXT_HASH      = "#4a6a8a"   # commit hash / metadata
TEXT_RULING    = "#ff6b35"   # MAX'S RULING accent
TEXT_EPISODE_T = "#e8d5b7"   # episode title warm cream

TYPEWRITER_INTERVAL_MS = 30   # ms per character


# ─── DB helper ────────────────────────────────────────────────────────────────

class DatabaseReader:
    """Reads haiku and episode data from tmChron.db.

    Separates all DB concerns from UI logic (Single Responsibility).
    """

    def __init__(self, db_path: str) -> None:
        """Initialise with path to tmChron.db.

        Args:
            db_path: Absolute path to the SQLite database file.
        """
        self._db_path = db_path
        LOGGER.debug("DatabaseReader initialised — path=%s", db_path)

    def load_haikus(self) -> List[Dict[str, Any]]:
        """Load all haiku rows ordered by commit_date ascending.

        Returns:
            List of haiku dicts. Empty list if DB missing or empty.
        """
        if not Path(self._db_path).exists():
            LOGGER.warning("DB not found: %s", self._db_path)
            return []
        try:
            conn = sqlite3.connect(self._db_path)
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM haiku_commits ORDER BY commit_date ASC"
            ).fetchall()
            conn.close()
            haikus = [dict(row) for row in rows]
            LOGGER.info("Loaded %d haikus from DB", len(haikus))
            return haikus
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
            episodes = [dict(row) for row in rows]
            LOGGER.info("Loaded %d episodes from DB", len(episodes))
            return episodes
        except sqlite3.OperationalError as exc:
            LOGGER.error("DB read error (episodes): %s", exc)
            return []


# ─── Typewriter effect ────────────────────────────────────────────────────────

class TypewriterEffect(QObject):
    """Character-by-character text reveal animation via QTimer.

    Signals:
        text_updated(str): emitted after each character is appended.
        finished():        emitted when the full text has been revealed.
    """

    text_updated = pyqtSignal(str)
    finished = pyqtSignal()

    def __init__(self, parent: Optional[QObject] = None) -> None:
        """Initialise the typewriter effect.

        Args:
            parent: Optional Qt parent object.
        """
        super().__init__(parent)
        self._full_text = ""
        self._current = ""
        self._pos = 0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        LOGGER.debug("TypewriterEffect initialised")

    def start(self, text: str, interval_ms: int = TYPEWRITER_INTERVAL_MS) -> None:
        """Begin typewriting the given text.

        Args:
            text:        The full text to reveal.
            interval_ms: Milliseconds between each character.
        """
        self._timer.stop()
        self._full_text = text
        self._current = ""
        self._pos = 0
        self._timer.start(interval_ms)
        LOGGER.debug("Typewriter started: %r", text[:30])

    def skip(self) -> None:
        """Immediately reveal the full text (user pressed SPACE during animation)."""
        self._timer.stop()
        self._current = self._full_text
        self._pos = len(self._full_text)
        self.text_updated.emit(self._current)
        self.finished.emit()
        LOGGER.debug("Typewriter skipped to end")

    def is_running(self) -> bool:
        """Return True if the typewriter animation is currently active."""
        return self._timer.isActive()

    @pyqtSlot()
    def _tick(self) -> None:
        """Advance one character and emit update or finished signal."""
        if self._pos < len(self._full_text):
            self._current += self._full_text[self._pos]
            self._pos += 1
            self.text_updated.emit(self._current)
        else:
            self._timer.stop()
            self.finished.emit()


# ─── Pipeline worker ──────────────────────────────────────────────────────────

class PipelineWorkerSignals(QObject):
    """Signals emitted by PipelineWorker.

    Attributes:
        finished(str, int): Pipeline name + count of items generated.
        error(str, str):    Pipeline name + error message.
    """
    finished = pyqtSignal(str, int)
    error    = pyqtSignal(str, str)


class PipelineWorker(QRunnable):
    """Runs haiku or episode pipeline in a thread pool to avoid blocking UI.

    Args:
        pipeline: "haiku" or "episode"
        cfg:      Config dict forwarded to fetch_actions().
    """

    def __init__(self, pipeline: str, cfg: Dict[str, Any]) -> None:
        """Initialise the pipeline worker.

        Args:
            pipeline: "haiku" or "episode"
            cfg:      Full config dict.
        """
        super().__init__()
        self._pipeline = pipeline
        self._cfg = cfg
        self.signals = PipelineWorkerSignals()

    @pyqtSlot()
    def run(self) -> None:
        """Execute the pipeline and emit finished or error signal."""
        LOGGER.info("PipelineWorker starting — pipeline=%s", self._pipeline)
        try:
            if self._pipeline == "haiku":
                from git_commit_haiku import fetch_actions
            else:
                from changelog_episodes import fetch_actions
            results = fetch_actions(config=self._cfg)
            count = len(results)
            LOGGER.info("PipelineWorker done — %d results", count)
            self.signals.finished.emit(self._pipeline, count)
        except Exception as exc:
            LOGGER.error("PipelineWorker error: %s", exc)
            self.signals.error.emit(self._pipeline, str(exc))


# ─── Haiku player ─────────────────────────────────────────────────────────────

class HaikuState(enum.IntEnum):
    """State machine for the 3-act haiku player."""
    IDLE             = 0   # title + subtitle shown; waiting for first SPACE
    TYPING_ACT1      = 1   # typewriting "ACT I: {act1_title}"
    ACT1_READY       = 2   # act1 label done; body shown
    TYPING_ACT2      = 3   # typewriting "ACT II: {act2_title}"
    ACT2_READY       = 4
    TYPING_ACT3      = 5
    ACT3_READY       = 6
    TYPING_VERDICT   = 7   # on verdict slide — typewriting "🔑  VERDICT"
    VERDICT_READY    = 8   # verdict body shown; waiting for SPACE → next haiku


def _label(
    text: str = "",
    color: str = TEXT_WHITE,
    size: int = 14,
    bold: bool = False,
    italic: bool = False,
    align: Qt.AlignmentFlag = Qt.AlignmentFlag.AlignLeft,
    word_wrap: bool = True,
) -> QLabel:
    """Factory for styled QLabel widgets.

    Args:
        text:      Initial text.
        color:     CSS colour string.
        size:      Font point size.
        bold:      Bold font weight.
        italic:    Italic style.
        align:     Text alignment.
        word_wrap: Enable word wrap.

    Returns:
        Configured QLabel.
    """
    lbl = QLabel(text)
    lbl.setStyleSheet(f"color: {color}; background: transparent;")
    font = lbl.font()
    font.setPointSize(size)
    if bold:
        font.setWeight(QFont.Weight.Bold)
    font.setItalic(italic)
    lbl.setFont(font)
    lbl.setAlignment(align)
    lbl.setWordWrap(word_wrap)
    return lbl


def _divider() -> QFrame:
    """Create a thin horizontal divider line.

    Returns:
        Styled QFrame divider.
    """
    line = QFrame()
    line.setFrameShape(QFrame.Shape.HLine)
    line.setStyleSheet(f"background-color: {DIVIDER_COL}; border: none;")
    line.setFixedHeight(1)
    return line


class HaikuPlayerWidget(QWidget):
    """The 3-act haiku player.

    Accumulates acts on screen as the user presses SPACE:
      - Act labels typed char-by-char ("ACT I: The Dystopian Mind")
      - Act body text revealed instantly
      - After all 3 acts: transitions to VerdictWidget

    Signals:
        request_verdict(dict): Emitted when user is ready for the verdict slide.
        request_next():        Emitted when verdict is done — move to next haiku.
        request_prev():        Emitted to navigate to previous haiku.
    """

    request_verdict = pyqtSignal(dict)
    request_next    = pyqtSignal()
    request_prev    = pyqtSignal()

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        """Initialise the haiku player with all labels hidden."""
        super().__init__(parent)
        self._haiku: Optional[Dict[str, Any]] = None
        self._state = HaikuState.IDLE
        self._typewriter = TypewriterEffect(self)
        self._typewriter.text_updated.connect(self._on_typewriter_update)
        self._typewriter.finished.connect(self._on_typewriter_done)
        self._build_ui()

    def _build_ui(self) -> None:
        """Construct the layout with all act labels and body widgets."""
        self.setStyleSheet(f"background-color: {BG_DARK};")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        # Centred content column (max 760px wide)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet(f"background: {BG_DARK}; border: none;")
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        content = QWidget()
        content.setStyleSheet(f"background: {BG_DARK};")
        self._content_layout = QVBoxLayout(content)
        self._content_layout.setContentsMargins(60, 50, 60, 40)
        self._content_layout.setSpacing(0)

        # ── Header ────────────────────────────────────────────────────────────
        self._lbl_meta = _label("", TEXT_HASH, 11, align=Qt.AlignmentFlag.AlignRight)
        self._lbl_title = _label("", TEXT_WHITE, 22, bold=True)
        self._lbl_subtitle = _label("", TEXT_SUBTITLE, 13, italic=True)
        self._lbl_subtitle.setContentsMargins(0, 4, 0, 0)

        self._content_layout.addWidget(self._lbl_meta)
        self._content_layout.addSpacing(10)
        self._content_layout.addWidget(self._lbl_title)
        self._content_layout.addWidget(self._lbl_subtitle)
        self._content_layout.addSpacing(20)
        self._content_layout.addWidget(_divider())
        self._content_layout.addSpacing(24)

        # ── Acts (initially hidden) ───────────────────────────────────────────
        self._act_widgets: List[Dict[str, QWidget]] = []
        for i in range(3):
            act_label = _label("", TEXT_ACT_LABEL, 13, bold=True)
            act_label.setContentsMargins(0, 0, 0, 6)
            act_body = _label("", TEXT_BODY, 14)
            act_body.setContentsMargins(0, 0, 0, 28)
            act_label.hide()
            act_body.hide()
            self._content_layout.addWidget(act_label)
            self._content_layout.addWidget(act_body)
            self._act_widgets.append({"label": act_label, "body": act_body})

        self._content_layout.addWidget(_divider())
        self._content_layout.addStretch(1)

        scroll.setWidget(content)
        outer.addWidget(scroll)

        # ── Hint bar ─────────────────────────────────────────────────────────
        hint = QWidget()
        hint.setFixedHeight(32)
        hint.setStyleSheet(f"background: {BG_CARD};")
        hint_layout = QHBoxLayout(hint)
        hint_layout.setContentsMargins(20, 0, 20, 0)
        self._lbl_hint = _label(
            "SPACE  advance    ←→  navigate    H  haiku    E  episodes    G  generate    Q  quit",
            TEXT_HASH, 10, align=Qt.AlignmentFlag.AlignCenter,
        )
        hint_layout.addWidget(self._lbl_hint)
        outer.addWidget(hint)

    def load_haiku(self, haiku: Dict[str, Any], index: int, total: int) -> None:
        """Load a new haiku and reset the player to IDLE state.

        Args:
            haiku: Haiku dict from the database.
            index: 1-based position in the haiku list.
            total: Total number of haikus.
        """
        self._haiku = haiku
        self._state = HaikuState.IDLE

        short_hash = (haiku.get("commit_hash") or haiku.get("hash", "?"))[:7]
        branch     = haiku.get("branch", "main") or "main"
        date       = (haiku.get("commit_date") or haiku.get("date", ""))[:10]
        commit_msg = haiku.get("commit_msg") or haiku.get("commit_message", "")

        self._lbl_meta.setText(
            f"  {index} / {total}   ·   {short_hash}   ·   {branch}   ·   {date}"
        )
        self._lbl_title.setText(haiku.get("title", f"CASE FILE — {short_hash}"))
        self._lbl_subtitle.setText(haiku.get("subtitle", commit_msg[:80]))

        # Hide all acts
        for widget_group in self._act_widgets:
            widget_group["label"].hide()
            widget_group["label"].setText("")
            widget_group["body"].hide()
            widget_group["body"].setText("")

        LOGGER.debug("Haiku loaded: %s (index=%d)", short_hash, index)

    def advance(self) -> None:
        """Handle SPACE press: skip typewriter if running, else advance state."""
        if self._typewriter.is_running():
            self._typewriter.skip()
            return

        # Advance state machine
        if self._state == HaikuState.IDLE:
            self._state = HaikuState.TYPING_ACT1
            self._start_act_typewriter(0)

        elif self._state == HaikuState.ACT1_READY:
            self._state = HaikuState.TYPING_ACT2
            self._start_act_typewriter(1)

        elif self._state == HaikuState.ACT2_READY:
            self._state = HaikuState.TYPING_ACT3
            self._start_act_typewriter(2)

        elif self._state == HaikuState.ACT3_READY:
            # Transition to verdict slide
            if self._haiku:
                self.request_verdict.emit(self._haiku)

        elif self._state == HaikuState.VERDICT_READY:
            self.request_next.emit()

    def _start_act_typewriter(self, act_idx: int) -> None:
        """Begin typewriting the act label for the given act index.

        Args:
            act_idx: 0, 1, or 2 for Acts I, II, III.
        """
        if not self._haiku:
            return
        roman = ["I", "II", "III"][act_idx]
        title_keys = ["act1_title", "act2_title", "act3_title"]
        act_title = self._haiku.get(title_keys[act_idx]) or ""
        label_text = f"ACT {roman}: {act_title}" if act_title else f"ACT {roman}"

        widget = self._act_widgets[act_idx]
        widget["label"].setText("")
        widget["label"].show()
        self._typewriter.start(label_text)

    def _on_typewriter_update(self, text: str) -> None:
        """Update the currently typewriting act label.

        Args:
            text: Partial text so far.
        """
        act_map = {
            HaikuState.TYPING_ACT1: 0,
            HaikuState.TYPING_ACT2: 1,
            HaikuState.TYPING_ACT3: 2,
        }
        idx = act_map.get(self._state)
        if idx is not None:
            self._act_widgets[idx]["label"].setText(text)

    def _on_typewriter_done(self) -> None:
        """Show the act body text after typewriter finishes, and update state."""
        if not self._haiku:
            return

        act_map = {
            HaikuState.TYPING_ACT1: (0, "when_where", HaikuState.ACT1_READY),
            HaikuState.TYPING_ACT2: (1, "who_whom",   HaikuState.ACT2_READY),
            HaikuState.TYPING_ACT3: (2, "what_why",   HaikuState.ACT3_READY),
        }
        mapping = act_map.get(self._state)
        if mapping:
            idx, body_key, next_state = mapping
            body_text = self._haiku.get(body_key, "")
            self._act_widgets[idx]["body"].setText(body_text)
            self._act_widgets[idx]["body"].show()
            self._state = next_state
            LOGGER.debug("Act %d revealed — state → %s", idx + 1, next_state.name)


# ─── Verdict widget ───────────────────────────────────────────────────────────

class VerdictWidget(QWidget):
    """Full-screen dramatic verdict slide.

    Typewriters "🔑  VERDICT", then reveals the verdict text.

    Signals:
        finished(): User pressed SPACE after reading — move to next haiku.
        go_back():  User pressed ← — return to act view.
    """

    finished = pyqtSignal()
    go_back  = pyqtSignal()

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        """Initialise the verdict widget."""
        super().__init__(parent)
        self._state = HaikuState.IDLE
        self._typewriter = TypewriterEffect(self)
        self._typewriter.text_updated.connect(self._on_typewriter_update)
        self._typewriter.finished.connect(self._on_typewriter_done)
        self._build_ui()

    def _build_ui(self) -> None:
        """Build the centred verdict panel layout."""
        self.setStyleSheet(f"background-color: {BG_VERDICT};")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addStretch(2)

        # Centred panel
        panel = QFrame()
        panel.setStyleSheet(
            f"background-color: {BG_CARD}; "
            f"border: 1px solid {DIVIDER_COL}; "
            "border-radius: 8px;"
        )
        panel.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(60, 50, 60, 50)
        panel_layout.setSpacing(20)

        self._lbl_verdict_title = _label("", TEXT_VERDICT_L, 16, bold=True)
        self._lbl_verdict_body = _label(
            "", TEXT_VERDICT_B, 18, italic=True,
            align=Qt.AlignmentFlag.AlignCenter,
        )
        self._lbl_verdict_body.hide()

        panel_layout.addWidget(self._lbl_verdict_title)
        panel_layout.addWidget(self._lbl_verdict_body)

        # Constrain panel width
        container = QHBoxLayout()
        container.setContentsMargins(80, 0, 80, 0)
        container.addWidget(panel)
        outer.addLayout(container)

        outer.addStretch(3)

        # Hint
        hint = QWidget()
        hint.setFixedHeight(32)
        hint.setStyleSheet(f"background: {BG_CARD};")
        hint_layout = QHBoxLayout(hint)
        hint_layout.setContentsMargins(20, 0, 20, 0)
        self._lbl_hint = _label(
            "SPACE  next haiku    ←  back to acts    H  haiku    E  episodes    Q  quit",
            TEXT_HASH, 10, align=Qt.AlignmentFlag.AlignCenter,
        )
        hint_layout.addWidget(self._lbl_hint)
        outer.addWidget(hint)

    def show_verdict(self, haiku: Dict[str, Any]) -> None:
        """Begin the verdict animation for the given haiku.

        Args:
            haiku: Haiku dict containing the verdict text.
        """
        self._state = HaikuState.TYPING_VERDICT
        self._lbl_verdict_title.setText("")
        self._lbl_verdict_body.hide()
        self._lbl_verdict_body.setText(f'"{haiku.get("verdict", "")}"')
        self._typewriter.start("🔑  VERDICT")
        LOGGER.debug("Verdict slide started")

    def advance(self) -> None:
        """Handle SPACE: skip typewriter or advance to next haiku."""
        if self._typewriter.is_running():
            self._typewriter.skip()
        elif self._state == HaikuState.VERDICT_READY:
            self.finished.emit()

    def _on_typewriter_update(self, text: str) -> None:
        """Update the verdict title label during typewriter animation."""
        self._lbl_verdict_title.setText(text)

    def _on_typewriter_done(self) -> None:
        """Reveal verdict body text after typewriter finishes."""
        self._lbl_verdict_body.show()
        self._state = HaikuState.VERDICT_READY
        LOGGER.debug("Verdict body revealed")


# ─── Episode viewer ───────────────────────────────────────────────────────────

class EpisodeCardWidget(QFrame):
    """A single episode card in the scrollable episode viewer.

    Displays: episode title, decade summary, branch note, MAX'S RULING.
    """

    def __init__(self, episode: Dict[str, Any], parent: Optional[QWidget] = None) -> None:
        """Initialise the episode card.

        Args:
            episode: Episode dict from the database.
            parent:  Optional Qt parent.
        """
        super().__init__(parent)
        self._build(episode)

    def _build(self, ep: Dict[str, Any]) -> None:
        """Construct the episode card layout.

        Args:
            ep: Episode data dict.
        """
        self.setStyleSheet(
            f"background-color: {BG_CARD}; "
            f"border: 1px solid {DIVIDER_COL}; "
            "border-radius: 6px;"
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 28, 32, 28)
        layout.setSpacing(10)

        # Episode title
        title_lbl = _label(
            ep.get("title", "UNTITLED EPISODE"),
            TEXT_EPISODE_T, 17, bold=True,
        )
        layout.addWidget(title_lbl)
        layout.addWidget(_divider())
        layout.addSpacing(6)

        # Decade summary
        if ep.get("decade_summary"):
            summary_lbl = _label(ep["decade_summary"], TEXT_BODY, 13)
            layout.addWidget(summary_lbl)
            layout.addSpacing(10)

        # Branch note
        if ep.get("branch_note"):
            branch_lbl = _label(ep["branch_note"], TEXT_SUBTITLE, 12, italic=True)
            layout.addWidget(branch_lbl)
            layout.addSpacing(12)

        layout.addWidget(_divider())
        layout.addSpacing(8)

        # MAX'S RULING
        ruling_header = _label("⚖  MAX'S RULING", TEXT_RULING, 11, bold=True)
        layout.addWidget(ruling_header)
        ruling_text = _label(
            f'"{ep.get("max_ruling", "")}"',
            TEXT_WHITE, 14, bold=True, italic=True,
        )
        ruling_text.setContentsMargins(0, 4, 0, 0)
        layout.addWidget(ruling_text)


class EpisodeViewerWidget(QWidget):
    """Scrollable episode case-file viewer showing all episode acts."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        """Initialise the episode viewer."""
        super().__init__(parent)
        self._build_ui()

    def _build_ui(self) -> None:
        """Build the scrollable episode list layout."""
        self.setStyleSheet(f"background-color: {BG_DARK};")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        # Header
        header = QWidget()
        header.setFixedHeight(60)
        header.setStyleSheet(f"background-color: {BG_CARD}; border-bottom: 1px solid {DIVIDER_COL};")
        hdr_layout = QHBoxLayout(header)
        hdr_layout.setContentsMargins(30, 0, 30, 0)
        self._header_lbl = _label(
            "📜  THE CHRONICLES  —  EPISODE ACTS",
            TEXT_WHITE, 16, bold=True,
        )
        hdr_layout.addWidget(self._header_lbl)
        outer.addWidget(header)

        # Scroll area
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet(f"background: {BG_DARK}; border: none;")

        self._scroll_content = QWidget()
        self._scroll_content.setStyleSheet(f"background: {BG_DARK};")
        self._cards_layout = QVBoxLayout(self._scroll_content)
        self._cards_layout.setContentsMargins(40, 30, 40, 30)
        self._cards_layout.setSpacing(20)
        self._cards_layout.addStretch(1)

        scroll.setWidget(self._scroll_content)
        outer.addWidget(scroll)

        # Hint bar
        hint = QWidget()
        hint.setFixedHeight(32)
        hint.setStyleSheet(f"background: {BG_CARD};")
        hint_layout = QHBoxLayout(hint)
        hint_layout.setContentsMargins(20, 0, 20, 0)
        hint_lbl = _label(
            "H  haiku mode    G  generate haikus    P  generate episode    R  refresh    Q  quit",
            TEXT_HASH, 10, align=Qt.AlignmentFlag.AlignCenter,
        )
        hint_layout.addWidget(hint_lbl)
        outer.addWidget(hint)

    def load_episodes(self, episodes: List[Dict[str, Any]]) -> None:
        """Populate the episode list.

        Args:
            episodes: List of episode dicts from the database.
        """
        # Clear existing cards (except the stretch at end)
        while self._cards_layout.count() > 1:
            item = self._cards_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        if not episodes:
            empty = _label(
                "No episodes yet.\n\nGenerate at least 10 haikus first, then press P.",
                TEXT_SUBTITLE, 14, align=Qt.AlignmentFlag.AlignCenter,
            )
            self._cards_layout.insertWidget(0, empty)
        else:
            for ep in reversed(episodes):   # newest first
                card = EpisodeCardWidget(ep)
                self._cards_layout.insertWidget(0, card)

        self._header_lbl.setText(
            f"📜  THE CHRONICLES  —  {len(episodes)} EPISODE ACT{'S' if len(episodes) != 1 else ''}"
        )
        LOGGER.info("Episode viewer loaded %d episodes", len(episodes))


# ─── Empty state widget ───────────────────────────────────────────────────────

class EmptyStateWidget(QWidget):
    """Shown when no haikus exist in the DB yet."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        """Initialise the empty state widget."""
        super().__init__(parent)
        self.setStyleSheet(f"background-color: {BG_DARK};")
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        icon = _label("🎬", TEXT_WHITE, 48, align=Qt.AlignmentFlag.AlignCenter)
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(icon)
        layout.addSpacing(20)

        msg = _label(
            "No haikus yet.\n\nPress  G  to generate haikus from your git history.",
            TEXT_SUBTITLE, 16, align=Qt.AlignmentFlag.AlignCenter,
        )
        msg.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(msg)
        layout.addSpacing(16)

        hint = _label(
            "Make sure config.json points to your repo and llm.env has your ANTHROPIC_API_KEY.",
            TEXT_HASH, 12, align=Qt.AlignmentFlag.AlignCenter,
        )
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(hint)


# ─── Loading overlay ──────────────────────────────────────────────────────────

class LoadingWidget(QWidget):
    """Overlay shown while a pipeline is running."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        """Initialise the loading overlay."""
        super().__init__(parent)
        self.setStyleSheet(f"background-color: {BG_DARK};")
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._lbl = _label("⏳  Generating...", TEXT_ACT_LABEL, 18, align=Qt.AlignmentFlag.AlignCenter)
        self._lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._lbl)

        self._sub = _label("MAX THE DESTROYER is at work.", TEXT_SUBTITLE, 13, align=Qt.AlignmentFlag.AlignCenter)
        self._sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._sub)

    def set_message(self, msg: str) -> None:
        """Update the loading message.

        Args:
            msg: New status text to display.
        """
        self._lbl.setText(msg)


# ─── Main window ──────────────────────────────────────────────────────────────

class MainWindow(QMainWindow):
    """Top-level application window managing all views and keyboard routing.

    Views (managed by QStackedWidget):
      0 — HaikuPlayerWidget  (haiku 3-act player)
      1 — VerdictWidget      (full-screen verdict)
      2 — EpisodeViewerWidget (scrollable episodes)
      3 — EmptyStateWidget   (no haikus yet)
      4 — LoadingWidget      (pipeline running)
    """

    IDX_HAIKU   = 0
    IDX_VERDICT = 1
    IDX_EPISODE = 2
    IDX_EMPTY   = 3
    IDX_LOADING = 4

    def __init__(self, cfg: Dict[str, Any]) -> None:
        """Initialise the main window.

        Args:
            cfg: Full config dict (db_path, etc.)
        """
        super().__init__()
        self._cfg = cfg
        self._db = DatabaseReader(cfg["db_path"])
        self._haikus: List[Dict[str, Any]] = []
        self._haiku_idx: int = 0
        self._thread_pool = QThreadPool()
        self._build_ui()
        self._refresh_data()
        LOGGER.info("MainWindow initialised")

    def _build_ui(self) -> None:
        """Construct the main window with all view widgets."""
        self.setWindowTitle("codeStory — The Chronicles")
        self.setMinimumSize(900, 600)
        self.resize(1100, 700)
        self.setStyleSheet(f"background-color: {BG_DARK};")

        # Central stacked widget
        self._stack = QStackedWidget()
        self._stack.setStyleSheet(f"background-color: {BG_DARK};")

        self._haiku_player = HaikuPlayerWidget()
        self._verdict_widget = VerdictWidget()
        self._episode_viewer = EpisodeViewerWidget()
        self._empty_widget = EmptyStateWidget()
        self._loading_widget = LoadingWidget()

        self._stack.addWidget(self._haiku_player)    # 0
        self._stack.addWidget(self._verdict_widget)  # 1
        self._stack.addWidget(self._episode_viewer)  # 2
        self._stack.addWidget(self._empty_widget)    # 3
        self._stack.addWidget(self._loading_widget)  # 4

        self.setCentralWidget(self._stack)

        # Wire haiku player signals
        self._haiku_player.request_verdict.connect(self._show_verdict)
        self._verdict_widget.finished.connect(self._next_haiku)
        self._verdict_widget.go_back.connect(self._show_haiku_view)

    def _refresh_data(self) -> None:
        """Reload haikus and episodes from DB and update all views."""
        LOGGER.info("Refreshing data from DB")
        self._haikus = self._db.load_haikus()
        episodes = self._db.load_episodes()
        self._episode_viewer.load_episodes(episodes)

        if not self._haikus:
            self._stack.setCurrentIndex(self.IDX_EMPTY)
        else:
            # Clamp index
            self._haiku_idx = min(self._haiku_idx, len(self._haikus) - 1)
            self._load_current_haiku()
            self._show_haiku_view()

    def _load_current_haiku(self) -> None:
        """Load the haiku at the current index into the player widget."""
        if not self._haikus:
            return
        haiku = self._haikus[self._haiku_idx]
        self._haiku_player.load_haiku(
            haiku,
            index=self._haiku_idx + 1,
            total=len(self._haikus),
        )
        LOGGER.debug("Loaded haiku %d/%d", self._haiku_idx + 1, len(self._haikus))

    def _show_haiku_view(self) -> None:
        """Switch to haiku player view."""
        self._stack.setCurrentIndex(self.IDX_HAIKU)

    def _show_verdict(self, haiku: Dict[str, Any]) -> None:
        """Switch to verdict slide and start animation.

        Args:
            haiku: Haiku data dict containing the verdict text.
        """
        self._stack.setCurrentIndex(self.IDX_VERDICT)
        self._verdict_widget.show_verdict(haiku)

    def _next_haiku(self) -> None:
        """Advance to the next haiku (wraps around)."""
        if not self._haikus:
            return
        self._haiku_idx = (self._haiku_idx + 1) % len(self._haikus)
        self._load_current_haiku()
        self._show_haiku_view()

    def _prev_haiku(self) -> None:
        """Go to the previous haiku (wraps around)."""
        if not self._haikus:
            return
        self._haiku_idx = (self._haiku_idx - 1) % len(self._haikus)
        self._load_current_haiku()
        self._show_haiku_view()

    def _run_pipeline(self, pipeline: str) -> None:
        """Run a haiku or episode pipeline in a background thread.

        Args:
            pipeline: "haiku" or "episode"
        """
        msg = "⏳  Generating haikus..." if pipeline == "haiku" else "⏳  Generating episode..."
        LOGGER.info("Running pipeline: %s", pipeline)
        self._loading_widget.set_message(msg)
        self._stack.setCurrentIndex(self.IDX_LOADING)

        worker = PipelineWorker(pipeline, self._cfg)
        worker.signals.finished.connect(self._on_pipeline_done)
        worker.signals.error.connect(self._on_pipeline_error)
        self._thread_pool.start(worker)

    @pyqtSlot(str, int)
    def _on_pipeline_done(self, pipeline: str, count: int) -> None:
        """Handle pipeline completion — refresh data and return to haiku view.

        Args:
            pipeline: "haiku" or "episode"
            count:    Number of items generated.
        """
        LOGGER.info("Pipeline '%s' done — %d items", pipeline, count)
        self._refresh_data()

    @pyqtSlot(str, str)
    def _on_pipeline_error(self, pipeline: str, error: str) -> None:
        """Handle pipeline error — show error in loading widget.

        Args:
            pipeline: "haiku" or "episode"
            error:    Error message string.
        """
        LOGGER.error("Pipeline '%s' error: %s", pipeline, error)
        self._loading_widget.set_message(f"❌  Error: {error[:80]}")
        # Return to previous view after 3 seconds
        QTimer.singleShot(3000, self._refresh_data)

    # ── Keyboard handling ─────────────────────────────────────────────────────

    def keyPressEvent(self, event: QKeyEvent) -> None:
        """Route keyboard shortcuts to the appropriate view or action.

        Args:
            event: Qt key press event.
        """
        key = event.key()
        current_idx = self._stack.currentIndex()

        # ── Global shortcuts (work in any view) ───────────────────────────────
        if key in (Qt.Key.Key_Q, Qt.Key.Key_Escape):
            LOGGER.info("User quit via keyboard")
            QApplication.quit()
            return

        if key == Qt.Key.Key_H:
            if self._haikus:
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
            if self.isFullScreen():
                self.showNormal()
            else:
                self.showFullScreen()
            return

        # ── View-specific shortcuts ───────────────────────────────────────────
        if current_idx == self.IDX_HAIKU:
            if key == Qt.Key.Key_Space:
                self._haiku_player.advance()
            elif key == Qt.Key.Key_Right:
                self._next_haiku()
            elif key == Qt.Key.Key_Left:
                self._prev_haiku()

        elif current_idx == self.IDX_VERDICT:
            if key == Qt.Key.Key_Space:
                self._verdict_widget.advance()
            elif key == Qt.Key.Key_Left:
                self._show_haiku_view()

        else:
            # Loading or episode view — SPACE goes to haiku view if we have data
            if key == Qt.Key.Key_Space and self._haikus:
                self._show_haiku_view()

        super().keyPressEvent(event)


# ─── Public entry point ───────────────────────────────────────────────────────

def launch_app(cfg: Dict[str, Any]) -> int:
    """Launch the codeStory PyQt6 application.

    Args:
        cfg: Full config dict (db_path required).

    Returns:
        Qt application exit code.
    """
    LOGGER.info("Launching codeStory viewer — db=%s", cfg.get("db_path"))

    app = QApplication.instance() or QApplication(sys.argv)

    # Set dark application palette
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor(BG_DARK))
    palette.setColor(QPalette.ColorRole.WindowText, QColor(TEXT_WHITE))
    palette.setColor(QPalette.ColorRole.Base, QColor(BG_CARD))
    palette.setColor(QPalette.ColorRole.Text, QColor(TEXT_BODY))
    app.setPalette(palette)

    window = MainWindow(cfg)
    window.show()

    return app.exec()


# ─── Standalone entry point ───────────────────────────────────────────────────

if __name__ == "__main__":
    import json as _json
    from pathlib import Path as _Path

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )

    _repo_root = _Path(__file__).resolve().parent

    # Load config
    _cfg: Dict[str, Any] = {
        "db_path": str(_repo_root / "tmChron.db"),
        "output_dir": str(_repo_root / "Assets" / "haikuJSON"),
        "repo_path": str(_repo_root),
        "haiku_provider": "anthropic",
        "haiku_model": "claude-haiku-4-5-20251001",
        "haiku_depth": "git_commit",
        "episode_provider": "anthropic",
        "episode_model": "claude-haiku-4-5-20251001",
        "episode_depth": "git_commit",
        "max_haiku_per_run": 12,
        "haiku_per_episode": 10,
    }
    config_path = _repo_root / "config.json"
    try:
        with open(config_path) as f:
            raw = _json.load(f)
        cfg_section = raw.get("tmChronicles", {})
        for key in ("db_path", "output_dir", "repo_path"):
            if key in cfg_section and not _Path(cfg_section[key]).is_absolute():
                cfg_section[key] = str(_repo_root / cfg_section[key])
        _cfg.update(cfg_section)
    except (FileNotFoundError, _json.JSONDecodeError):
        pass

    sys.exit(launch_app(_cfg))
