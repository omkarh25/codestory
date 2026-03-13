# codeStory — Audio Assets

This directory holds BGM tracks and SFX used by the Director's Cut render pipeline.

## Default Tracks (Built-In)

The pipeline ships with two default GarageBand Chillwave loops — already on your Mac,
no download required, royalty-free for content creation:

| Role           | File                                                                                  | Vibe                              |
|----------------|--------------------------------------------------------------------------------------|-----------------------------------|
| **Haiku BGM**  | `/Library/Audio/Apple Loops/Apple/07 Chillwave/Kyoto Night Synth.caf`               | Focused midnight intensity        |
| **Episode BGM**| `/Library/Audio/Apple Loops/Apple/07 Chillwave/Ghost Harmonics Synth.caf`           | Haunting, dramatic                |

Both are ~5s loops. ffmpeg's `-stream_loop -1` repeats them for the full video duration.

## Using a Custom Track

Place your `.wav`, `.mp3`, or `.aiff` file in this directory, then update `config.json`:

```json
{
  "codestory": {
    "audio": {
      "track_path": "Assets/audio/your_haiku_track.wav",
      "episode_track_path": "Assets/audio/your_episode_track.wav",
      "volume": 0.3,
      "fade_in_s": 1.0,
      "fade_out_s": 1.5
    }
  }
}
```

## Render Profiles

| Profile   | Audio | Casefile MD | Speed  |
|-----------|-------|-------------|--------|
| `minimal` | ✗     | ✗           | Fast   |
| `short`   | ✓     | ✓           | Normal |

Override via CLI:
```bash
python ytpipeline.py --render-profile minimal   # fast/silent
python ytpipeline.py --render-profile short     # full Director's Cut (default)
codestory --generate-ytshorts --render-profile short
```

## Recommended Free Sources

- **YouTube Audio Library** — filter by mood → "Dark" or "Cinematic"
- **Freesound.org** — CC0 licensed WAV files
- **GarageBand Apple Loops** — already on your Mac, 100% free for any use
