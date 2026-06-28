import sys
import time
from unittest.mock import MagicMock, patch

# Mock slint and sounddevice before import
mock_slint = MagicMock()


class FakeTimerMode:
    Repeated = "repeated"


mock_slint.TimerMode = FakeTimerMode


class FakeTimer:
    def __init__(self):
        self._cb = None

    def start(self, mode, interval, cb):
        self._cb = cb

    def stop(self):
        self._cb = None

    def tick(self):
        if self._cb:
            self._cb()


_fake_timer = FakeTimer()
mock_slint.Timer.return_value = _fake_timer
sys.modules["slint"] = mock_slint

mock_sd = MagicMock()
mock_sd.OutputStream = MagicMock


class FakeStream:
    active = True

    def start(self):
        pass

    def write(self, data):
        pass

    def abort(self):
        pass

    def close(self):
        self.active = False


sys.modules["sounddevice"] = mock_sd

import numpy as np
from unittest.mock import patch as _patch
from tts_gui.audio_player import AudioPlayer, _format_time


def _make_pcm_bytes():
    """Generate minimal valid audio: 1 second of silence as WAV."""
    import struct
    sr = 44100
    samples = b'\x00\x00' * sr  # 1s mono 16-bit silence
    # WAV header
    data_size = len(samples)
    header = struct.pack('<4sI4s4sIHHIIHH4sI',
                        b'RIFF', 36 + data_size, b'WAVE',
                        b'fmt ', 16, 1, 1, sr, sr * 2, 2, 16,
                        b'data', data_size)
    return header + samples


def _make_player():
    p = AudioPlayer(device=None)
    p._timer = _fake_timer
    return p


def test_format_time():
    assert _format_time(0) == "0:00"
    assert _format_time(65.4) == "1:05"
    assert _format_time(3599) == "59:59"


def test_load():
    p = _make_player()
    wav = _make_pcm_bytes()
    with _patch("tts_gui.audio_player.miniaudio") as mock_ma:
        mock_decoded = MagicMock()
        mock_decoded.sample_rate = 44100
        mock_decoded.nchannels = 1
        mock_decoded.samples = np.zeros(44100, dtype=np.int16).tobytes()
        mock_ma.decode.return_value = mock_decoded
        mock_ma.SampleFormat.SIGNED16 = 2
        p.load(wav)
    assert p._total == 44100
    assert p.total_time == "0:01"
    assert p.current_time == "0:00"


def test_seek():
    p = _make_player()
    p._pcm = np.zeros((44100, 1), dtype=np.int16)
    p._total = 44100
    p._samplerate = 44100
    p.seek(50.0)
    assert abs(p._frame - 22050) <= 1


def test_volume():
    p = _make_player()
    p.set_volume(60)
    assert abs(p._volume - 0.6) < 0.01


def test_cycle_speed():
    p = _make_player()
    assert p._speed_idx == 3  # default 1.5x
    p.cycle_speed()
    assert p._speed_idx == 4  # 2x
    p.cycle_speed()
    assert p._speed_idx == 0  # 0.75x


def test_toggle_loop():
    p = _make_player()
    assert not p._loop
    p.toggle_loop()
    assert p._loop
    p.toggle_loop()
    assert not p._loop


def test_progress_callback():
    p = _make_player()
    p._pcm = np.zeros((44100, 1), dtype=np.int16)
    p._total = 44100
    p._samplerate = 44100
    p._frame = 22050
    p._playing = True

    progress_calls = []
    p.on_progress = lambda pct, cur, total: progress_calls.append((pct, cur, total))
    _fake_timer._cb = p._poll
    _fake_timer.tick()
    assert len(progress_calls) == 1
    assert abs(progress_calls[0][0] - 50.0) < 0.1
    assert progress_calls[0][1] == "0:00"  # 22050/44100 = 0.5s
    assert progress_calls[0][2] == "0:01"


def test_stop_resets_frame():
    p = _make_player()
    p._pcm = np.zeros((44100, 1), dtype=np.int16)
    p._total = 44100
    p._frame = 10000
    p.stop()
    assert p._frame == 0
    assert not p._playing
