# CASE FILE — The Missing Link

*The database path was lost in translation. He had to teach the pipeline to remember where the truth was buried.*

---

| Field      | Value |
|------------|-------|
| **Date**   | `2026-03-13` |
| **Commit** | `fix: pass db-path to ytpipeline from render_all, add --db-path flag` |
| **Branch** | `main` |
| **Type**   | `FIX` — *Damage control — The alibi was falling apart* |
| **Author** | Omkar |
| **Hash**   | `29bbde1` |
| **#**      | 023 |

---

### ACT I — THE SILENT GAP

March 13th, 1:20 PM. Main branch, ninety seconds after the isolation fix. The render_all() function was calling ytpipeline_main() with a clean argv, but ytpipeline had no way to know which database held the case files. The connection between the confessions and the renderer was invisible.

### ACT II — THE HANDOFF

render_all() in src/codestory/render/video.py knew the db_path from config. ytpipeline_main() in the legacy pipeline needed it but had no mechanism to receive it. The data was locked in one room, the renderer waiting in another. A new _box() function and _step() counter were added to __main__.py—240 lines of preflight ceremony—but the core problem remained: no bridge.

### ACT III — THE SIGNAL RESTORED

He added a --db-path flag to the CLI. render_all() would now pass the database path directly to ytpipeline via sys.argv: ["ytpipeline", "--all", "--db-path", db_path]. The preflight wizard—run_release_dry_run()—would check the database status, count haikus and episodes, verify storyboards, audit the render queue, inspect audio tracks. Six steps. Six checkpoints. Every confession would be verified before rendering. The pipeline could now trace its way back to the source of truth.

---

### VERDICT

> He didn't just fix the pipeline; he built a courtroom where every witness could be cross-examined before the verdict was filmed.

---

*codeStory — Director's Cut · Case #023*
