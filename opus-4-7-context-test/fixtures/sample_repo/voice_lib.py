"""Hypothetical voice generation library — fixture for benchmark dry-runs.

Not a real library; just a small, self-contained Python module used as
sample input to context_loader.py so the benchmark works on a fresh clone
without needing the user's real codebase.
"""
from __future__ import annotations

from pathlib import Path

DEFAULT_VOICE_ID = "v_marvin_42"
DEFAULT_MODEL = "tts_v3_multilingual"
EXPRESSIVE_MODEL = "tts_v3_expressive"
API_BASE = "https://api.example.com"
CHARS_PER_SECOND = 14
MAX_RETRIES = 3
TIMEOUT_SECONDS = 30

VOICE_SETTINGS = {
    "stability": 0.45,
    "similarity_boost": 0.75,
    "style": 0.20,
    "use_speaker_boost": True,
}


def synthesize(text: str, voice_id: str = DEFAULT_VOICE_ID,
               model: str = DEFAULT_MODEL,
               output_path: str | Path = "out.mp3") -> Path:
    """Generate audio from text. Returns path to written MP3.

    Order of operations:
        1. tts_normalizer.normalize(text)   — clean numbers, expand abbreviations
        2. POST {API_BASE}/synthesize       — get MP3 bytes
        3. write to output_path
        4. return Path(output_path)
    """
    raise NotImplementedError("fixture stub — see pipeline.py for orchestration")


def estimate_duration_seconds(text: str) -> float:
    """Best-effort duration estimate at CHARS_PER_SECOND."""
    return len(text) / CHARS_PER_SECOND
