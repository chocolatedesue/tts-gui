# PRD: Edge TTS GUI — UI 重设计

## Problem Statement

当前应用 UI 存在以下问题：
- 播放控制和生成参数耦合在同一页面，概念混乱
- 状态信息（左下角小字）不够醒目，视觉反馈弱
- 左侧导航栏图标过小，辨识度差
- 整体控件字体偏小，占用空间分配不合理
- 窗口不支持自由缩放

## Solution

按"关注点分离"原则重新设计 UI 架构：

- **合成页**精简为：文本输入 + 语音选择 + 生成按钮
- **TTS 参数**（语速/音调/音量）移入 Settings 页
- **播放器**独立为底部固定工具栏，提供运行时播放控制
- **状态通知**改为应用内 Toast 卡片
- 侧栏加大，窗口支持自由缩放

## User Stories

1. As a 用户, I want to 在合成页只看到文本和生成相关的内容, so that 界面不杂乱
2. As a 用户, I want to 底部有一个播放器栏, so that 我能像音乐播放器一样控制音频回放
3. As a 用户, I want to 播放时拖动进度条 seek, so that 我能跳到想听的位置
4. As a 用户, I want to 实时调节播放音量, so that 不用重新生成就能控制听到的声音大小
5. As a 用户, I want to 切换播放倍速(1x/1.5x/2x), so that 我能快速预览长文本
6. As a 用户, I want to 看到当前时间和总时长, so that 我知道播放进度
7. As a 用户, I want to 播放栏始终可见但无音频时灰显, so that 布局稳定且功能位置可预期
8. As a 用户, I want to 操作状态通过 Toast 卡片通知我, so that 我不用盯着角落看小字
9. As a 用户, I want to Toast 成功时绿色、错误时红色、进行中带 spinner, so that 我一眼判断状态
10. As a 用户, I want to Toast 几秒后自动消失, so that 不占用界面空间
11. As a 用户, I want to 侧栏图标更大更清晰, so that 导航容易辨认
12. As a 用户, I want to 自由缩放窗口, so that 我能按自己的屏幕调整大小
13. As a 用户, I want to 所有内容随窗口缩放自适应, so that 放大缩小后布局不破
14. As a 用户, I want to TTS 生成参数在 Settings 页配置, so that 合成页保持简洁
15. As a 用户, I want to 合成页保留语音选择(语言/性别/音色+试听), so that 我能快速切换声音

## Implementation Decisions

- **三区布局架构**: 侧栏(120px) | 内容区 | 底部播放栏。侧栏和播放栏为固定区域，内容区自适应。
- **播放栏组件**: 自定义 Slint component，包含 TouchArea 实现进度条拖动，Slider 做音量控制。播放状态（position, duration, volume, speed）作为 Window 级 property 暴露给 Python。
- **音频 seek 实现**: 将解码后的 PCM samples 保持在内存，seek 时修改播放偏移量（sample index），不重新解码。
- **倍速播放**: 通过 sounddevice 的 samplerate 参数实现（1.5x = samplerate * 1.5），或使用 numpy resample。
- **Toast 系统**: Slint 层用 `if` 条件渲染一个浮动 Rectangle（z-order 最顶），通过 Timer 控制显示/隐藏。Python 端维护 toast message queue。
- **窗口缩放**: 移除 Window 的固定 width/height，改用 min-width/min-height + preferred-width/preferred-height，让布局 stretch 填充。
- **侧栏**: 120px 宽，图标用 Text emoji 放大到 1.4rem，下方配文字标签。
- **合成页精简**: 移除 ParamRow 滑条，只保留文本分栏 + 语音选择行 + 生成按钮。
- **Settings 页重组**: 分为 "语音参数"（语速/音调/音量预设）、"LLM 清洗"、"音频设备" 三个 GroupBox。

## Testing Decisions

- **播放器控制测试**: 验证 play/pause/stop/seek 状态转换正确（生成 → 播放 → seek → 暂停 → 继续 → 停止）
- **倍速测试**: 验证切换倍速后音频播放时长符合预期（2x 应该减半）
- **Toast 测试**: 验证 toast 在 3 秒后自动消失，错误 toast 保持直到关闭
- **布局测试**: 用 `slint-viewer --screenshot` 在不同尺寸下截图对比（通过 Window size 属性设置）
- **缩放测试**: 验证 min-width/min-height 约束生效，内容不溢出

## Out of Scope

- 波形可视化（频谱/波形图）
- 播放列表（多段音频排队）
- 键盘快捷键（空格播放/暂停等）
- 拖拽文件输入
- 系统级通知（macOS Notification Center）

## Further Notes

- 进度条 seek 需要知道总 sample 数和当前播放位置，Python 端需维护一个 `current_frame` 计数器
- Toast 在 Slint 中没有内置组件，需要自定义实现（浮动层 + 动画）
- 倍速播放改变 samplerate 会改变音调（加速变尖），如果要保持音调不变需要 time-stretch 算法（如 rubberband），但对 TTS 场景可以接受变调
- 侧栏未来可扩展：历史记录页、收藏语音页等

## Addendum: Playback Enhancements

- 播放栏新增循环播放按钮（🔁），点击切换：单次 → 循环
- 默认播放倍速设为 1.5x（可在播放栏切换 1x/1.5x/2x）
- 循环播放时音频播完后自动从头开始
