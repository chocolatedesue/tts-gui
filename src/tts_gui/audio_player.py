import threading
from datetime import timedelta

import miniaudio
import numpy as np
import sounddevice as sd
import slint

SPEED_OPTIONS = [("0.75x", 0.75), ("1x", 1.0), ("1.25x", 1.25), ("1.5x", 1.5), ("2x", 2.0)]


def _format_time(seconds: float) -> str:
    s = max(0, int(seconds))
    return f"{s // 60}:{s % 60:02d}"


class AudioPlayer:
    def __init__(self, device=None):
        self._lock = threading.Lock()
        self._pcm: np.ndarray | None = None
        self._samplerate: int = 44100
        self._channels: int = 1
        self._frame: int = 0
        self._total: int = 0
        self._stream: sd.OutputStream | None = None
        self._volume: float = 0.8
        self._speed_idx: int = 3
        self._loop: bool = False
        self._playing: bool = False
        self._device = device
        self._timer: slint.Timer | None = None

        self.on_progress = None  # Callable[[float, str, str], None] (pct, cur, total)
        self.on_finished = None  # Callable[[], None]
        self.on_state_changed = None  # Callable[[bool], None] (playing)

    @property
    def playing(self) -> bool:
        return self._playing

    @property
    def speed_label(self) -> str:
        return SPEED_OPTIONS[self._speed_idx][0]

    @property
    def loop_enabled(self) -> bool:
        return self._loop

    def load(self, audio_bytes: bytes):
        self.stop()
        decoded = miniaudio.decode(audio_bytes, output_format=miniaudio.SampleFormat.SIGNED16)
        self._samplerate = decoded.sample_rate
        self._channels = decoded.nchannels
        self._pcm = np.frombuffer(decoded.samples, dtype=np.int16).reshape(-1, decoded.nchannels)
        self._total = len(self._pcm)
        self._frame = 0

    @property
    def total_time(self) -> str:
        return _format_time(self._total / self._samplerate) if self._pcm is not None else "0:00"

    @property
    def current_time(self) -> str:
        return _format_time(self._frame / self._samplerate) if self._pcm is not None else "0:00"

    def set_device(self, device):
        self._device = device

    def play(self):
        if self._pcm is None:
            return
        self._stop_stream()
        _, speed = SPEED_OPTIONS[self._speed_idx]
        self._stream = sd.OutputStream(
            samplerate=int(self._samplerate * speed),
            channels=self._channels,
            dtype="int16",
            blocksize=4096,
            device=self._device,
        )
        self._stream.start()
        self._playing = True
        if self.on_state_changed:
            self.on_state_changed(True)
        threading.Thread(target=self._play_loop, daemon=True).start()
        self._start_timer()

    def _play_loop(self):
        stream = self._stream
        pcm = self._pcm
        while True:
            with self._lock:
                if stream is None or stream != self._stream or not stream.active:
                    return
                frame = self._frame
                if frame >= self._total:
                    return
                end = min(frame + 4096, self._total)
            chunk = pcm[frame:end].astype(np.float32)
            chunk = (chunk * self._volume).clip(-32768, 32767).astype(np.int16)
            try:
                stream.write(chunk)
            except Exception:
                return
            with self._lock:
                if self._stream == stream:
                    self._frame = end

    def pause(self):
        self._stop_stream()
        self._playing = False
        if self.on_state_changed:
            self.on_state_changed(False)

    def stop(self):
        self._stop_stream()
        self._playing = False
        if self._timer:
            self._timer.stop()
        with self._lock:
            self._frame = 0
        if self.on_state_changed:
            self.on_state_changed(False)

    def seek(self, pct: float):
        if self._pcm is None:
            return
        with self._lock:
            self._frame = max(0, min(int((pct / 100.0) * self._total), self._total - 1))
        if self._playing:
            self.play()

    def set_volume(self, pct: float):
        self._volume = pct / 100.0

    def cycle_speed(self):
        self._speed_idx = (self._speed_idx + 1) % len(SPEED_OPTIONS)
        if self._playing:
            self.play()

    def toggle_loop(self):
        self._loop = not self._loop

    def _stop_stream(self):
        s = self._stream
        self._stream = None
        if s is not None:
            try:
                s.abort()
                s.close()
            except Exception:
                pass

    def _start_timer(self):
        if self._timer is not None:
            self._timer.stop()
        self._timer = slint.Timer()
        self._timer.start(slint.TimerMode.Repeated, timedelta(milliseconds=200), self._poll)

    def _poll(self):
        if self._pcm is None or self._total == 0:
            return
        with self._lock:
            frame = self._frame
        pct = (frame / self._total) * 100.0
        cur = _format_time(frame / self._samplerate)
        total = _format_time(self._total / self._samplerate)
        if self.on_progress:
            self.on_progress(pct, cur, total)
        if frame >= self._total and self._playing:
            if self._loop:
                self._stop_stream()
                with self._lock:
                    self._frame = 0
                self.play()
            else:
                self._playing = False
                self._stop_stream()
                with self._lock:
                    self._frame = 0
                if self.on_state_changed:
                    self.on_state_changed(False)
                if self.on_finished:
                    self.on_finished()
