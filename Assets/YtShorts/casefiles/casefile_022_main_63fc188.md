# CASE FILE — The Contamination

*The parent's sins were bleeding into the child. He had to sever the connection.*

---

| Field      | Value |
|------------|-------|
| **Date**   | `2026-03-13` |
| **Commit** | `fix: isolate ytpipeline sys.argv from parent CLI flags in render_all` |
| **Branch** | `main` |
| **Type**   | `FIX` — *Damage control — The alibi was falling apart* |
| **Author** | Omkar |
| **Hash**   | `63fc188` |
| **#**      | 022 |

---

### ACT I — THE INFECTION SPREADS

March 13th, 1:18 PM. Main branch, three minutes after the Director's Cut was committed. The render_all function in src/codestory/render/video.py was hemorrhaging—sys.argv from the parent CLI was poisoning ytpipeline_main() with flags it never asked for.

### ACT II — THE ALIBI CRUMBLES

render_all() was being called by the parent process with --release_dry_run and other contaminating flags. ytpipeline_main() received them blindly, its own argument parser choking on orders it didn't understand. The exit_code came back wrong. The evidence was corrupted before it even reached the camera.

### ACT III — SURGICAL ISOLATION

He reached into video.py and performed the operation: save orig_argv, replace sys.argv with ["ytpipeline", "--all"], call ytpipeline_main() in a try-finally block, restore orig_argv. Four lines of defense. He isolated the child process from the parent's contamination, giving ytpipeline a clean slate, a blank confession. The fix was surgical—no other code touched, no other flags leaked. By the time ytpipeline woke, it knew only its own truth.

---

### VERDICT

> He couldn't control the parent, so he built a firewall between confession and judgment.

---

*codeStory — Director's Cut · Case #022*
