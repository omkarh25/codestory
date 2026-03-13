# 🎬 codeStory

> *"Every commit is a confession. Every repo is a crime scene. codeStory is the detective."*

**codeStory** reads your git history and turns it into a cinematic noir crime thriller — commit by commit, act by act.

Powered by **LLMs** and rendered in a **PyQt6 dark UI**, each git commit becomes a 3-act case file narrated by MAX THE DESTROYER. Ten confessions become an episode. The repo becomes a story.

---

## What It Does

```
git commit
   ↓
haiku pipeline (HaikuDirector.md) → casefile JSON + casefile_NNN.md
   ↓  (every 10)
episode pipeline (EpisodeDirector.md) → episode JSON
   ↓
storyboard pipeline (ReleaseCutDirector.md) → storyboard.json
   ↓
ytpipeline → PNG slides → ffmpeg + BGM (Kyoto Night Synth)
   ↓
haiku_NNN_branch_hash.mp4  +  episode_NNN.mp4
```

### The Three Render Tiers (Configurable Complexity)

| Profile   | Command                                    | Output                                          |
|-----------|--------------------------------------------|-------------------------------------------------|
| `minimal` | `--render-profile minimal`                 | Silent MP4, fast, no companion files            |
| `short`   | `--render-profile short` *(default)*       | MP4 + BGM + Director's Cut casefile .md         |

Set in `config.json` under `"render": { "profile": "short" }` or override on CLI.

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
| `Director/HaikuDirector.md` | MAX THE DESTROYER's brief for haiku generation — **do not modify** |
| `Director/EpisodeDirector.md` | MAX's brief for episodic act writing |
| `Director/RepoStory.md` | Origin story preface — the baseline context for all episodes |
| `Director/ReleaseCutDirector.md` | ✨ **NEW** — Cinematic storyboard generator. Takes episode + case files, produces JSON shot list for video renderer |

Edit these files to tune tone, lexicon, or output format without touching code.

### ReleaseCutDirector Storyboard JSON

When you run `--generate-storyboard`, MAX THE DESTROYER reads your episode and case files
and produces a `storyboard_episode_NNN.json`:

```json
{
  "episode_index": 1,
  "title": "Episode 1: The Birth of Sin",
  "opening_line": "They thought it was a refactor. It was reconstruction.",
  "generated_by": "ReleaseCutDirector",
  "total_shots": 13,
  "shots": [
    { "shot_id": "title_card", "type": "TitleCard",  "duration_s": 6.0, ... },
    { "shot_id": "case_roll",  "type": "CaseRoll",   "duration_s": 6.0, ... },
    { "shot_id": "case_001",   "type": "CaseFile",   "duration_s": 18.0, ... },
    ...
    { "shot_id": "episode_verdict", "type": "VerdictCard", "duration_s": 8.0, ... }
  ]
}
```

The storyboard drives the video renderer — each shot type becomes a slide, durations are
scaled by commit type (feat = 18s, chore = 12s, etc.).

---

## BGM Setup

The Director's Cut pipeline ships with two built-in GarageBand Chillwave loops
(already on your Mac, royalty-free for content creation):

| Role           | Track                         | Vibe                        |
|----------------|-------------------------------|-----------------------------|
| Haiku videos   | `Kyoto Night Synth.caf`       | Focused midnight intensity  |
| Episode videos | `Ghost Harmonics Synth.caf`   | Haunting, dramatic          |

Both are ~5s loops — ffmpeg's `-stream_loop -1` repeats them to fit the video length,
with a 1s fade-in and 1.5s fade-out applied automatically.

**To use a custom track**, add to `config.json`:
```json
{
  "codestory": {
    "audio": {
      "track_path": "Assets/audio/your_track.wav",
      "episode_track_path": "Assets/audio/your_episode_track.wav",
      "volume": 0.3,
      "fade_in_s": 1.0,
      "fade_out_s": 1.5
    }
  }
}
```

See `Assets/audio/README.md` for free track sources.

---

## The Architecture

```
codestory.py / src/codestory/__main__.py    ← CLI entry point
├── src/codestory/pipeline/
│   ├── haiku.py          ← Haiku pipeline (git log → LLM → DB)
│   ├── episode.py        ← Episode pipeline (DB haikus → LLM → DB)
│   └── git.py            ← Git log reader + crime lexicon
├── src/codestory/render/
│   ├── video.py          ← Render facade (delegates to ytpipeline)
│   ├── markdown.py       ← ✨ Director's Cut casefile .md writer
│   └── storyboard.py     ← ✨ Storyboard JSON generator (LLM + default)
├── src/codestory/director/
│   └── prompts.py        ← Prompt loader (HaikuDirector, EpisodeDirector, ReleaseCutDirector)
├── ytpipeline.py         ← PNG slides → ffmpeg + BGM → MP4
├── codeQT.py             ← PyQt6 viewer
├── config.json           ← All settings
├── llm.env               ← API keys (gitignored)
├── Director/
│   ├── HaikuDirector.md        ← Haiku LLM brief (do not modify)
│   ├── EpisodeDirector.md      ← Episode LLM brief
│   ├── RepoStory.md            ← Origin story preface
│   └── ReleaseCutDirector.md   ← ✨ Storyboard shot-list generator
└── Assets/
    ├── YtShorts/         ← Rendered MP4 output + casefile .md files
    ├── audio/            ← ✨ BGM tracks (see README inside)
    └── haikuJSON/        ← Haiku JSON files
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

## New CLI Commands

```bash
# Generate Director's Cut storyboard JSON for latest episode
codestory --generate-storyboard

# Render with specific profile
codestory --generate-ytshorts --render-profile minimal  # fast, no BGM
codestory --generate-ytshorts --render-profile short    # BGM + casefile MD (default)

# Same via ytpipeline direct
python ytpipeline.py --render-profile minimal --max 3
python ytpipeline.py --episode 1 --render-profile short

# Full Director's Cut pipeline (haiku → episode → storyboard → render)
codestory --generate-haikus --generate-episodes --generate-storyboard --generate-ytshorts
```

---

## Future Directions

- **Tier 3 — Remotion keynote render**: React + Remotion for Apple-style release trailers
- **Multi-repo**: track multiple repos in one DB
- **Storyboard viewer**: interactive shot-list editor before rendering
- **SFX transitions**: whoosh sounds between slide reveals

---

*"He didn't build a productivity app. He built a confessional booth — and called it codeStory."*

---

## Changelog

### 2026-03-13

**Fix**: SIGSEGV crash in PyQt6 viewer during `--commit` flow

The background thread for YouTube Shorts rendering was importing `ytpipeline.py`, which
created a `QApplication` at module import time. When the viewer subsequently tried to
launch in the main thread, Qt detected the QApplication was created in a different thread
and crashed with "QApplication was not created in the main() thread".

**Solution**: Changed `ytpipeline.py` to use lazy QApplication initialization — the
`QApplication` is now only created when actually rendering videos (inside
`_ensure_offscreen_app()`), not at module import time. This prevents Qt from
initializing in the wrong thread when `ytpipeline` is imported as a side effect.

---

### 2026-03-12

**Fix**: Episode generation logic error

Episode generation was incorrectly calculating which haikus to include, causing
episodes to have too few or too many haikus.

**Solution**: Rewrote the episode aggregation logic to correctly group haikus by
episode_number from the database.
