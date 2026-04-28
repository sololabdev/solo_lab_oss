"""Orchestrator that ties voice + video together. Fixture for benchmark."""
from __future__ import annotations

from pathlib import Path

from voice_lib import synthesize, estimate_duration_seconds
from video_lib import compose_reel
from subtitle_lib import to_ass_word_pop, transcribe


def daily_publish(caption_path: Path, image_path: Path,
                  output_dir: Path) -> Path:
    """End-to-end: caption.md -> voice MP3 -> video MP4 with subs.

    Pipeline:
        1. read caption.md
        2. voice_lib.synthesize() -> audio.mp3
        3. subtitle_lib.transcribe(audio.mp3) -> word-level timestamps
        4. subtitle_lib.to_ass_word_pop(words) -> subs.ass
        5. video_lib.compose_reel(image, audio, output, subs.ass) -> reel.mp4

    Returns: path to final reel MP4.
    """
    text = caption_path.read_text()
    audio = synthesize(text, output_path=output_dir / "audio.mp3")
    words = transcribe(audio)
    subs = to_ass_word_pop(words, output_path=output_dir / "subs.ass")
    return compose_reel(
        image_path=image_path,
        audio_path=audio,
        output_mp4=output_dir / "reel.mp4",
        ass_subtitle_path=subs,
    )
