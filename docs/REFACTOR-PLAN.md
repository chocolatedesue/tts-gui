# Refactor Plan: tts_gui 架构深化

## Problem Statement

`app.py` 是一个 380 行的浅层模块，承担 6 个职责（UI 协调、TTS 合成、音频播放、设备管理、LLM 调用、设置持久化）。所有异步操作共享单一 `_result` 变量存在竞态，播放逻辑的 `current_frame` 无锁跨线程读写，progress slider 的双向绑定存在反馈循环 bug。代码不可独立测试。

## Solution

将 TTSApp 从"一个大类做所有事"拆分为 4 个深层模块 + 1 个薄协调层，每个模块有小接口、大实现，可独立测试。

## Dependency Graph & Parallelism

```
                    ┌─────────────────────┐
                    │  #0 Fix seek bug    │  ← 最先做，1 个小 commit
                    └────────┬────────────┘
                             │
       ┌─────────────┬───────┼───────┬──────────────┐
       │             │       │       │              │
       ▼             ▼       ▼       ▼              ▼
 ┌───────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐
 │#1 Task-   │ │#2 Set-  │ │#3 TTS-  │ │#3b His- │ │         │
 │   Runner  │ │  tings  │ │  Engine │ │   tory  │ │ 可并行  │
 └─────┬─────┘ └─────────┘ └────┬────┘ └────┬────┘ │         │
       │                         │            │      └─────────┘
       └────────────┬────────────┘            │
                    ▼                         │
           ┌─────────────────┐               │
           │ #4 AudioPlayer  │               │
           └────────┬────────┘               │
                    │                         │
                    └────────────┬────────────┘
                                ▼
                    ┌─────────────────────┐
                    │  #5 Coordinator     │  ← 最后整合
                    │    (slim TTSApp)    │
                    └─────────────────────┘
```

**可并行的工作：** #1、#2、#3、#3b 之间无依赖，可同时进行。

## Commits (按阶段)

### Phase 0: Bug Fix (独立，无依赖)

**Commit 0.1** — 修复 seek 反馈循环
- 在 `on_seek` 回调中加入 `_seeking` 守卫标志
- Timer poll 中设置 progress 前置 `_seeking = True`，设置后 `_seeking = False`
- `on_seek` 检查：如果 `_seeking` 为 True，直接 return
- 验证：手动播放时 slider 不再触发 restart

---

### Phase 1: TaskRunner 模块 (无依赖)

**Commit 1.1** — 创建 `src/tts_gui/task_runner.py`，定义接口
- 接口：`run(fn, on_success, on_error, timeout_ms=30000) → task_id`
- 接口：`cancel(task_id)`
- 内部用 `queue.Queue` 为每个 task 隔离结果
- 内部用一个 `slint.Timer` 轮询所有活跃 task 的 queue

**Commit 1.2** — 为 TaskRunner 编写单元测试
- 不依赖 UI，mock `slint.Timer` 为手动触发
- 测试：正常完成回调、错误回调、超时、cancel

**Commit 1.3** — 将 `_load_voices_async` 迁移到 TaskRunner
- 删除 `_load_voices_async` 中的手动 timer/poll
- 改为 `self.runner.run(load_voices_fn, self._on_voices_loaded, self._on_voices_error)`
- 确认功能不变

**Commit 1.4** — 将 `on_generate` 的 clean + tts 链迁移到 TaskRunner
- 删除 `poll_clean` 和 `_start_gen_poll` 中的手动 timer
- 改为链式 `runner.run(clean_fn, then_run_tts, ...)`

**Commit 1.5** — 将 `on_preview` 迁移到 TaskRunner，删除 `self._result`

---

### Phase 2: Settings 模块 (无依赖，可与 Phase 1 并行)

**Commit 2.1** — 创建 `src/tts_gui/settings.py`
- 定义 `SCHEMA`: dict 描述 `{key: (ui_property, default, type)}`
- 实现 `load() → dict`、`save(data)`
- 实现 `apply_to(win)` — 遍历 schema 设置 UI 属性
- 实现 `capture_from(win) → dict` — 遍历 schema 读取 UI 属性

**Commit 2.2** — 替换 `__init__` 中 14 行手动赋值 + `on_save_settings` 中 12 行手动读取
- 改为 `settings.apply_to(self.win)` 和 `settings.save(settings.capture_from(self.win))`
- 删除旧的 `load_settings`、`save_settings_to_disk` 自由函数

**Commit 2.3** — Settings 模块测试
- 测试 round-trip：save → load → 数据一致
- 测试 default 填充

---

### Phase 3: TTSEngine 模块 (无依赖，可与 Phase 1/2 并行)

**Commit 3.1** — 创建 `src/tts_gui/tts_engine.py`
- 接口：`list_voices(locale=None, gender=None) → list[VoiceInfo]`
- 接口：`synthesize(text, voice, rate, pitch, volume) → bytes`
- 接口：`clean_text(text, llm_config) → str` (可选步骤)
- 内部封装 edge_tts + httpx

**Commit 3.2** — TTSEngine 测试
- Mock `edge_tts.Communicate`，验证 params 格式化正确
- Mock `httpx.post`，验证 LLM 调用和错误处理
- 测试 `list_voices` 过滤逻辑

**Commit 3.3** — TTSApp 中替换直接 edge_tts 调用为 TTSEngine
- `_run_tts` → `self.engine.synthesize`
- `_load_voices_async` 内部 → `self.engine.list_voices`
- `clean_text_with_llm` → `self.engine.clean_text`
- 删除 TTSApp 中的 `_get_tts_params`、`_apply_filter` 方法体（委托给 engine）

---

### Phase 3b: History 模块 (无依赖，可与 Phase 1/2/3 并行)

**背景：** 代码已引入历史消息功能（`_load_history`, `_save_history_entry`, `on_select_history`, `on_delete_history`, `on_clear_history`, `_refresh_history_list`, `_restore_voice`），约 90 行，管理 `~/.config/tts-gui/history/` 目录下的 index.json + mp3 文件。

**影响分析：**
- History 读写磁盘 I/O（保存 mp3）目前在主线程执行，大文件可能卡 UI
- `on_select_history` 直接设置 `win.*` 属性 + 调用 `_decode_audio`，与 AudioPlayer 提取有交互
- `_save_history_entry` 在 `_start_gen_poll` 内调用，与 `_result` 竞态问题同源
- `_restore_voice` 依赖 `_apply_filter`，后者将移入 TTSEngine

**Commit 3b.1** — 创建 `src/tts_gui/history.py`
- 接口：
  - `load() → list[HistoryEntry]`
  - `save_entry(text, cleaned, audio_bytes, voice_info) → HistoryEntry`
  - `delete(entry_id)`
  - `clear()`
  - `get_audio(entry_id) → bytes`
  - `display_items() → list[dict]` (给 UI ListModel 用)
- 内部管理 HISTORY_DIR / index.json / mp3 文件
- MAX_HISTORY 裁剪逻辑在此模块内

**Commit 3b.2** — History 模块测试
- 使用 tmp_path 做磁盘 IO 测试
- 测试 save → load round-trip
- 测试 MAX_HISTORY 裁剪（旧 mp3 被删除）
- 测试 delete / clear

**Commit 3b.3** — TTSApp 中替换历史逻辑为 History 模块
- 删除 `_load_history`, `_save_history_entry`, `_refresh_history_list`, `on_delete_history`, `on_clear_history` 方法体
- 改为委托 `self.history_store = History()`
- `on_select_history` 仍在协调层（因为它同时操作 AudioPlayer + voice filter）

**与其他 Phase 的交互（需注意）：**
- Phase 4 提取 AudioPlayer 后，`on_select_history` 中的 `_decode_audio` 调用改为 `self.player.load(audio_bytes)`
- Phase 3 提取 TTSEngine 后，`_restore_voice` 的 filter 逻辑改为 `self.engine.list_voices(locale=...)` + UI 同步
- 保存音频时若使用 TaskRunner，可改为异步写磁盘避免卡 UI

---

### Phase 4: AudioPlayer 模块 (依赖 Phase 1 TaskRunner)

**Commit 4.1** — 创建 `src/tts_gui/audio_player.py`
- 接口：
  - `load(audio_bytes: bytes)` — 解码 + 设置 duration
  - `play()` / `pause()` / `stop()`
  - `seek(percent: float)`
  - `set_volume(percent: float)`
  - `set_speed(multiplier: float)`
  - `toggle_loop()`
  - `on_progress: Callable[[float, str, str], None]` — 回调 (progress%, current_time, total_time)
  - `on_finished: Callable[[], None]`
- 内部：
  - `threading.Lock` 保护 `current_frame`
  - 使用 TaskRunner（或内部 timer）更新进度
  - 设备选择作为构造参数

**Commit 4.2** — AudioPlayer 测试
- 用短音频测试 load → play → on_progress 回调触发
- 测试 seek 不触发 restart（seek bug 在模块内部用 guard 处理）
- 测试 volume/speed 切换

**Commit 4.3** — AudioPlayer 整合设备热插拔
- 将 `_query_output_names`、`_refresh_devices` 逻辑移入（或作为 adapter 注入）
- 不再调用 `sd._terminate()` / `sd._initialize()`，改用安全方式

**Commit 4.4** — TTSApp 中替换播放逻辑为 AudioPlayer
- 删除 TTSApp 中 11 个音频方法
- `self.player = AudioPlayer(device=...)`
- UI 回调直接委托：`self.win.play_audio = self.player.play`
- 进度更新通过 `player.on_progress` 回调写入 `win.*`

---

### Phase 5: 最终协调 (依赖 Phase 1-4)

**Commit 5.1** — TTSApp 瘦身为协调层
- 仅保留：UI 绑定、模块初始化、generate/preview 流程编排
- 预计 < 100 行

**Commit 5.2** — 加入清洗/生成计时显示
- `on_generate` 开始记录 `_gen_start = time.perf_counter()`
- clean 回调中计算 `_clean_elapsed`，toast 显示 "清洗完成 Xs"
- tts 回调中计算 `_tts_elapsed`，toast 显示组合耗时
- poll 中实时更新 status 为 "清洗中… Xs" / "生成中… Xs"
- 跳过清洗时 toast 只显示 tts 耗时
- History 记录中写入 `clean_time` / `tts_time`

**Commit 5.3** — 整体冒烟测试
- `uv run python src/tts_gui/app.py` 启动正常
- 生成、播放、设置保存、设备切换、计时显示全流程验证

**Commit 5.4** — Briefcase 构建验证
- `uv run briefcase create macOS && uv run briefcase build macOS`
- 确认打包成功

---

## Decision Document

| 决策 | 选择 | 理由 |
|------|------|------|
| 异步模型 | TaskRunner + queue.Queue + slint.Timer | Slint 要求 UI 更新在主线程，Timer 是唯一安全的回调机制 |
| 播放线程安全 | threading.Lock 保护 current_frame | GIL 不足以保证逻辑正确性，Lock 开销可忽略 |
| 设备热插拔 | 不调用 sd 私有 API，改用 try/except 捕获设备异常 | `sd._terminate()` 是内部实现细节 |
| Settings schema | dict 描述而非 dataclass | 与 JSON 序列化天然对齐，字段少无需类型系统 |
| TTSEngine 是否内含 LLM 清洗 | 是，作为可选步骤 | 调用者只需一次 `synthesize`，清洗是内部逻辑 |
| History 独立模块 | 是，与 TTSEngine 平级 | 历史管理涉及文件 IO + 裁剪策略，值得独立 seam |
| History IO 策略 | 小文件同步，大文件可考虑 TaskRunner 异步 | 当前 mp3 通常 < 500KB，同步写入可接受 |
| on_select_history 归属 | 留在协调层 | 它同时操作 player + engine + UI，是编排逻辑 |
| 模块文件位置 | `src/tts_gui/` 同级 | 项目小，不需要 sub-package |

## Testing Decisions

| 模块 | 测试方式 | 依赖替换 |
|------|---------|---------|
| TaskRunner | 纯 Python 单测，mock slint.Timer | 手动 tick 模拟 timer |
| Settings | 单测，tmpfile 做 IO | 无外部依赖 |
| TTSEngine | 单测，mock edge_tts + httpx | 注入 mock client |
| History | 单测，tmp_path 做文件 IO | 无外部依赖 |
| AudioPlayer | 集成测试，短 PCM 数据 | 可选 mock sounddevice |
| TTSApp (coordinator) | 手动冒烟测试 + briefcase build | 全链路 |

测试原则：
- 测试外部行为（输入 → 输出/回调），不测内部实现
- 每个模块通过其接口测试，不穿透 seam

## Out of Scope

- UI 视觉设计改进（PRD-v2 范畴，不在此重构内）
- 新增功能（批量导出、多段拼接等）
- Slint UI 文件拆分（ui.slint 结构清晰，暂不需要）
- 异步改为 asyncio 主循环（Slint Python bindings 不支持）
- History 页面 UI 改版（当前 UI 已可用，不在此重构范围）

## Feature: 清洗/生成计时显示

### 需求

在生成流程中记录并展示各阶段耗时，帮助用户感知等待进度和性能：
- **清洗耗时** — LLM 文本清洗阶段花费的时间
- **生成耗时** — edge-tts 语音合成阶段花费的时间
- **总耗时** — 从点击生成到完成的总时间

### 显示方案

| 时机 | 显示位置 | 格式 | 示例 |
|------|---------|------|------|
| 清洗完成时 | Toast (info) | "清洗完成 {t}s" | "清洗完成 1.2s" |
| 生成完成时 | Toast (success) | "生成完成 ({size}) 清洗 {t1}s + 生成 {t2}s" | "生成完成 (48.3 KB) 清洗 1.2s + 生成 3.5s" |
| 跳过清洗时 | Toast (success) | "生成完成 ({size}) {t}s" | "生成完成 (48.3 KB) 3.5s" |
| 进行中 | Status bar (侧栏底部) | "清洗中… {elapsed}s" / "生成中… {elapsed}s" | "生成中… 2.1s" |

### 实现归属

此功能在重构中归入 **协调层（app.py）**，因为它跨越 clean + tts 两个阶段：

- 在 `on_generate` 开始时记录 `t0 = time.perf_counter()`
- clean 完成时记录 `t_clean = time.perf_counter() - t0`
- tts 完成时记录 `t_tts = time.perf_counter() - t_after_clean`
- Toast 显示组合信息

### 进行中计时（实时 elapsed）

在生成流程进行中，侧栏 status 实时显示 elapsed 秒数：
- 复用已有的 poll timer（200ms），每次 poll 时更新 `win.status = f"生成中… {elapsed:.1f}s"`
- 流程结束后恢复 status 为 "就绪"

### 与 TaskRunner 的关系

重构后，计时自然融入 TaskRunner 的回调模式：

```python
# 协调层伪代码
self._gen_start = time.perf_counter()
self.runner.run(
    fn=lambda: self.engine.clean_text(text, config),
    on_success=lambda cleaned: self._on_clean_done(cleaned),
    on_error=lambda e: self._on_clean_failed(e, text),
)

def _on_clean_done(self, cleaned):
    self._clean_elapsed = time.perf_counter() - self._gen_start
    self.show_toast(f"清洗完成 {self._clean_elapsed:.1f}s", 0)
    self._tts_start = time.perf_counter()
    self.runner.run(
        fn=lambda: self.engine.synthesize(cleaned, ...),
        on_success=self._on_generated,
    )

def _on_generated(self, audio_bytes):
    t_tts = time.perf_counter() - self._tts_start
    size = len(audio_bytes) / 1024
    self.show_toast(f"生成完成 ({size:.1f} KB) 清洗 {self._clean_elapsed:.1f}s + 生成 {t_tts:.1f}s", 1)
```

### History 中记录耗时

每条历史记录额外保存 `clean_time` 和 `tts_time` 字段：

```python
entry = {
    ...
    "clean_time": 1.2,   # 秒，None 表示跳过清洗
    "tts_time": 3.5,
}
```

历史列表的 subtitle 中展示：`"06-28 13:15 · Yunxi · 4.7s"`（总耗时）

## Target File Structure (After)

```
src/tts_gui/
├── app.py            # 协调层 (~100 lines)
├── audio_player.py   # 播放模块
├── tts_engine.py     # TTS + LLM 合成模块
├── task_runner.py    # 异步任务调度模块
├── settings.py       # 配置持久化模块
├── history.py        # 历史记录管理模块
├── ui.slint          # UI 定义（不变）
├── icons/            # SVG 图标（不变）
├── __init__.py
└── __main__.py
tests/
├── test_task_runner.py
├── test_settings.py
├── test_tts_engine.py
├── test_history.py
└── test_audio_player.py
```
