import queue
import threading
import time
import uuid
from datetime import timedelta

import slint


class TaskRunner:
    def __init__(self):
        self._tasks = {}  # task_id -> {queue, on_success, on_error, start_time, timeout_ms}
        self._timer = slint.Timer()

    def run(self, fn, on_success, on_error=None, timeout_ms=30000):
        task_id = str(uuid.uuid4())
        q = queue.Queue()
        self._tasks[task_id] = {
            "queue": q,
            "on_success": on_success,
            "on_error": on_error,
            "start_time": time.time(),
            "timeout_ms": timeout_ms,
        }

        def worker():
            try:
                result = fn()
                q.put(("ok", result))
            except Exception as e:
                q.put(("err", e))

        t = threading.Thread(target=worker, daemon=True)
        t.start()

        if len(self._tasks) == 1:
            self._timer.start(slint.TimerMode.Repeated, timedelta(milliseconds=200), self._poll)

        return task_id

    def cancel(self, task_id):
        self._tasks.pop(task_id, None)
        if not self._tasks:
            self._timer.stop()

    def _poll(self):
        done = []
        for task_id, task in list(self._tasks.items()):
            try:
                status, value = task["queue"].get_nowait()
                done.append(task_id)
                if status == "ok":
                    task["on_success"](value)
                elif task["on_error"]:
                    task["on_error"](value)
            except queue.Empty:
                elapsed = (time.time() - task["start_time"]) * 1000
                if elapsed >= task["timeout_ms"]:
                    done.append(task_id)
                    if task["on_error"]:
                        task["on_error"](TimeoutError(f"Task {task_id} timed out"))

        for task_id in done:
            self._tasks.pop(task_id, None)
        if not self._tasks:
            self._timer.stop()
