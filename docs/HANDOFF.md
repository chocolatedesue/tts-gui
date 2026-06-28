# Handoff: Edge TTS GUI

## Project Location
`/Users/ccds/tmp/tts_gui`

## GitHub
https://github.com/chocolatedesue/tts-gui

## What Was Built

A desktop TTS app using **Slint (Python bindings)** + **edge-tts** + **miniaudio/sounddevice** for playback.

### Current Architecture
```
src/tts_gui/
├── ui.slint          # Slint UI (sidebar + synth page + settings page + player bar + toast)
├── app.py            # Python logic (TTSApp class, all callbacks)
├── icons/mic.svg     # Sidebar icon
├── icons/settings.svg
├── __init__.py
└── __main__.py
```

### Key Tech Decisions
- **Rendering**: Slint's 21MB native Rust .so does all rendering via Skia+Metal (GPU). Python is FFI-only.
- **Thread safety**: Worker threads NEVER touch `win.*`. All UI updates via Timer polling + shared `_result` variable.
- **Config**: `~/.config/tts-gui/settings.json` stores LLM API key/url/model, TTS params, device selection.
- **Packaging**: Briefcase → macOS .app (157MB, embeds CPython 3.13 + all deps).
- **Icons**: SVG files with `colorize` for theme adaptation (emoji renders as □ in Slint).

### Installed Skills
- `.agents/skills/slint/` — Slint language, layout, polish, gotchas, MCP server, viewer screenshots
- `.agents/skills/to-prd/`, `to-issues/`, `implement/`, `review/` — engineering workflow

## What's Done
- ✅ Left-right text panels (original | cleaned) with LLM cleaning via gemini-3.5-flash
- ✅ Voice browser (322 voices, lang/gender filter, preview)
- ✅ Bottom player bar (play/pause, stop, progress slider, time, volume, speed)
- ✅ Settings page (LLM config, TTS params, audio device)
- ✅ SVG sidebar icons
- ✅ Toast notification system
- ✅ Window freely resizable
- ✅ Default zh-CN voices
- ✅ Accent-colored Generate button
- ✅ Installed to /Applications/Edge TTS.app

## What's Next (Unfinished)

### 1. Visual Design Improvement (HIGH PRIORITY)
Current UI is functional but lacks polish/beauty. Needs:
- Research good TTS/audio app UIs (Descript, ElevenLabs desktop, Voice Memos)
- Better color palette, spacing rhythm, subtle shadows/borders
- More refined player bar (progress bar styling, proper iconography)
- Consider custom theme global with curated colors

### 2. Loop Playback + Default 1.5x Speed
- Add loop toggle button (🔁) to player bar
- Default speed = 1.5x
- Loop: auto-restart from beginning when playback ends

### 3. Stability
- The app has crashed before due to cross-thread access (abort() on Thread 18)
- Current fix: Timer polling. But need to audit ALL paths where worker might touch UI.
- The save dialog uses `osascript` on macOS (tkinter crashes from threads)

## Key Files to Read First
1. `docs/PRD-v2-ui-redesign.md` — full requirements
2. `docs/ADR-001-ui-redesign.md` — design decisions from grill session
3. `src/tts_gui/ui.slint` — current UI definition
4. `src/tts_gui/app.py` — current Python logic
5. `.agents/skills/slint/reference/polish.md` — Slint visual polish checklist

## Commands
```bash
cd /Users/ccds/tmp/tts_gui
uv run python src/tts_gui/app.py          # Run dev
slint-viewer --check src/tts_gui/ui.slint  # Compile check
slint-viewer --screenshot out.png src/tts_gui/ui.slint  # Headless screenshot
slint-viewer --auto-reload src/tts_gui/ui.slint  # Live preview

# Build & install
uv run briefcase create macOS && uv run briefcase build macOS
cp -R "build/tts-gui/macos/app/Edge TTS.app" /Applications/
```

## LLM API (local config only, not in git)
- URL: https://gemini-web2api.588345.xyz/v1
- Model: gemini-3.5-flash
- Config: ~/.config/tts-gui/settings.json
