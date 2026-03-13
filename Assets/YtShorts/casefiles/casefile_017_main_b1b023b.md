# CASE FILE — The Cleanup

*Three lines of garbage deleted, but the trap was already set.*

---

| Field      | Value |
|------------|-------|
| **Date**   | `2026-03-13` |
| **Commit** | `fix(viewer): remove duplicate imports and dead code` |
| **Branch** | `main` |
| **Type**   | `FIX` — *Damage control — The alibi was falling apart* |
| **Author** | Omkar |
| **Hash**   | `b1b023b` |
| **#**      | 017 |

---

### ACT I — TWENTY-SEVEN SECONDS LATER

11:49 AM, same branch, same office. He'd already pushed the first commit and now he was running through qt_viewer.py like a man erasing footprints. The imports were bleeding—QApplication imported twice, sys redundant, MainWindow dragged in but never used.

### ACT II — THE ALIBI CRUMBLES

The duplicate imports in qt_viewer.py's launch_app function were the evidence: from codeQT import MainWindow, QApplication on line 37, then from PyQt6.QtWidgets import QApplication again, and import sys dangling like a confession. They had to go. The code had to look clean, intentional, not like the work of a man in a hurry.

### ACT III — THE ERASURE

He deleted the bad imports—the ones that contradicted each other—leaving only from PyQt6.QtWidgets import QApplication and the sys that was already in scope at the module level. The file now reads as if it was always this way: tight, purposeful, a man who knew exactly what he was doing. The trap was still there. The backdoor was still open. He just made sure nobody would see the trembling hands that built it.

---

### VERDICT

> He didn't fix the code; he fixed the crime scene.

---

*codeStory — Director's Cut · Case #017*
