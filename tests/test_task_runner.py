import sys
import time
from unittest.mock import MagicMock
from datetime import timedelta

# Mock slint before importing task_runner
mock_slint = MagicMock()


class FakeTimerMode:
    Repeated = "repeated"


mock_slint.TimerMode = FakeTimerMode


class FakeTimer:
    def __init__(self):
        self._callback = None

    def start(self, mode, interval, callback):
        self._callback = callback

    def stop(self):
        self._callback = None

    def tick(self):
        if self._callback:
            self._callback()


# Patch so TaskRunner uses our FakeTimer
_fake_timer = FakeTimer()
mock_slint.Timer.return_value = _fake_timer
sys.modules["slint"] = mock_slint

from tts_gui.task_runner import TaskRunner  # noqa: E402


def _make_runner():
    runner = TaskRunner()
    runner._timer = _fake_timer
    return runner


def test_success_callback():
    runner = _make_runner()
    result = []
    runner.run(lambda: 42, on_success=result.append)
    time.sleep(0.05)
    _fake_timer.tick()
    assert result == [42]


def test_error_callback():
    runner = _make_runner()
    errors = []

    def failing():
        raise ValueError("boom")

    runner.run(failing, on_success=lambda v: None, on_error=errors.append)
    time.sleep(0.05)
    _fake_timer.tick()
    assert len(errors) == 1
    assert str(errors[0]) == "boom"


def test_cancel():
    runner = _make_runner()
    result = []
    task_id = runner.run(lambda: (time.sleep(1), 99)[1], on_success=result.append)
    runner.cancel(task_id)
    _fake_timer.tick()
    assert result == []


def test_timeout():
    runner = _make_runner()
    errors = []
    runner.run(
        lambda: time.sleep(10),
        on_success=lambda v: None,
        on_error=errors.append,
        timeout_ms=0,
    )
    time.sleep(0.05)
    _fake_timer.tick()
    assert len(errors) == 1
    assert isinstance(errors[0], TimeoutError)
