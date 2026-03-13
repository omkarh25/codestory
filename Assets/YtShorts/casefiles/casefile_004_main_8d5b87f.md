# CASE FILE — The Pipeline Loaded

*774 lines of Python. One man. No exit.*

---

| Field      | Value |
|------------|-------|
| **Date**   | `2026-03-13` |
| **Commit** | `feat: implement git haiku pipeline with configurable depth` |
| **Branch** | `main` |
| **Type**   | `FEAT` — *Rising action — He acquired a new weapon* |
| **Author** | Omkar |
| **Hash**   | `8d5b87f` |
| **#**      | 004 |

---

### ACT I — THE ARSENAL ASSEMBLY

Still morning, still main, still the same daylight. He opened git_commit_haiku.py and began filling it: imports, path bootstrap, the GIT_CRIME_LEXICON hardcoded in stone. Anthropic waiting in the shadows. The database path resolved. The output directory made real.

### ACT II — THE HAIKU ENGINE TAKES SHAPE

The LLM client faced git commits like a detective faces crime scenes. load_config() pulled settings from config.json—max_haiku_per_run, batch_size, haiku_per_episode—each a constraint, each a leash. The function load_haiku_director_prompt() would read HaikuDirector.md at runtime, or fall back to _FALLBACK_HAIKU_PROMPT if the file went missing. Omkar was building redundancy into his own judgment.

### ACT III — THE MACHINERY AWAKENS

He implemented fetch_commits() to pull git history, async_haiku_batch() to fire LLM requests in parallel, and persist_haiku_to_db() to lock verdicts into tmChron.db. Every commit became a row. Every row became evidence. The depth modes—git_commit vs. git_diff—meant the LLM could see either just the message or the full diff with function names, class names, changed lines. He was building a system that could see deeper into his own crimes the more he asked it to.

---

### VERDICT

> He built the machine that would dissect him.

---

*codeStory — Director's Cut · Case #004*
