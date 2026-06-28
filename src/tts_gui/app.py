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

SPEED_OPTIONS = [("1x", 1.0), ("1.5x", 1.5), ("2x", 2.0)]
BASE_SAMPLERATE = 44100


def load_settings() -> dict:
    if SETTINGS_FILE.exists():
        return json.loads(SETTINGS_FILE.read_text())
    return {}


def save_settings_to_disk(data: dict):
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


def format_time(seconds: float) -> str:
    s = max(0, int(seconds))
    return f"{s // 60}:{s % 60:02d}"


class TTSApp:
    def __init__(self):
        self.app_dir = Path(__file__).parent
        self.ui = slint.load_file(self.app_dir / "ui.slint")
        self.win = self.ui.MainWindow()

        self.all_voices = []
        self.filtered_voices = []
        self.audio_buf = bytearray()

        # Audio playback state
        self.pcm_samples: np.ndarray | None = None
        self.pcm_samplerate: int = BASE_SAMPLERATE
        self.pcm_channels: int = 1
        self.current_frame: int = 0
        self.total_frames: int = 0
        self.play_stream: sd.OutputStream | None = None
        self.player_volume: float = 0.8
        self.speed_index: int = 0
        self.output_device = None

        self._result = None
        self._toast_timer: slint.Timer | None = None
        self._player_timer: slint.Timer | None = None

        # Load saved settings
        settings = load_settings()
        if settings:
            self.win.api_url = settings.get("api_url", "")
            self.win.api_key = settings.get("api_key", "")
            self.win.api_model = settings.get("api_model", "")
            self.win.clean_prompt = settings.get("clean_prompt", DEFAULT_CLEAN_PROMPT)
            self.win.rate_value = settings.get("rate", 0)
            self.win.pitch_value = settings.get("pitch", 0)
            self.win.volume_value = settings.get("volume", 0)
            self.win.clean_enabled = settings.get("clean_enabled", True)
            self.win.player_volume = settings.get("player_volume", 80)
            self.player_volume = settings.get("player_volume", 80) / 100.0
        else:
            self.win.clean_prompt = DEFAULT_CLEAN_PROMPT

        # Populate audio devices
        self._init_audio_devices(settings.get("device_index", 0))

        # Bind callbacks
        self.win.generate = self.on_generate
        self.win.play_audio = self.on_play
        self.win.pause_audio = self.on_pause
        self.win.stop_audio = self.on_stop
        self.win.seek_audio = self.on_seek
        self.win.set_volume = self.on_set_volume
        self.win.cycle_speed = self.on_cycle_speed
        self.win.preview_voice = self.on_preview
        self.win.filter_changed = self.on_filter_changed
        self.win.save_settings = self.on_save_settings
        self.win.dismiss_toast = self.on_dismiss_toast

        self._load_voices_async()

    # --- Toast system ---

    def show_toast(self, message: str, toast_type: int = 0):
        """toast_type: 0=info, 1=success, 2=error"""
        self.win.toast_message = message
        self.win.toast_type = toast_type
        self.win.toast_visible = True
        if self._toast_timer is not None:
            self._toast_timer.stop()
        self._toast_timer = slint.Timer()
        self._toast_timer.start(slint.TimerMode.SingleShot, timedelta(seconds=3), self._hide_toast)

    def _hide_toast(self):
        self.win.toast_visible = False

    def on_dismiss_toast(self):
        self.win.toast_visible = False
        if self._toast_timer is not None:
            self._toast_timer.stop()

    # --- Settings ---

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
            "player_volume": self.win.player_volume,
        }
        save_settings_to_disk(data)
        self.show_toast("设置已保存", 1)

    # --- Audio devices ---

    def _init_audio_devices(self, saved_idx: int = 0):
        devices = sd.query_devices()
        self._output_devices = []
        names = ["系统默认"]
        for i, d in enumerate(devices):
            if d["max_output_channels"] > 0:
                self._output_devices.append(i)
                names.append(d["name"])
        self.win.device_list = slint.ListModel(names)
        if saved_idx < len(names):
            self.win.current_device_index = saved_idx
        self._update_output_device(saved_idx)

    def _update_output_device(self, idx: int):
        if idx == 0:
            self.output_device = None
        else:
            dev_idx = idx - 1
            if dev_idx < len(self._output_devices):
                self.output_device = self._output_devices[dev_idx]

    # --- Voice loading ---

    def _load_voices_async(self):
        self.win.status = "正在加载语音列表..."
        self._result = None

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

        timer = slint.Timer()

        def poll():
            if self._result is None:
                return
            timer.stop()
            if self._result[0] == "voices_loaded":
                langs = sorted(set(v["Locale"] for v in self.all_voices))
                self.win.lang_list = slint.ListModel(["全部"] + langs)
                try:
                    zh_idx = (["全部"] + langs).index("zh-CN")
                    self.win.current_lang_index = zh_idx
                except ValueError:
                    zh_idx = 0
                self._apply_filter(zh_idx, 0)
                self.win.status = "就绪"
                self.show_toast(f"已加载 {len(self.all_voices)} 个语音", 1)
            else:
                self.show_toast(f"加载语音失败: {self._result[1]}", 2)
                self.win.status = "加载失败"
            self._result = None

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
        display = [
            f"{v['ShortName'].split('-', 2)[-1].replace('Neural', '')} ({v['Gender'][0]})"
            for v in filtered
        ]
        self.win.voice_display_list = slint.ListModel(display if display else ["无匹配语音"])
        self.win.current_voice_index = 0

    def on_filter_changed(self, lang_idx: int, gender_idx: int):
        self._apply_filter(lang_idx, gender_idx)

    # --- TTS params ---

    def _get_tts_params(self):
        rate = int(self.win.rate_value)
        pitch = int(self.win.pitch_value)
        volume = int(self.win.volume_value)
        voice = (
            self.filtered_voices[self.win.current_voice_index]["ShortName"]
            if self.filtered_voices
            else "zh-CN-YunxiNeural"
        )
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

    # --- Generate ---

    def on_generate(self, text: str):
        if not text.strip():
            self.show_toast("请输入文本", 2)
            return
        self.win.generating = True
        self.win.has_audio = False
        self.win.cleaned_text = ""
        self.on_stop()

        if self.win.clean_enabled:
            self.show_toast("正在清洗文本...", 0)
            self.win.status = "清洗中..."
            self._result = None

            api_url = self.win.api_url
            api_key = self.win.api_key
            api_model = self.win.api_model
            prompt = self.win.clean_prompt or DEFAULT_CLEAN_PROMPT

            def clean_worker():
                try:
                    cleaned = clean_text_with_llm(text, api_url, api_key, api_model, prompt)
                    self._result = ("cleaned", cleaned)
                except Exception as e:
                    self._result = ("clean_err", str(e))

            threading.Thread(target=clean_worker, daemon=True).start()

            clean_timer = slint.Timer()

            def poll_clean():
                if self._result is None:
                    return
                clean_timer.stop()
                if self._result[0] == "cleaned":
                    cleaned = self._result[1]
                    self.win.cleaned_text = cleaned
                    self.win.status = "生成中..."
                    self.show_toast("正在生成语音...", 0)
                    self._result = None
                    self._run_tts(cleaned, "generated")
                    self._start_gen_poll()
                else:
                    self.show_toast(f"清洗失败，使用原文", 2)
                    self.win.cleaned_text = text
                    self._result = None
                    self.win.status = "生成中..."
                    self._run_tts(text, "generated")
                    self._start_gen_poll()

            clean_timer.start(slint.TimerMode.Repeated, timedelta(milliseconds=200), poll_clean)
        else:
            self.win.cleaned_text = text
            self.win.status = "生成中..."
            self.show_toast("正在生成语音...", 0)
            self._run_tts(text, "generated")
            self._start_gen_poll()

    def _start_gen_poll(self):
        gen_timer = slint.Timer()

        def poll():
            if self._result is None:
                return
            gen_timer.stop()
            if self._result[0] == "generated":
                self.audio_buf[:] = self._result[1]
                self._decode_audio()
                self.win.has_audio = True
                self.win.status = "就绪"
                self.show_toast(f"生成完成 ({len(self.audio_buf) / 1024:.1f} KB)", 1)
            else:
                self.win.status = "生成失败"
                self.show_toast(f"生成失败: {self._result[1]}", 2)
            self.win.generating = False
            self._result = None

        gen_timer.start(slint.TimerMode.Repeated, timedelta(milliseconds=200), poll)

    # --- Preview ---

    def on_preview(self):
        self.win.generating = True
        self.show_toast("试听生成中...", 0)
        self._run_tts("你好，这是语音试听。Hello, this is a voice preview.", "preview")

        timer = slint.Timer()

        def poll():
            if self._result is None:
                return
            timer.stop()
            self.win.generating = False
            if self._result[0] == "preview":
                self.audio_buf[:] = self._result[1]
                self._decode_audio()
                self.win.has_audio = True
                self.show_toast("试听播放中...", 1)
                self._start_playback()
            else:
                self.show_toast(f"试听失败: {self._result[1]}", 2)
            self._result = None

        timer.start(slint.TimerMode.Repeated, timedelta(milliseconds=200), poll)

    # --- Audio decode ---

    def _decode_audio(self):
        """Decode MP3 bytes in audio_buf to PCM samples."""
        decoded = miniaudio.decode(bytes(self.audio_buf), output_format=miniaudio.SampleFormat.SIGNED16)
        self.pcm_samplerate = decoded.sample_rate
        self.pcm_channels = decoded.nchannels
        self.pcm_samples = np.frombuffer(decoded.samples, dtype=np.int16).reshape(-1, decoded.nchannels)
        self.total_frames = len(self.pcm_samples)
        self.current_frame = 0
        # Update total time display
        total_sec = self.total_frames / self.pcm_samplerate
        self.win.player_total_time = format_time(total_sec)
        self.win.player_current_time = "0:00"
        self.win.player_progress = 0.0

    # --- Playback with seek/pause/resume ---

    def _start_playback(self):
        """Start or resume playback from current_frame."""
        if self.pcm_samples is None:
            return
        self._stop_stream()
        self._update_output_device(self.win.current_device_index)

        _, speed = SPEED_OPTIONS[self.speed_index]
        effective_rate = int(BASE_SAMPLERATE * speed)

        self.play_stream = sd.OutputStream(
            samplerate=effective_rate,
            channels=self.pcm_channels,
            dtype="int16",
            blocksize=4096,
            device=self.output_device,
        )
        self.play_stream.start()
        self.win.playing = True

        def play_worker():
            stream = self.play_stream
            samples = self.pcm_samples
            vol = self.player_volume
            while self.current_frame < self.total_frames:
                if stream is None or not stream.active or stream != self.play_stream:
                    return
                end = min(self.current_frame + 4096, self.total_frames)
                chunk = samples[self.current_frame:end].astype(np.float32)
                chunk = (chunk * vol).clip(-32768, 32767).astype(np.int16)
                try:
                    stream.write(chunk)
                except Exception:
                    return
                self.current_frame = end
                vol = self.player_volume  # re-read volume each block

        threading.Thread(target=play_worker, daemon=True).start()
        self._start_player_timer()

    def _start_player_timer(self):
        """Poll playback progress and update UI properties."""
        if self._player_timer is not None:
            self._player_timer.stop()
        self._player_timer = slint.Timer()

        def poll():
            if self.pcm_samples is None or self.total_frames == 0:
                return
            progress = (self.current_frame / self.total_frames) * 100.0
            self.win.player_progress = progress
            _, speed = SPEED_OPTIONS[self.speed_index]
            current_sec = self.current_frame / (self.pcm_samplerate * speed)
            self.win.player_current_time = format_time(current_sec)
            # Check if playback finished
            if self.current_frame >= self.total_frames and self.win.playing:
                self.win.playing = False
                self._stop_stream()
                self.current_frame = 0
                self.win.player_progress = 0.0
                self.win.player_current_time = "0:00"

        self._player_timer.start(slint.TimerMode.Repeated, timedelta(milliseconds=200), poll)

    def _stop_stream(self):
        if self.play_stream is not None:
            try:
                self.play_stream.abort()
                self.play_stream.close()
            except Exception:
                pass
            self.play_stream = None

    def on_play(self):
        if self.pcm_samples is None:
            return
        self._start_playback()

    def on_pause(self):
        """Pause: stop stream but keep current_frame position."""
        self._stop_stream()
        self.win.playing = False

    def on_stop(self):
        self._stop_stream()
        self.win.playing = False
        self.current_frame = 0
        if self.pcm_samples is not None:
            self.win.player_progress = 0.0
            self.win.player_current_time = "0:00"

    def on_seek(self, value: float):
        """Seek to position (0-100)."""
        if self.pcm_samples is None:
            return
        self.current_frame = int((value / 100.0) * self.total_frames)
        self.current_frame = max(0, min(self.current_frame, self.total_frames - 1))
        # If playing, restart from new position
        if self.win.playing:
            self._start_playback()

    def on_set_volume(self, value: float):
        """Set playback volume (0-100)."""
        self.player_volume = value / 100.0

    def on_cycle_speed(self):
        """Cycle through speed options."""
        self.speed_index = (self.speed_index + 1) % len(SPEED_OPTIONS)
        label, _ = SPEED_OPTIONS[self.speed_index]
        self.win.player_speed_label = label
        # If playing, restart with new speed
        if self.win.playing:
            self._start_playback()

    # --- Run ---

    def run(self):
        self.win.run()


def main():
    app = TTSApp()
    app.run()
