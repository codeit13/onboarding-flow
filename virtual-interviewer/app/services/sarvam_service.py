"""Sarvam AI text-to-speech (Bulbul v3) for interview question audio."""

from __future__ import annotations

import base64
import logging
import os

import httpx
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("sarvam-service")

SARVAM_TTS_URL = "https://api.sarvam.ai/text-to-speech"


class SarvamService:
    """Generate MP3 speech via Sarvam REST API."""

    def __init__(self) -> None:
        self.api_key = (
            os.getenv("SARVAM_API_KEY") or os.getenv("SARVAM_API_SUBSCRIPTION_KEY") or ""
        ).strip()
        if not self.api_key:
            raise ValueError(
                "SARVAM_API_KEY is required for text-to-speech. "
                "Add it to virtual-interviewer/.env (see .env.example)."
            )

        self.model = os.getenv("SARVAM_TTS_MODEL", "bulbul:v3")
        # Male voice; natural Indian English on en-IN (also used for hi-IN consistency).
        self.speaker = os.getenv("SARVAM_TTS_SPEAKER", "aditya")
        self.pace = float(os.getenv("SARVAM_TTS_PACE", "0.95"))
        self._client = httpx.Client(timeout=60.0)

    @staticmethod
    def _target_language_code(language: str) -> str:
        lang = (language or "en").strip().lower()
        if lang in ("hi", "hin", "hi-in"):
            return "hi-IN"
        return "en-IN"

    def generate_text_to_speech(self, text: str, language: str = "en") -> bytes:
        """Convert text to MP3 bytes using Sarvam Bulbul v3."""
        if not text or not text.strip():
            raise ValueError("TTS text must be non-empty")

        payload = {
            "text": text,
            "target_language_code": self._target_language_code(language),
            "model": self.model,
            "speaker": self.speaker,
            "output_audio_codec": "mp3",
            "pace": self.pace,
        }

        response = self._client.post(
            SARVAM_TTS_URL,
            headers={
                "api-subscription-key": self.api_key,
                "Content-Type": "application/json",
            },
            json=payload,
        )

        if response.status_code != 200:
            detail = response.text[:500] if response.text else response.status_code
            logger.error("Sarvam TTS failed (%s): %s", response.status_code, detail)
            response.raise_for_status()

        data = response.json()
        audios = data.get("audios") or []
        if not audios:
            raise ValueError("Sarvam TTS returned no audio in response")

        return base64.b64decode(audios[0])
