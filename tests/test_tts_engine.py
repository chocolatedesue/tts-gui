"""Tests for TTSEngine module."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tts_gui.tts_engine import TTSEngine


@pytest.fixture
def engine():
    return TTSEngine()


class TestListVoices:
    def test_returns_all_voices(self, engine):
        fake_voices = [
            {"Name": "v1", "Locale": "zh-CN", "Gender": "Male"},
            {"Name": "v2", "Locale": "en-US", "Gender": "Female"},
        ]
        with patch("tts_gui.tts_engine.edge_tts.VoicesManager.create", new_callable=AsyncMock) as mock_create:
            mock_vm = MagicMock()
            mock_vm.voices = fake_voices
            mock_create.return_value = mock_vm
            result = engine.list_voices()
        assert result == fake_voices

    def test_filter_by_locale(self, engine):
        fake_voices = [
            {"Name": "v1", "Locale": "zh-CN", "Gender": "Male"},
            {"Name": "v2", "Locale": "en-US", "Gender": "Female"},
        ]
        with patch("tts_gui.tts_engine.edge_tts.VoicesManager.create", new_callable=AsyncMock) as mock_create:
            mock_vm = MagicMock()
            mock_vm.voices = fake_voices
            mock_create.return_value = mock_vm
            result = engine.list_voices(locale="zh")
        assert result == [fake_voices[0]]

    def test_filter_by_gender(self, engine):
        fake_voices = [
            {"Name": "v1", "Locale": "zh-CN", "Gender": "Male"},
            {"Name": "v2", "Locale": "en-US", "Gender": "Female"},
        ]
        with patch("tts_gui.tts_engine.edge_tts.VoicesManager.create", new_callable=AsyncMock) as mock_create:
            mock_vm = MagicMock()
            mock_vm.voices = fake_voices
            mock_create.return_value = mock_vm
            result = engine.list_voices(gender="Female")
        assert result == [fake_voices[1]]

    def test_caches_voices(self, engine):
        fake_voices = [{"Name": "v1", "Locale": "zh-CN", "Gender": "Male"}]
        with patch("tts_gui.tts_engine.edge_tts.VoicesManager.create", new_callable=AsyncMock) as mock_create:
            mock_vm = MagicMock()
            mock_vm.voices = fake_voices
            mock_create.return_value = mock_vm
            engine.list_voices()
            engine.list_voices()
            mock_create.assert_called_once()


class TestSynthesize:
    def test_returns_bytes(self, engine):
        async def fake_stream():
            yield {"type": "audio", "data": b"hello"}
            yield {"type": "metadata", "data": "ignored"}
            yield {"type": "audio", "data": b" world"}

        with patch("tts_gui.tts_engine.edge_tts.Communicate") as mock_comm_cls:
            mock_inst = MagicMock()
            mock_inst.stream = fake_stream
            mock_comm_cls.return_value = mock_inst
            result = engine.synthesize("test", "voice1", rate="+10%")
        assert result == b"hello world"
        mock_comm_cls.assert_called_once_with("test", "voice1", rate="+10%", pitch="+0Hz", volume="+0%")


class TestCleanText:
    def test_returns_cleaned_text(self, engine):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"choices": [{"message": {"content": "cleaned"}}]}
        mock_resp.raise_for_status = MagicMock()

        with patch("tts_gui.tts_engine.httpx.post", return_value=mock_resp) as mock_post:
            result = engine.clean_text("raw", "http://api", "key123", "gpt-4", "fix it")
        assert result == "cleaned"
        mock_post.assert_called_once_with(
            "http://api/chat/completions",
            headers={"Authorization": "Bearer key123"},
            json={"model": "gpt-4", "messages": [{"role": "system", "content": "fix it"}, {"role": "user", "content": "raw"}]},
            timeout=30,
        )

    def test_raises_on_http_error(self, engine):
        mock_resp = MagicMock()
        mock_resp.raise_for_status.side_effect = Exception("500 error")

        with patch("tts_gui.tts_engine.httpx.post", return_value=mock_resp):
            with pytest.raises(Exception, match="500 error"):
                engine.clean_text("raw", "http://api", "key", "model", "prompt")


class TestFormatParams:
    def test_positive_values(self):
        assert TTSEngine.format_params(10, 5, 20) == ("+10%", "+5Hz", "+20%")

    def test_negative_values(self):
        assert TTSEngine.format_params(-10, -5, -20) == ("-10%", "-5Hz", "-20%")

    def test_zero_values(self):
        assert TTSEngine.format_params(0, 0, 0) == ("+0%", "+0Hz", "+0%")
