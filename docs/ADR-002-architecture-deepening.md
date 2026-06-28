# ADR-002: 架构深化 — 拆分 TTSApp 为 4 个深层模块

## Status: Accepted

## Context

`app.py` 中 TTSApp 类是一个 380 行的浅层模块，接口几乎等于实现。所有异步操作共享单一 `_result` 字段，存在竞态。音频播放的 `current_frame` 无锁跨线程读写。代码不可独立测试。

## Decision

将 TTSApp 拆分为 4 个独立模块 + 1 个薄协调层：

1. **TaskRunner** — 统一异步任务调度，每个 task 有独立 result channel
2. **Settings** — 配置 schema + 序列化 + UI 映射
3. **TTSEngine** — edge-tts 合成 + LLM 清洗封装
4. **AudioPlayer** — 音频解码/播放/seek/volume/speed/loop

TTSApp 退化为协调层：仅做 UI 绑定和模块间编排。

## Consequences

- 每个模块可独立单元测试
- 播放竞态问题在 AudioPlayer 内部用 Lock 解决
- `_result` 竞态被 TaskRunner 的 per-task queue 消除
- 新增 4 个文件 + 1 个 tests/ 目录
- app.py 从 380 行降至 ~80 行
