# Edge TTS GUI

基于 [Slint](https://slint.dev) + Python 的 Microsoft Edge TTS 语音合成桌面客户端。

![UI Preview](https://github.com/chocolatedesue/tts-gui/blob/main/docs/preview.png?raw=true)

## 功能

- 322 种语音，支持按语言/性别筛选
- 语速、音调、音量滑条调节
- 试听按钮快速预览音色
- 内存中生成和播放，无需预先保存文件
- 支持导出为 MP3 文件
- 支持 Briefcase 打包为 macOS `.app` / `.dmg`

## 快速开始

```bash
# 安装 uv (如果没有)
curl -LsSf https://astral.sh/uv/install.sh | sh

# 克隆并运行
git clone https://github.com/chocolatedesue/tts-gui.git
cd tts-gui
uv sync
uv run python src/tts_gui/app.py
```

## 开发流程

### 环境设置

```bash
uv sync                          # 安装依赖
```

### 运行

```bash
uv run python src/tts_gui/app.py  # 启动 GUI
```

### UI 开发 (热重载预览)

```bash
# 安装 slint-viewer
curl -fsSL https://github.com/slint-ui/slint/releases/latest/download/slint-viewer-macos.tar.gz | tar xz
install slint-viewer/slint-viewer ~/.local/bin/

# 热重载预览 UI (修改 .slint 文件时自动刷新)
slint-viewer --auto-reload src/tts_gui/ui.slint

# 静态编译检查
slint-viewer --check src/tts_gui/ui.slint

# 无头截图 (CI/review)
slint-viewer --screenshot preview.png src/tts_gui/ui.slint
```

### 项目结构

```
tts-gui/
├── pyproject.toml          # uv 依赖 + briefcase 打包配置
├── src/tts_gui/
│   ├── __init__.py
│   ├── __main__.py         # python -m tts_gui 入口
│   ├── app.py              # 主逻辑 (TTSApp 类)
│   └── ui.slint            # Slint UI 定义
└── .agents/skills/slint/   # Slint AI 开发 skill
```

### 依赖说明

| 包 | 用途 |
|---|---|
| `slint` | GUI 框架 (原生渲染) |
| `edge-tts` | Microsoft Edge TTS API |
| `miniaudio` | 内存中 MP3 解码 |
| `sounddevice` + `numpy` | 音频播放 |

## 打包分发 (Briefcase)

```bash
# 安装打包工具
uv add --group dev briefcase briefcasex-slint

# macOS
uv run briefcase create macOS
uv run briefcase build macOS
uv run briefcase run macOS                              # 测试
uv run briefcase package macOS --adhoc-sign --no-notarize  # 生成 .dmg

# 产物在 dist/ 目录
ls dist/*.dmg
```

> 注意: ad-hoc 签名只能在本机运行。分发给他人需要 Apple Developer 证书。

## License

MIT
