import json
from datetime import datetime
from pathlib import Path

HISTORY_DIR = Path.home() / ".config" / "tts-gui" / "history"
HISTORY_INDEX = HISTORY_DIR / "index.json"
MAX_HISTORY = 50


class History:
    def __init__(self, base_dir=HISTORY_DIR):
        self.base_dir = Path(base_dir)
        self.index_file = self.base_dir / "index.json"
        self.entries: list[dict] = []
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.load()

    def load(self) -> list[dict]:
        try:
            if self.index_file.exists():
                self.entries = json.loads(self.index_file.read_text(encoding="utf-8"))
        except Exception:
            self.entries = []
        return self.entries

    def _save_index(self):
        try:
            self.index_file.write_text(json.dumps(self.entries, ensure_ascii=False), encoding="utf-8")
        except Exception:
            pass

    def save_entry(self, text, cleaned, audio_bytes, voice_short_name, voice_display, rate, pitch, volume, clean_time=None, tts_time=None) -> dict:
        entry_id = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        entry = {
            "id": entry_id,
            "text": text,
            "cleaned": cleaned,
            "voice_short_name": voice_short_name,
            "voice_display": voice_display,
            "rate": rate,
            "pitch": pitch,
            "volume": volume,
            "ts": datetime.now().strftime("%Y-%m-%d %H:%M"),
        }
        if clean_time is not None:
            entry["clean_time"] = clean_time
        if tts_time is not None:
            entry["tts_time"] = tts_time
        try:
            (self.base_dir / f"{entry_id}.mp3").write_bytes(audio_bytes)
        except Exception:
            pass
        self.entries.insert(0, entry)
        while len(self.entries) > MAX_HISTORY:
            old = self.entries.pop()
            try:
                (self.base_dir / f"{old['id']}.mp3").unlink(missing_ok=True)
            except Exception:
                pass
        self._save_index()
        return entry

    def delete(self, entry_id: str):
        self.entries = [e for e in self.entries if e["id"] != entry_id]
        try:
            (self.base_dir / f"{entry_id}.mp3").unlink(missing_ok=True)
        except Exception:
            pass
        self._save_index()

    def clear(self):
        for e in self.entries:
            try:
                (self.base_dir / f"{e['id']}.mp3").unlink(missing_ok=True)
            except Exception:
                pass
        self.entries = []
        self._save_index()

    def get_audio(self, entry_id: str) -> bytes:
        try:
            return (self.base_dir / f"{entry_id}.mp3").read_bytes()
        except Exception:
            return b""

    def display_items(self) -> list[dict]:
        items = []
        for e in self.entries:
            t = e["text"].replace("\n", " ")
            title = t[:24] + "…" if len(t) > 24 else t
            subtitle = f"{e['ts']} · {e['voice_display']}"
            if e.get("clean_time") is not None and e.get("tts_time") is not None:
                subtitle += f" · {e['clean_time'] + e['tts_time']:.1f}s"
            items.append({"title": title, "subtitle": subtitle})
        return items
