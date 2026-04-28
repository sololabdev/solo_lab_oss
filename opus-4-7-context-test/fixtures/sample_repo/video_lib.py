"""Hypothetical video composition library — fixture for benchmark dry-runs."""
from __future__ import annotations

from pathlib import Path

# Canvas geometry
CANVAS_WIDTH = 1080
CANVAS_HEIGHT = 1920
FRAME_RATE = 30
PIXEL_FORMAT = "yuv420p"
VIDEO_CODEC = "libx264"
AUDIO_CODEC = "aac"
AUDIO_BITRATE = "128k"

# Animation
ZOOM_START = 1.000
ZOOM_END = 1.080
ZOOM_ANCHOR_X = 0.45
ZOOM_ANCHOR_Y = 0.42
OPENER_FADE_SECONDS = 0.6

# Branding
BRAND_TEXT = "// example_lab"
BRAND_FONT_SIZE = 36
BRAND_MARGIN_PX = 40

# Subtitles
SUB_FONT_SIZE = 72
SUB_MARGIN_VERTICAL_PX = 170


def compose_reel(image_path: Path, audio_path: Path,
                 output_mp4: Path, ass_subtitle_path: Path | None = None) -> Path:
    """Compose a vertical reel from a still PNG + voice MP3.

    Steps (in order):
        1. ffmpeg pre-scale image 4×    (avoid zoompan aliasing)
        2. ffmpeg zoompan + fade-in     (ZOOM_START -> ZOOM_END)
        3. overlay BRAND_TEXT           (top-left, fade in 0.5–1.2s)
        4. mux with audio_path
        5. if ass_subtitle_path:        ffmpeg libass burn-in
        6. write output_mp4

    Returns: output_mp4 (absolute Path).
    """
    raise NotImplementedError("fixture stub")
