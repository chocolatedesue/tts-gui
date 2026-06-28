# PRD: Edge TTS 语音合成桌面应用

## Problem Statement

用户需要一个简单易用的桌面 TTS（文本转语音）工具，能够：
- 利用免费的 Microsoft Edge TTS 服务将文本合成为自然语音
- 在合成前自动清洗文本（移除 markdown、语气词、口头禅等不适合朗读的内容）
- 支持多种语音和参数调节
- 直接在应用内播放和保存，无需命令行操作

现有 edge-tts CLI 虽然功能完整，但缺乏 GUI、文本预处理能力和一体化的试听体验。

## Solution

基于 Slint (Rust 原生渲染) + Python 构建的跨平台桌面应用，提供：
- 左右分栏界面：左侧输入原文，右侧实时显示 LLM 清洗后的文本
- 322 种语音浏览器，支持按语言/性别筛选和一键试听
- 语速/音调/音量全参数调节
- 内存中生成和播放（无需保存临时文件）
- 通过 Briefcase 打包为原生 macOS .app（未来可扩展 Windows/Linux）
- 设置页面支持自定义 LLM API、清洗 Prompt、输出设备

## User Stories

1. As a 内容创作者, I want to 将文章一键转为语音, so that 我可以快速制作音频内容
2. As a 用户, I want to 选择不同语言和性别的语音, so that 我能找到最适合内容的声音
3. As a 用户, I want to 在合成前自动移除 markdown 格式和语气词, so that 生成的语音自然流畅
4. As a 用户, I want to 看到清洗前后的文本对比, so that 我能确认清洗质量
5. As a 用户, I want to 一键试听某个语音, so that 我不用合成全文就能判断语音是否合适
6. As a 用户, I want to 调节语速/音调/音量, so that 我能精细控制输出效果
7. As a 用户, I want to 在应用内直接播放生成的语音, so that 我不需要切换到其他播放器
8. As a 用户, I want to 选择音频输出设备, so that 我能通过蓝牙耳机或外接音箱试听
9. As a 用户, I want to 将生成的语音保存为 MP3, so that 我可以在其他地方使用
10. As a 用户, I want to 关闭文本清洗功能, so that 当原文已经是纯文本时不做多余处理
11. As a 用户, I want to 自定义 LLM API 地址和模型, so that 我能使用自己的服务或切换更好的模型
12. As a 用户, I want to 自定义清洗 Prompt, so that 我能针对不同场景调整清洗策略
13. As a 用户, I want to 设置被持久化保存, so that 每次打开应用不用重新配置
14. As a 用户, I want to 应用默认选中中文语音, so that 作为中文用户不需要手动筛选
15. As a 用户, I want to 将应用安装为 macOS .app, so that 我能从启动台直接打开
16. As a 用户, I want to 应用不崩溃, so that 长时间使用时体验稳定

## Implementation Decisions

- **GUI 框架**: Slint (Rust 原生渲染引擎，Python 绑定)，`.slint` 声明式 UI，支持深色模式自动适配
- **TTS 引擎**: edge-tts (免费，无需 API Key，走 Microsoft Edge WebSocket 协议)
- **音频播放**: miniaudio 解码 MP3 → sounddevice OutputStream 播放，全程内存操作
- **文本清洗**: OpenAI 兼容 API (`/v1/chat/completions`)，可配置 URL/Key/Model/Prompt
- **线程模型**: 所有网络/音频操作在 worker thread 执行，通过 Timer 轮询将结果同步回 UI 主线程（Slint 不允许跨线程访问 UI 组件）
- **持久化**: 设置保存到 `~/.config/tts-gui/settings.json`
- **打包分发**: Briefcase + briefcasex-slint 插件，产出 macOS .app/.dmg
- **依赖管理**: uv + pyproject.toml，BFSU 镜像源
- **导航模式**: 左侧固定导航栏，页面通过 `current-page` 属性切换（合成页/设置页）
- **字体策略**: `default-font-size: 15px`，所有控件继承统一基线

## Testing Decisions

- **外部行为测试为主**: 验证"输入文本 → 得到音频字节"的完整流程，不测试内部 Timer 细节
- **TTS 集成测试**: 验证 edge-tts 能生成有效 MP3 字节流（`miniaudio.decode` 不报错）
- **LLM 清洗测试**: 验证 API 调用返回 200 且输出是纯文本
- **UI 编译测试**: `slint-viewer --check` 验证 .slint 文件无编译错误
- **视觉回归**: `slint-viewer --screenshot` 生成截图用于 review
- **稳定性测试**: 确保播放完成后无跨线程 panic（Thread assertion failed）

## Out of Scope

- 批量文件处理 / 队列合成
- SSML 高级标记支持
- 实时流式边生成边播放
- Windows / Linux 打包（架构支持，但当前只做 macOS）
- 用户账户系统
- 语音克隆 / 自定义语音训练
- 离线 TTS 引擎

## Further Notes

- edge-tts 依赖网络连接（Microsoft Edge 服务），无网时不可用
- LLM 清洗 API 默认使用 `gemini-3.5-flash`，可在设置页切换
- Slint 当前 Python 绑定为 Beta (1.17.0b2)，API 可能有变动
- 跨线程安全是主要稳定性风险，所有 UI 更新必须通过 Timer 回到主线程
