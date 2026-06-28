"""TTSEngine module - synchronous wrapper around edge_tts and LLM API."""

import asyncio

import edge_tts
import httpx


class TTSEngine:
    def __init__(self):
        self._voices_cache: list[dict] | None = None

    def list_voices(self, locale=None, gender=None) -> list[dict]:
        if self._voices_cache is None:

            async def _fetch():
                vm = await edge_tts.VoicesManager.create()
                return vm.voices

            self._voices_cache = asyncio.run(_fetch())

        voices = self._voices_cache
        if locale:
            voices = [v for v in voices if v.get("Locale", "").startswith(locale)]
        if gender:
            voices = [v for v in voices if v.get("Gender") == gender]
        return voices

    def synthesize(self, text, voice, rate="+0%", pitch="+0Hz", volume="+0%") -> bytes:
        async def _synth():
            comm = edge_tts.Communicate(text, voice, rate=rate, pitch=pitch, volume=volume)
            chunks = []
            async for chunk in comm.stream():
                if chunk["type"] == "audio":
                    chunks.append(chunk["data"])
            return b"".join(chunks)

        return asyncio.run(_synth())

    def clean_text(self, text, base_url, api_key, model, prompt) -> str:
        resp = httpx.post(
            f"{base_url}/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json={"model": model, "messages": [{"role": "system", "content": prompt}, {"role": "user", "content": text}]},
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]

    @staticmethod
    def format_params(rate_int, pitch_int, volume_int) -> tuple[str, str, str]:
        rate = f"+{rate_int}%" if rate_int >= 0 else f"{rate_int}%"
        pitch = f"+{pitch_int}Hz" if pitch_int >= 0 else f"{pitch_int}Hz"
        volume = f"+{volume_int}%" if volume_int >= 0 else f"{volume_int}%"
        return rate, pitch, volume
