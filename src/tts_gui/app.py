import asyncio
import io
import threading
from datetime import timedelta
from pathlib import Path
from tkinter import filedialog

import edge_tts
import miniaudio
import numpy as np
import sounddevice as sd
import slint

VOICES = [
    "zh-CN-YunxiNeural",
    "zh-CN-XiaoxiaoNeural",
    "zh-CN-YunyangNeural",
    "zh-CN-YunjianNeural",
    "zh-CN-XiaoyiNeural",
]


def main():
    app_dir = Path(__file__).parent
    ui = slint.load_file(app_dir / "ui.slint")
    win = ui.MainWindow()

    audio_buf = bytearray()
    play_stream = [None]
    result_box = [None]

    def generate(text: str, voice_idx: int, rate: float):
        if not text.strip():
            win.status = "请输入文本"
            return
        win.generating = True
        win.has_audio = False
        win.playing = False
        win.status = "正在生成..."
        result_box[0] = None

        def worker():
            loop = asyncio.new_event_loop()
            try:
                tts = edge_tts.Communicate(text, voice=VOICES[voice_idx], rate=f"{int(rate):+d}%")
                buf = io.BytesIO()

                async def stream():
                    async for chunk in tts.stream():
                        if chunk["type"] == "audio":
                            buf.write(chunk["data"])

                loop.run_until_complete(stream())
                result_box[0] = ("ok", buf.getvalue())
            except Exception as e:
                result_box[0] = ("err", str(e))
            finally:
                loop.close()

        threading.Thread(target=worker, daemon=True).start()

        def poll():
            if result_box[0] is None:
                return
            timer.stop()
            if result_box[0][0] == "ok":
                audio_buf[:] = result_box[0][1]
                win.has_audio = True
                size_kb = len(audio_buf) / 1024
                win.status = f"生成完成 ({size_kb:.1f} KB)，可播放或保存"
            else:
                win.status = f"错误: {result_box[0][1]}"
            win.generating = False
            result_box[0] = None

        timer = slint.Timer()
        timer.start(slint.TimerMode.Repeated, timedelta(milliseconds=200), poll)

    def play_audio():
        if not audio_buf:
            return
        stop_audio()
        try:
            decoded = miniaudio.decode(bytes(audio_buf), output_format=miniaudio.SampleFormat.SIGNED16)
            samples = np.frombuffer(decoded.samples, dtype=np.int16).reshape(-1, decoded.nchannels)

            def finished_cb():
                slint.invoke_from_event_loop(lambda: setattr(win, 'playing', False))

            # Try invoke_from_event_loop, fall back to timer
            try:
                slint.invoke_from_event_loop
                use_invoke = True
            except AttributeError:
                use_invoke = False

            def on_finish():
                if use_invoke:
                    slint.invoke_from_event_loop(lambda: setattr(win, 'playing', False))
                else:
                    win.playing = False

            play_stream[0] = sd.OutputStream(
                samplerate=decoded.sample_rate,
                channels=decoded.nchannels,
                dtype='int16',
                blocksize=4096,
            )
            play_stream[0].start()

            # Play in a thread to not block
            def play_worker():
                stream = play_stream[0]
                chunk_size = 4096
                for i in range(0, len(samples), chunk_size):
                    if stream is None or not stream.active:
                        break
                    chunk = samples[i:i + chunk_size]
                    stream.write(chunk)
                # Done
                win.playing = False

            win.playing = True
            threading.Thread(target=play_worker, daemon=True).start()
        except Exception as e:
            win.status = f"播放错误: {e}"

    def stop_audio():
        if play_stream[0] is not None:
            play_stream[0].abort()
            play_stream[0].close()
            play_stream[0] = None
        win.playing = False

    def save_audio():
        if not audio_buf:
            return

        def do_save():
            import tkinter as tk
            root = tk.Tk()
            root.withdraw()
            path = filedialog.asksaveasfilename(
                defaultextension=".mp3",
                filetypes=[("MP3 文件", "*.mp3"), ("所有文件", "*.*")],
                initialfile="tts_output.mp3",
            )
            root.destroy()
            if path:
                with open(path, "wb") as f:
                    f.write(audio_buf)
                win.status = f"已保存: {path}"

        threading.Thread(target=do_save, daemon=True).start()

    win.generate = generate
    win.play_audio = play_audio
    win.stop_audio = stop_audio
    win.save_audio = save_audio
    win.run()
