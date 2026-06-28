# Handoff: Edge TTS GUI

## Project Location
`/Users/ccds/tmp/tts_gui`

## What Was Built

A desktop TTS app using **Slint (Python bindings)** + **edge-tts** + **miniaudio/sounddevice** for playback.

### Current Architecture (Post-Refactor)
```
src/tts_gui/
├── app.py            # 薄协调层 (~230 lines)
├── audio_player.py   # 播放模块（线程安全，Lock 保护）
├── tts_engine.py     # TTS + LLM 合成模块
├── task_runner.py    # 异步任务调度（per-task queue）
├── settings.py       # 配置 schema + load/save/apply/capture
├── history.py        # 历史记录管理（index.json + mp3）
├── ui.slint          # Slint UI 定义
├── icons/            # Lucide 风格 SVG 图标
├── __init__.py
└── __main__.py
tests/
├── test_task_runner.py
├── test_settings.py
├── test_tts_engine.py
├── test_history.py
└── test_audio_player.py
```

### Key Tech Decisions
- **模块化：** TTSApp 从 490 行单文件重构为 5 个独立模块 + 薄协调层
- **线程安全：** AudioPlayer 用 threading.Lock 保护 current_frame；TaskRunner 用 per-task Queue 替代共享 _result
- **Seek bug 修复：** _updating_progress 守卫防止 slider 双向绑定反馈循环
- **计时显示：** Toast 中展示 "清洗 Xs + 生成 Ys"
- **保存音频：** osascript choose file name 弹出原生保存对话框（worker 线程执行）
- **Icons:** Lucide SVG，colorize 适配主题
- **Config:** `~/.config/tts-gui/settings.json`
- **History:** `~/.config/tts-gui/history/` (index.json + mp3, max 50)
- **Packaging:** Briefcase → macOS .app

### Installed Skills
- `.agents/skills/slint/` — Slint 开发
- `.agents/skills/e2e-mcp-test/` — MCP E2E 测试流程

## Commands
```bash
cd /Users/ccds/tmp/tts_gui
uv run python -m tts_gui                   # Run dev
uv run pytest tests/ -q                    # Unit tests (31)
slint-viewer --check src/tts_gui/ui.slint  # Compile check

# Build & install
uv run briefcase update macOS && uv run briefcase build macOS
cp -R "build/tts-gui/macos/app/Edge TTS.app" /Applications/
codesign --force --deep --sign - "/Applications/Edge TTS.app"

# MCP debug
SLINT_EMIT_DEBUG_INFO=1 SLINT_MCP_PORT=9315 uv run python -m tts_gui
```

## Known Issues
- `cp -R` .app bundle 后必须 `codesign --force --deep --sign -` 重新签名
- Slint 不渲染 emoji（显示为□），需用 SVG + colorize 或设置 font-family: "Apple Color Emoji"
- tkinter 在 Slint 进程中会 crash（NSInvalidArgumentException），不能用作文件对话框
