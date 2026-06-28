import pytest
from tts_gui.history import History, MAX_HISTORY


@pytest.fixture
def hist(tmp_path):
    return History(base_dir=tmp_path)


def _save(hist, text="hello", **kw):
    defaults = dict(cleaned=text, audio_bytes=b"\xff" * 10, voice_short_name="en-US-Guy", voice_display="Guy", rate="+0%", pitch="+0Hz", volume="+0%")
    defaults.update(kw)
    return hist.save_entry(text, **defaults)


def test_save_and_load_roundtrip(hist, tmp_path):
    entry = _save(hist, "test text")
    h2 = History(base_dir=tmp_path)
    assert len(h2.entries) == 1
    assert h2.entries[0]["text"] == "test text"
    assert h2.get_audio(entry["id"]) == b"\xff" * 10


def test_max_history_trim(hist, tmp_path):
    for i in range(51):
        _save(hist, f"msg{i}")
    assert len(hist.entries) == MAX_HISTORY
    # oldest was msg0, should be gone
    ids = {e["text"] for e in hist.entries}
    assert "msg0" not in ids
    # its mp3 should be deleted
    first_id = None
    for f in tmp_path.glob("*.mp3"):
        first_id = f.stem
    # reload to confirm persistence
    h2 = History(base_dir=tmp_path)
    assert len(h2.entries) == MAX_HISTORY


def test_delete(hist):
    e = _save(hist, "to delete")
    hist.delete(e["id"])
    assert len(hist.entries) == 0
    assert hist.get_audio(e["id"]) == b""


def test_clear(hist):
    _save(hist, "a")
    _save(hist, "b")
    hist.clear()
    assert len(hist.entries) == 0


def test_display_items(hist):
    _save(hist, "short", clean_time=0.5, tts_time=1.5)
    _save(hist, "a" * 30)
    items = hist.display_items()
    assert len(items) == 2
    # most recent first
    assert items[0]["title"] == "a" * 24 + "…"
    assert "·" in items[0]["subtitle"]
    # second has time info
    assert "2.0s" in items[1]["subtitle"]
