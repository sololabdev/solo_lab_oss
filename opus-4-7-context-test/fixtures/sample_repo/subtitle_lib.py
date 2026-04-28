"""Hypothetical karaoke-style subtitle library — fixture for benchmark."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

# ASS subtitle styling
SUB_FONT_NAME = "JetBrainsMono"
SUB_FONT_SIZE = 72
SUB_PRIMARY_COLOUR = "&H00FFFFFF"   # white in ASS BGR notation
SUB_ACCENT_COLOUR = "&H0074A5D4"    # warm beige
SUB_OUTLINE = 3
SUB_MARGIN_V = 170
SUB_ALIGNMENT = 2                    # bottom-center

KARAOKE_TAG = "\\kf"  # progressive colour-fill, in centiseconds per word


@dataclass
class WordTimestamp:
    text: str
    start_s: float
    end_s: float


def transcribe(audio_path: Path) -> list[WordTimestamp]:
    """Run the audio through STT and return word-level timestamps.

    Note: this fixture stub returns empty; real implementation would call
    an STT API (e.g. whisper, ElevenLabs Scribe) and convert to dataclass.
    """
    raise NotImplementedError("fixture stub")


def to_ass_word_pop(words: list[WordTimestamp],
                    output_path: Path) -> Path:
    """Emit an ASS subtitle file with one Dialogue per window plus karaoke
    tags for per-word colour sweep.

    Format choice: a SINGLE Dialogue line per ~3-5 word window, with
    \\kf<centiseconds> per word. This keeps the rendered bg-box stable
    (one continuous black bar that the colour sweeps across) instead of
    the staircase-of-boxes you'd get with one Dialogue per word.
    """
    raise NotImplementedError("fixture stub")
