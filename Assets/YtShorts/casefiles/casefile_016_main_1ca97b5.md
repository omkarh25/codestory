# CASE FILE — The Backdoor Opens

*He threaded a needle through MainWindow's throat and called it navigation.*

---

| Field      | Value |
|------------|-------|
| **Date**   | `2026-03-13` |
| **Commit** | `feat(viewer): add start_index support for direct haiku navigation` |
| **Branch** | `main` |
| **Type**   | `FEAT` — *Rising action — He acquired a new weapon* |
| **Author** | Omkar |
| **Hash**   | `1ca97b5` |
| **#**      | 016 |

---

### ACT I — MIDDAY ON MAIN

March 13th, 11:48 AM. Main branch. The kind of afternoon when nobody's watching the code review. Omkar had the terminal open and a plan that smelled like shortcuts.

### ACT II — THE NEW PARAMETER

MainWindow's __init__ now takes a start_index—a direct line to any haiku the caller wants to land on. The old flow, the one that started at the newest entry, was about to be circumvented. The viewer didn't know it yet, but it was about to become a puppet on a string.

### ACT III — THE HANDOFF

He spliced start_index into three files: codeQT.py's MainWindow constructor, the commit pipeline's run_commit_pipeline function (which now runs git add -A before committing, staging everything blind), and qt_viewer.py's launch_app, which now passes the index directly to the window. The _haiku_idx gets overwritten on first load, then _start_index clears itself—a one-time weapon that leaves no trace. The commit pipeline doesn't ask questions; it just stages everything and moves on. He built a door that only opens from the outside.

---

### VERDICT

> He didn't just add a feature; he installed a remote control for someone else's hands.

---

*codeStory — Director's Cut · Case #016*
