# 🎬 codeStory

> *"Every commit is a confession. Every repo is a crime scene. codeStory is the detective."*

**codeStory** reads your git history and turns it into a cinematic noir crime thriller — commit by commit, act by act.

Powered by **LLMs** and rendered in a **PyQt6 dark UI**, each git commit becomes a 3-act case file narrated by MAX THE DESTROYER. Ten confessions become an episode. The repo becomes a story.

---

## What It Does

```
git commit → 3-act noir haiku → DB → cinematic PyQt viewer
              (WHEN/WHERE)
              (WHO/WHOM)
              (WHAT/WHY)
              (VERDICT)

10 haikus → episode act → DB → episode viewer
             (TITLE)
             (DECADE SUMMARY)
             (BRANCH NOTE)
             (MAX'S RULING)
```

### The Depth Dial

| `haiku_depth` | What the LLM sees | Drama level |
|---------------|-------------------|-------------|
| `git_commit`  | Commit message only | 🔥 Good |
| `git_diff`    | Full diff — function names, class names, changed lines | 🔥🔥🔥 Visceral |

Same dial applies to episodes: `episode_depth: git_commit` or `git_diff`.

At `git_diff` depth, haikus reference actual code: *"He extracted `_build_llm_client()` from the void — the accomplice had a name now."*

---

## The UI

A full-screen PyQt6 dark cinema experience.

### Haiku Mode — The 3-Act Player

Each haiku is revealed progressively via **typewriter effect** for act titles, **instant reveal** for body text:

```
┌─────────────────────────────────────────────────────────┐
│  CASE FILE — "App Grew Eyes"          ← typewriter      │
│  Midnight on main, he taught it to see...  ← subtitle   │
│                                                          │
│  [SPACE] ──────────────────────────────────────────────▶│
│  ACT I — WHEN/WHERE                   ← typewriter      │
│  Full body text appears at once                          │
│                                                          │
│  [SPACE] ──────────────────────────────────────────────▶│
│  ACT II — WHO/WHOM                    ← typewriter      │
│  Body appears at once                                    │
│                                                          │
│  [SPACE] ──────────────────────────────────────────────▶│
│  ACT III — WHAT/WHY                   ← typewriter      │
│  Body appears at once                                    │
│                                                          │
│  [SPACE] ──────────────────────────────────────────────▶│
│  ┌──────────────────────────────────────────────────┐    │
│  │  🔑 VERDICT                      ← typewriter   │    │
│  │  "He didn't build an app..."     ← instant      │    │
│  └──────────────────────────────────────────────────┘    │
│                                                          │
│  [SPACE] → Next haiku                                   │
└─────────────────────────────────────────────────────────┘
```

### Episode Mode — The Case Files

Scrollable noir case-file layout showing episodic acts: title, decade summary, branch note, and MAX'S RULING.

---

## Keyboard Shortcuts

| Key | Action |
|-----|--------|
| `SPACE` | Advance (next act → next haiku) |
| `←` / `→` | Navigate between haikus |
| `H` | Switch to Haiku mode |
| `E` | Switch to Episode mode |
| `G` | Generate new haikus (triggers pipeline) |
| `P` | Generate new episode |
| `R` | Refresh from DB |
| `F` | Toggle fullscreen |
| `Q` / `ESC` | Quit |

---

## CLI Usage

### Main Pipeline

```bash
# Generate haikus for current repo
python codestory.py --generate-haikus

# Generate haikus with git diff depth (more dramatic)
python codestory.py --generate-haikus --depth git_diff

# Generate an episode (needs 10+ uncompiled haikus)
python codestory.py --generate-episodes

# Launch the PyQt viewer
python codestory.py --play

# Point at any repo
python codestory.py --repo /path/to/other/repo --generate-haikus

# Reset the database (fresh start)
python codestory.py --reset-db

# Full pipeline: generate + play
python codestory.py --generate-haikus --generate-episodes --play
```

### CRUD Operations (Haikus)

**Delete a haiku** (removes from DB + cleans up JSON files):
```bash
python git_commit_haiku.py --delete f4096af
```

**Regenerate a haiku** (delete + re-LLM-generate after failed attempt):
```bash
python git_commit_haiku.py --regenerate f4096af
```

**Check consistency** (orphaned/missing JSON files, duplicate filenames):
```bash
python git_commit_haiku.py --validate
```

**Rebuild chronological indices** (after git history rebase/force-push):
```bash
python git_commit_haiku.py --rebuild-indices
```

### CRUD Operations (Episodes)

**Delete an episode** (removes from DB + un-marks its haikus as compiled):
```bash
python changelog_episodes.py --delete 1
```

**Regenerate an episode** (delete + re-synthesize from fresh haikus):
```bash
python changelog_episodes.py --regenerate 1
```

**Check episode consistency** (orphaned JSONs, missing files, broken commit references):
```bash
python changelog_episodes.py --validate
```

### Git Commit Hook (CI/CD)

Auto-generate a haiku on every commit. Add to `.git/hooks/post-commit`:

```bash
#!/bin/bash
conda run -n macenv python /path/to/codestory.py --generate-haikus --max 1
```

Make it executable:
```bash
chmod +x .git/hooks/post-commit
```

---

## Setup

### Requirements

- Python 3.10+
- `macenv` conda environment with PyQt6
- Anthropic API key

### Install

```bash
# Clone the repo
git clone https://github.com/omkarh25/codestory.git
cd codestory

# Activate macenv
conda activate macenv

# Install dependencies
pip install anthropic python-dotenv PyQt6

# Set up your API key
cp llm.env.example llm.env
# Edit llm.env and add your ANTHROPIC_API_KEY

# Point at a repo and generate
python codestory.py --repo /path/to/your/repo --generate-haikus --play
```

### Config (`config.json`)

```json
{
    "tmChronicles": {
        "repo_path": ".",
        "max_haiku_per_run": 12,
        "batch_size": 3,
        "haiku_per_episode": 10,
        "db_path": "tmChron.db",
        "output_dir": "Assets/haikuJSON",
        "haiku_provider": "anthropic",
        "haiku_model": "claude-haiku-4-5-20251001",
        "haiku_depth": "git_commit",
        "episode_provider": "anthropic",
        "episode_model": "claude-haiku-4-5-20251001",
        "episode_depth": "git_commit",
        "oldest_first": true
    }
}
```

---

## The Director

The LLM narrator persona lives in `Director/`:

| File | Purpose |
|------|---------|
| `Director/HaikuDirector.md` | MAX THE DESTROYER's brief for haiku generation |
| `Director/EpisodeDirector.md` | MAX's brief for episodic act writing |
| `Director/RepoStory.md` | Origin story preface — the baseline context for all episodes |

Edit these files to tune tone, lexicon, or output format without touching code.

---

## The Architecture

```
codestory.py              ← CLI entry point
├── git_commit_haiku.py   ← Haiku pipeline (git log → LLM → DB)
├── changelog_episodes.py ← Episode pipeline (DB haikus → LLM → DB)
├── codeQT.py             ← PyQt6 viewer
├── config.json           ← All settings
├── llm.env               ← API keys (gitignored)
├── tmChron.db            ← SQLite (gitignored)
└── Director/
    ├── HaikuDirector.md  ← Haiku LLM system prompt
    ├── EpisodeDirector.md← Episode LLM system prompt
    └── RepoStory.md      ← Origin story preface
```

---

## The Git Crime Lexicon

| Git Term | Crime Equivalent |
|----------|-----------------|
| `bug` | thug / hired muscle |
| `branch` | parallel operation / side racket |
| `merge` | the conspiracy comes together |
| `commit` | confession / signing the deed |
| `push` | going public / point of no return |
| `revert` | burning the evidence |
| `stash` | contraband / hidden assets |
| `diff` | the forensic report |
| `.gitignore` | witness protection |

---

## Future Directions

- **DB diff depth**: haikus from database schema changes (table names, column names, data diffs)
- **YouTube Shorts pipeline**: `ytpipeline.py` — render haiku slides to video via ffmpeg
- **Git hooks**: auto-generate on every commit
- **Multi-repo**: track multiple repos in one DB

---

*"He didn't build a productivity app. He built a confessional booth — and called it codeStory."*
test change
