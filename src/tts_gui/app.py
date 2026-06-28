import asyncio
import io
import json
import threading
from datetime import timedelta
from pathlib import Path

import edge_tts
import httpx
import miniaudio
import numpy as np
import sounddevice as sd
import slint

GENDER_MAP = {"全部": None, "男": "Male", "女": "Female"}

DEFAULT_CLEAN_PROMPT = "将文本转换为适合TTS朗读的纯文本：移除markdown格式、语气词、口头禅，使句子通顺，保留核心内容。只输出结果。"

SETTINGS_FILE = Path.home() / ".config" / "tts-gui" / "settings.json"


def load_settings() -> dict:
    if SETTINGS_FILE.exists():
        return json.loads(SETTINGS_FILE.read_text())
    return {}


def save_settings(data: dict):
    SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2))


def clean_text_with_llm(text: str, base_url: str, api_key: str, model: str, prompt: str) -> str:
    resp = httpx.post(
        f"{base_url}/chat/completions",
        headers={"Authorization": f"Bearer {api_key}"},
        json={
            "model": model,
            "messages": [
                {"role": "system", "content": prompt},
                {"role": "user", "content": text},
            ],
            "temperature": 0.3,
        },
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"].strip()


class TTSApp:
    def __init__(self):
        self.app_dir = Path(__file__).parent
        self.ui = slint.load_file(self.app_dir / "ui.slint")
        self.win = self.ui.MainWindow()

        self.all_voices = []
        self.filtered_voices = []
        self.audio_buf = bytearray()
        self.play_stream = None
        self._result = None
        self._play_done = False
        self.output_device = None  # None = system default

        # Load saved settings
        settings = load_settings()
        if settings:
            self.win.api_url = settings.get("api_url", self.win.api_url)
            self.win.api_key = settings.get("api_key", self.win.api_key)
            self.win.api_model = settings.get("api_model", self.win.api_model)
            self.win.clean_prompt = settings.get("clean_prompt", self.win.clean_prompt)
            self.win.rate_value = settings.get("rate", 0)
            self.win.pitch_value = settings.get("pitch", 0)
            self.win.volume_value = settings.get("volume", 0)
            self.win.clean_enabled = settings.get("clean_enabled", True)

        # Populate audio devices
        self._init_audio_devices(settings.get("device_index", 0))

        # Bind callbacks
        self.win.generate = self.on_generate
        self.win.play_audio = self.on_play
        self.win.stop_audio = self.on_stop
        self.win.save_audio = self.on_save
        self.win.preview_voice = self.on_preview
        self.win.filter_changed = self.on_filter_changed
        self.win.save_settings = self.on_save_settings
        self.win.device_changed = self.on_device_changed

        self._load_voices_async()

    def on_save_settings(self):
        data = {
            "api_url": self.win.api_url,
            "api_key": self.win.api_key,
            "api_model": self.win.api_model,
            "clean_prompt": self.win.clean_prompt,
            "rate": self.win.rate_value,
            "pitch": self.win.pitch_value,
            "volume": self.win.volume_value,
            "clean_enabled": self.win.clean_enabled,
            "device_index": self.win.current_device_index,
        }
        save_settings(data)
        self.win.status = "设置已保存"

    def _init_audio_devices(self, saved_idx: int = 0):
        devices = sd.query_devices()
        self._output_devices = []  # list of (device_index, name)
        names = ["系统默认"]
        for i, d in enumerate(devices):
            if d["max_output_channels"] > 0:
                self._output_devices.append(i)
                names.append(d["name"])
        self.win.device_list = slint.ListModel(names)
        if saved_idx < len(names):
            self.win.current_device_index = saved_idx
        self.on_device_changed(self.win.current_device_index)

    def on_device_changed(self, idx: int):
        if idx == 0:
            self.output_device = None  # system default
        else:
            dev_idx = idx - 1
            if dev_idx < len(self._output_devices):
                self.output_device = self._output_devices[dev_idx]

    def _load_voices_async(self):
        self.win.status = "正在加载语音列表..."

        def worker():
            loop = asyncio.new_event_loop()
            try:
                voices = loop.run_until_complete(edge_tts.VoicesManager.create())
                self.all_voices = sorted(voices.voices, key=lambda v: v["Locale"])
                self._result = ("voices_loaded", None)
            except Exception as e:
                self._result = ("err", str(e))
            finally:
                loop.close()

        threading.Thread(target=worker, daemon=True).start()

        def poll():
            if self._result is None:
                return
            timer.stop()
            if self._result[0] == "voices_loaded":
                langs = sorted(set(v["Locale"] for v in self.all_voices))
                self.win.lang_list = slint.ListModel(["全部"] + langs)
                # Default to zh-CN
                try:
                    zh_idx = (["全部"] + langs).index("zh-CN")
                    self.win.current_lang_index = zh_idx
                except ValueError:
                    zh_idx = 0
                self._apply_filter(zh_idx, 0)
                self.win.status = f"已加载 {len(self.all_voices)} 个语音"
            else:
                self.win.status = f"加载失败: {self._result[1]}"
            self._result = None

        timer = slint.Timer()
        timer.start(slint.TimerMode.Repeated, timedelta(milliseconds=200), poll)

    def _apply_filter(self, lang_idx: int, gender_idx: int):
        langs = list(self.win.lang_list)
        lang = langs[lang_idx] if lang_idx < len(langs) else "全部"
        gender_keys = list(GENDER_MAP.keys())
        gender = GENDER_MAP[gender_keys[gender_idx]] if gender_idx < len(gender_keys) else None

        filtered = self.all_voices
        if lang != "全部":
            filtered = [v for v in filtered if v["Locale"] == lang]
        if gender:
            filtered = [v for v in filtered if v["Gender"] == gender]

        self.filtered_voices = filtered
        display = [f"{v['ShortName'].split('-', 2)[-1].replace('Neural', '')} ({v['Gender'][0]})" for v in filtered]
        self.win.voice_display_list = slint.ListModel(display if display else ["无匹配语音"])
        self.win.current_voice_index = 0

    def on_filter_changed(self, lang_idx: int, gender_idx: int):
        self._apply_filter(lang_idx, gender_idx)

    def _get_tts_params(self):
        rate = int(self.win.rate_value)
        pitch = int(self.win.pitch_value)
        volume = int(self.win.volume_value)
        voice = self.filtered_voices[self.win.current_voice_index]["ShortName"] if self.filtered_voices else "zh-CN-YunxiNeural"
        return voice, f"{rate:+d}%", f"{pitch:+d}Hz", f"{volume:+d}%"

    def _run_tts(self, text: str, callback_key: str):
        self._result = None
        voice, rate, pitch, volume = self._get_tts_params()

        def worker():
            loop = asyncio.new_event_loop()
            try:
                tts = edge_tts.Communicate(text, voice=voice, rate=rate, pitch=pitch, volume=volume)
                buf = io.BytesIO()

                async def stream():
                    async for chunk in tts.stream():
                        if chunk["type"] == "audio":
                            buf.write(chunk["data"])

                loop.run_until_complete(stream())
                self._result = (callback_key, buf.getvalue())
            except Exception as e:
                self._result = ("err", str(e))
            finally:
                loop.close()

        threading.Thread(target=worker, daemon=True).start()

    def on_generate(self, text: str):
        if not text.strip():
            self.win.status = "请输入文本"
            return
        self.win.generating = True
        self.win.has_audio = False
        self.win.cleaned_text = ""

        if self.win.clean_enabled:
            self.win.status = "正在清洗文本..."
            self._result = None

            api_url = self.win.api_url
            api_key = self.win.api_key
            api_model = self.win.api_model
            prompt = self.win.clean_prompt

            def clean_worker():
                try:
                    cleaned = clean_text_with_llm(text, api_url, api_key, api_model, prompt)
                    self._result = ("cleaned", cleaned)
                except Exception as e:
                    self._result = ("clean_err", str(e))

            threading.Thread(target=clean_worker, daemon=True).start()

            def poll_clean():
                if self._result is None:
                    return
                clean_timer.stop()
                if self._result[0] == "cleaned":
                    cleaned = self._result[1]
                    self.win.cleaned_text = cleaned
                    self.win.status = "正在生成语音..."
                    self._result = None
                    self._run_tts(cleaned, "generated")
                    self._start_gen_poll()
                else:
                    self.win.status = f"清洗失败: {self._result[1]}，使用原文"
                    self.win.cleaned_text = text
                    self._result = None
                    self._run_tts(text, "generated")
                    self._start_gen_poll()

            clean_timer = slint.Timer()
            clean_timer.start(slint.TimerMode.Repeated, timedelta(milliseconds=200), poll_clean)
        else:
            self.win.cleaned_text = text
            self.win.status = "正在生成语音..."
            self._run_tts(text, "generated")
            self._start_gen_poll()

    def _start_gen_poll(self):
        def poll():
            if self._result is None:
                return
            gen_timer.stop()
            if self._result[0] == "generated":
                self.audio_buf[:] = self._result[1]
                self.win.has_audio = True
                self.win.status = f"生成完成 ({len(self.audio_buf)/1024:.1f} KB)"
            else:
                self.win.status = f"错误: {self._result[1]}"
            self.win.generating = False
            self._result = None

        gen_timer = slint.Timer()
        gen_timer.start(slint.TimerMode.Repeated, timedelta(milliseconds=200), poll)

    def on_preview(self):
        self.win.generating = True
        self.win.status = "试听中..."
        self._run_tts("你好，这是语音试听。Hello, this is a voice preview.", "preview")

        def poll():
            if self._result is None:
                return
            timer.stop()
            self.win.generating = False
            if self._result[0] == "preview":
                self._play_bytes(self._result[1])
                self.win.status = "试听播放中..."
            else:
                self.win.status = f"试听失败: {self._result[1]}"
            self._result = None

        timer = slint.Timer()
        timer.start(slint.TimerMode.Repeated, timedelta(milliseconds=200), poll)

    def _play_bytes(self, data: bytes):
        self.on_stop()
        try:
            decoded = miniaudio.decode(data, output_format=miniaudio.SampleFormat.SIGNED16)
            samples = np.frombuffer(decoded.samples, dtype=np.int16).reshape(-1, decoded.nchannels)
            self.play_stream = sd.OutputStream(
                samplerate=decoded.sample_rate, channels=decoded.nchannels, dtype="int16", blocksize=4096,
                device=self.output_device,
            )
            self.play_stream.start()
            self.win.playing = True
            self._play_done = False

            def play_worker():
                stream = self.play_stream
                for i in range(0, len(samples), 4096):
                    if stream is None or not stream.active:
                        break
                    stream.write(samples[i : i + 4096])
                self._play_done = True

            threading.Thread(target=play_worker, daemon=True).start()

            # Poll for playback completion on main thread
            def poll_play():
                if not self._play_done:
                    return
                play_timer.stop()
                self.win.playing = False

            play_timer = slint.Timer()
            play_timer.start(slint.TimerMode.Repeated, timedelta(milliseconds=300), poll_play)
        except Exception as e:
            self.win.status = f"播放错误: {e}"

    def on_play(self):
        if self.audio_buf:
            self._play_bytes(bytes(self.audio_buf))

    def on_stop(self):
        if self.play_stream is not None:
            self.play_stream.abort()
            self.play_stream.close()
            self.play_stream = None
        self.win.playing = False

    def on_save(self):
        if not self.audio_buf:
            return

        def do_save():
            import subprocess, sys
            if sys.platform == "darwin":
                # Use osascript for file dialog (thread-safe on macOS)
                script = 'tell application "System Events" to set f to POSIX path of (choose file name with prompt "保存语音文件" default name "tts_output.mp3")'
                r = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
                path = r.stdout.strip()
            else:
                import tkinter as tk
                from tkinter import filedialog
                root = tk.Tk()
                root.withdraw()
                path = filedialog.asksaveasfilename(
                    defaultextension=".mp3",
                    filetypes=[("MP3 文件", "*.mp3")],
                    initialfile="tts_output.mp3",
                )
                root.destroy()

            if path:
                if not path.endswith(".mp3"):
                    path += ".mp3"
                with open(path, "wb") as f:
                    f.write(self.audio_buf)
                self.win.status = f"已保存: {path}"

        threading.Thread(target=do_save, daemon=True).start()

    def run(self):
        self.win.run()


def main():
    app = TTSApp()
    app.run()
