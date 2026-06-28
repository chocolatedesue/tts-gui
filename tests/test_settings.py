from tts_gui.settings import load, save, apply_to, capture_from, SCHEMA, DEFAULT_CLEAN_PROMPT


def test_save_load_roundtrip(tmp_path):
    f = tmp_path / 'settings.json'
    data = {'api_url': 'http://x', 'rate': 1.5, 'clean_enabled': False}
    save(data, path=f)
    result = load(path=f)
    assert result['api_url'] == 'http://x'
    assert result['rate'] == 1.5
    assert result['clean_enabled'] is False


def test_defaults_on_empty(tmp_path):
    f = tmp_path / 'settings.json'
    f.write_text('{}')
    result = load(path=f)
    assert result['clean_prompt'] == DEFAULT_CLEAN_PROMPT
    assert result['player_volume'] == 80
    assert result['clean_enabled'] is True


def test_defaults_on_missing(tmp_path):
    f = tmp_path / 'nonexistent.json'
    result = load(path=f)
    assert result['api_url'] == ''
    assert result['device_index'] == 0


def test_apply_to_and_capture_from():
    class Win:
        pass

    win = Win()
    data = {'api_url': 'http://test', 'rate': 2.0, 'player_volume': 50}
    apply_to(win, data)
    assert win.api_url == 'http://test'
    assert win.rate_value == 2.0
    assert win.player_volume == 50

    captured = capture_from(win)
    assert captured['api_url'] == 'http://test'
    assert captured['rate'] == 2.0
    assert captured['player_volume'] == 50
