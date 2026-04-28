# Sample repo (fixture for benchmark)

This is a small hypothetical content-generation pipeline used as the
default corpus for the Opus 4.7 context-cliff benchmark. Four modules:

- `voice_lib.py` — TTS synthesis. Holds voice IDs, model identifiers,
  base URL, character-rate constants.
- `video_lib.py` — vertical reel composition via ffmpeg. Holds canvas
  geometry, zoom params, brand text.
- `subtitle_lib.py` — karaoke-style ASS subtitle generation. Defines
  the colour-sweep format choice and styling constants.
- `pipeline.py` — orchestrator that ties voice + video + subs together.

The functions are deliberately stubs (raise `NotImplementedError`).
The point is to give the benchmark something concrete to ask
multi-hop and refactor questions about — exact constant values,
import relationships, data flow between modules.

`fixtures/sample_questions.json` contains 9 questions written against
this fixture: 3 needle (single-fact lookup), 3 multi-hop (trace data
flow), 3 refactor (synthesis).

To benchmark your own codebase, replace these files with your own and
write your own `questions.json`. The harness is codebase-agnostic.
