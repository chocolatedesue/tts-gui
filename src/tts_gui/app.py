import time
from datetime import timedelta
from pathlib import Path

import sounddevice as sd
import slint

from tts_gui import settings
from tts_gui.audio_player import AudioPlayer
from tts_gui.history import History
from tts_gui.task_runner import TaskRunner
from tts_gui.tts_engine import TTSEngine

GENDER_MAP = {"全部": None, "男": "Male", "女": "Female"}


class TTSApp:
    def __init__(self):
        self.app_dir = Path(__file__).parent
        self.ui = slint.load_file(self.app_dir / "ui.slint")
        self.win = self.ui.MainWindow()

        self.engine = TTSEngine()
        self.runner = TaskRunner()
        self.history = History()
        self.player = AudioPlayer()

        self.all_voices: list[dict] = []
        self.filtered_voices: list[dict] = []

        self._updating_progress = False
        self._toast_timer: slint.Timer | None = None
        self._gen_start: float = 0
        self._clean_elapsed: float = 0
        self._last_input_text: str = ""
        self._current_entry_id: str | None = None

        # Load & apply settings
        cfg = settings.load()
        settings.apply_to(self.win, cfg)
        self.player.set_volume(cfg.get("player_volume", 80))
        self._init_audio_devices(cfg.get("device_index", 0))

        # Default speed
        self.win.player_speed_label = self.player.speed_label

        # Player callbacks
        self.player.on_progress = self._on_player_progress
        self.player.on_state_changed = self._on_player_state
        self.player.on_finished = self._on_player_finished

        # Bind UI callbacks
        self.win.generate = self.on_generate
        self.win.play_audio = lambda: self.player.play()
        self.win.pause_audio = lambda: self.player.pause()
        self.win.stop_audio = lambda: self.player.stop()
        self.win.seek_audio = self.on_seek
        self.win.set_volume = self._on_set_volume
        self.win.cycle_speed = self._on_cycle_speed
        self.win.toggle_loop = self._on_toggle_loop
        self.win.preview_voice = self.on_preview
        self.win.export_audio = self._on_export_audio
        self.win.filter_changed = self._apply_filter
        self.win.save_settings = self._on_save_settings
        self.win.dismiss_toast = self._dismiss_toast
        self.win.select_history = self.on_select_history
        self.win.delete_history = lambda idx: (self.history.delete(self.history.entries[idx]["id"]) if 0 <= idx < len(self.history.entries) else None, self._refresh_history())
        self.win.clear_history = lambda: (self.history.clear(), self._refresh_history())

        self._refresh_history()
        self._load_voices()

        # Device hot-plug
        self._device_timer = slint.Timer()
        self._device_timer.start(slint.TimerMode.Repeated, timedelta(milliseconds=2000), self._refresh_devices)

    # --- Voices ---

    def _load_voices(self):
        self.win.status = "正在加载语音列表..."
        self.runner.run(
            fn=lambda: self.engine.list_voices(),
            on_success=self._on_voices_loaded,
            on_error=lambda e: (self.show_toast(f"加载语音失败: {e}", 2), setattr(self.win, "status", "加载失败")),
        )

    def _on_voices_loaded(self, voices):
        self.all_voices = sorted(voices, key=lambda v: v["Locale"])
        langs = sorted(set(v["Locale"] for v in self.all_voices))
        self.win.lang_list = slint.ListModel(["全部"] + langs)
        try:
            zh_idx = (["全部"] + langs).index("zh-CN")
        except ValueError:
            zh_idx = 0
        self.win.current_lang_index = zh_idx
        self._apply_filter(zh_idx, 0)
        self.win.status = "就绪"
        self.show_toast(f"已加载 {len(self.all_voices)} 个语音", 1)

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
        self.win.voice_display_list = slint.ListModel(display or ["无匹配语音"])
        self.win.current_voice_index = 0

    # --- Generate ---

    def on_generate(self, text: str):
        if not text.strip():
            self.show_toast("请输入文本", 2)
            return
        self._last_input_text = text
        self._gen_start = time.perf_counter()
        self._clean_elapsed = 0
        self.win.generating = True
        self.win.has_audio = False
        self.win.cleaned_text = ""
        self.player.stop()

        if self.win.clean_enabled:
            self.win.status = "清洗中…"
            api_url = self.win.api_url
            api_key = self.win.api_key
            api_model = self.win.api_model
            prompt = self.win.clean_prompt or settings.DEFAULT_CLEAN_PROMPT
            self.runner.run(
                fn=lambda: self.engine.clean_text(text, api_url, api_key, api_model, prompt),
                on_success=self._on_cleaned,
                on_error=lambda e: self._on_clean_failed(e, text),
            )
        else:
            self.win.cleaned_text = text
            self._do_synthesize(text)

    def _on_cleaned(self, cleaned: str):
        self._clean_elapsed = time.perf_counter() - self._gen_start
        self.win.cleaned_text = cleaned
        self.show_toast(f"清洗完成 {self._clean_elapsed:.1f}s", 0)
        self._do_synthesize(cleaned)

    def _on_clean_failed(self, err, original_text: str):
        self._clean_elapsed = 0
        self.show_toast("清洗失败，使用原文", 2)
        self.win.cleaned_text = original_text
        self._do_synthesize(original_text)

    def _do_synthesize(self, text: str):
        self.win.status = "生成中…"
        voice, rate, pitch, volume = self._get_tts_params()
        tts_start = time.perf_counter()
        self.runner.run(
            fn=lambda: self.engine.synthesize(text, voice, rate, pitch, volume),
            on_success=lambda audio: self._on_generated(audio, tts_start),
            on_error=lambda e: self._on_gen_failed(e),
        )

    def _on_generated(self, audio_bytes: bytes, tts_start: float):
        tts_elapsed = time.perf_counter() - tts_start
        self.player.load(audio_bytes)
        self.win.has_audio = True
        self.win.player_total_time = self.player.total_time
        self.win.player_progress = 0.0
        self.win.player_current_time = "0:00"
        self.win.generating = False
        self.win.status = "就绪"

        # Toast with timing
        size_kb = len(audio_bytes) / 1024
        if self._clean_elapsed > 0:
            self.show_toast(f"生成完成 ({size_kb:.1f} KB) 清洗 {self._clean_elapsed:.1f}s + 生成 {tts_elapsed:.1f}s", 1)
        else:
            self.show_toast(f"生成完成 ({size_kb:.1f} KB) {tts_elapsed:.1f}s", 1)

        # Save history
        try:
            v = self.filtered_voices[self.win.current_voice_index]
            vsn, vd = v["ShortName"], v["ShortName"].split("-", 2)[-1].replace("Neural", "")
        except Exception:
            vsn, vd = "zh-CN-YunxiNeural", "Yunxi"
        self.history.save_entry(
            self._last_input_text, self.win.cleaned_text, audio_bytes,
            vsn, vd, self.win.rate_value, self.win.pitch_value, self.win.volume_value,
            clean_time=self._clean_elapsed if self._clean_elapsed > 0 else None,
            tts_time=tts_elapsed,
        )
        self._current_entry_id = self.history.entries[0]["id"]
        self._refresh_history()

    def _on_gen_failed(self, err):
        self.win.generating = False
        self.win.status = "生成失败"
        self.show_toast(f"生成失败: {err}", 2)

    # --- Preview ---

    def on_preview(self):
        self.win.generating = True
        self.show_toast("试听生成中…", 0)
        voice, rate, pitch, volume = self._get_tts_params()
        self.runner.run(
            fn=lambda: self.engine.synthesize("你好，这是语音试听。Hello, this is a voice preview.", voice, rate, pitch, volume),
            on_success=self._on_preview_done,
            on_error=lambda e: (setattr(self.win, "generating", False), self.show_toast(f"试听失败: {e}", 2)),
        )

    def _on_preview_done(self, audio_bytes: bytes):
        self.win.generating = False
        self.player.load(audio_bytes)
        self.win.has_audio = True
        self.win.player_total_time = self.player.total_time
        self.show_toast("试听播放中…", 1)
        self.player.play()

    # --- Player UI wiring ---

    def _on_player_progress(self, pct, cur, total):
        self._updating_progress = True
        self.win.player_progress = pct
        self.win.player_current_time = cur
        self._updating_progress = False

    def _on_player_state(self, playing: bool):
        self.win.playing = playing

    def _on_player_finished(self):
        self.win.player_progress = 0.0
        self.win.player_current_time = "0:00"

    def on_seek(self, value: float):
        if self._updating_progress:
            return
        self.player.seek(value)

    def _on_set_volume(self, value: float):
        self.player.set_volume(value)

    def _on_cycle_speed(self):
        self.player.cycle_speed()
        self.win.player_speed_label = self.player.speed_label

    def _on_toggle_loop(self):
        self.player.toggle_loop()
        self.win.loop_enabled = self.player.loop_enabled

    # --- History ---

    def on_select_history(self, idx: int):
        if not (0 <= idx < len(self.history.entries)):
            return
        entry = self.history.entries[idx]
        self._current_entry_id = entry["id"]
        self.player.stop()
        self.win.input_text = entry.get("text", "")
        self.win.cleaned_text = entry.get("cleaned", "")
        self.win.rate_value = entry.get("rate", 0)
        self.win.pitch_value = entry.get("pitch", 0)
        self.win.volume_value = entry.get("volume", 0)
        audio = self.history.get_audio(entry["id"])
        if audio:
            self.player.load(audio)
            self.win.has_audio = True
            self.win.player_total_time = self.player.total_time
        else:
            self.show_toast("音频文件丢失", 2)
        self._restore_voice(entry.get("voice_short_name", ""))
        self.win.current_page = 0
        self.show_toast("已恢复历史会话", 1)

    def _restore_voice(self, short_name: str):
        if not self.all_voices or not short_name:
            return
        voice = next((v for v in self.all_voices if v["ShortName"] == short_name), None)
        if not voice:
            return
        locale = voice["Locale"]
        langs = list(self.win.lang_list)
        if locale in langs:
            lang_idx = langs.index(locale)
            self.win.current_lang_index = lang_idx
            self.win.current_gender_index = 0
            self._apply_filter(lang_idx, 0)
            for i, v in enumerate(self.filtered_voices):
                if v["ShortName"] == short_name:
                    self.win.current_voice_index = i
                    break

    def _refresh_history(self):
        self.win.history_list = slint.ListModel(self.history.display_items())

    # --- Settings ---

    def _on_save_settings(self):
        data = settings.capture_from(self.win)
        settings.save(data)
        self.show_toast("设置已保存", 1)

    # --- Audio devices ---

    def _init_audio_devices(self, saved_idx: int = 0):
        names, paindices = self._query_output_names()
        self._device_names = names
        self._pa_indices = paindices
        self.win.device_list = slint.ListModel(names)
        if saved_idx < len(names):
            self.win.current_device_index = saved_idx
        self._update_device(saved_idx)

    def _query_output_names(self):
        devices = sd.query_devices()
        names = ["系统默认"]
        paindices = [None]
        for i, d in enumerate(devices):
            if d["max_output_channels"] > 0:
                names.append(d["name"])
                paindices.append(i)
        return names, paindices

    def _update_device(self, idx: int):
        dev = self._pa_indices[idx] if 0 <= idx < len(self._pa_indices) else None
        self.player.set_device(dev)

    def _refresh_devices(self):
        names, paindices = self._query_output_names()
        if names == self._device_names:
            return
        cur_idx = self.win.current_device_index
        cur_name = self._device_names[cur_idx] if cur_idx < len(self._device_names) else "系统默认"
        self._device_names = names
        self._pa_indices = paindices
        self.win.device_list = slint.ListModel(names)
        new_idx = names.index(cur_name) if cur_name in names else 0
        self.win.current_device_index = new_idx
        self._update_device(new_idx)

    # --- TTS params helper ---

    def _get_tts_params(self):
        voice = self.filtered_voices[self.win.current_voice_index]["ShortName"] if self.filtered_voices else "zh-CN-YunxiNeural"
        rate, pitch, volume = TTSEngine.format_params(int(self.win.rate_value), int(self.win.pitch_value), int(self.win.volume_value))
        return voice, rate, pitch, volume

    # --- Export ---

    def _on_export_audio(self):
        if not self._current_entry_id:
            self.show_toast("没有可保存的音频", 2)
            return
        audio = self.history.get_audio(self._current_entry_id)
        if not audio:
            self.show_toast("音频文件丢失", 2)
            return

        import subprocess, threading

        def do_save():
            try:
                script = 'POSIX path of (choose file name with prompt "保存音频文件" default name "tts_output.mp3" default location (path to desktop folder))'
                result = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=60)
                if result.returncode != 0:
                    return
                path = Path(result.stdout.strip())
                if not path.suffix:
                    path = path.with_suffix(".mp3")
                path.write_bytes(audio)
                self._export_result = str(path)
            except Exception as e:
                self._export_result = f"ERR:{e}"

        self._export_result = None
        threading.Thread(target=do_save, daemon=True).start()

        timer = slint.Timer()

        def poll():
            if self._export_result is None:
                return
            timer.stop()
            if self._export_result.startswith("ERR:"):
                self.show_toast(f"保存失败: {self._export_result[4:]}", 2)
            else:
                self.show_toast(f"已保存: {Path(self._export_result).name}", 1)

        timer.start(slint.TimerMode.Repeated, timedelta(milliseconds=200), poll)

    # --- Toast ---

    def show_toast(self, message: str, toast_type: int = 0):
        self.win.toast_message = message
        self.win.toast_type = toast_type
        self.win.toast_visible = True
        if self._toast_timer:
            self._toast_timer.stop()
        self._toast_timer = slint.Timer()
        self._toast_timer.start(slint.TimerMode.SingleShot, timedelta(seconds=3), lambda: setattr(self.win, "toast_visible", False))

    def _dismiss_toast(self):
        self.win.toast_visible = False
        if self._toast_timer:
            self._toast_timer.stop()

    # --- Run ---

    def run(self):
        self.win.run()


def main():
    app = TTSApp()
    app.run()
