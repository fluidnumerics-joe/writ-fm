# TODO: FluidNumerics Repo Report — Ron Burgundy Edition

GitHub activity news segment delivered in a cloned Ron Burgundy voice.

---

## Voice Cloning Setup

- [ ] Find or record a 10-30s clean reference clip of the target voice (WAV, mono, minimal background noise)
- [ ] Save reference clip to `mac/chatterbox/voices/ron_burgundy.wav`
- [ ] Set up Chatterbox venv:
  ```bash
  cd mac/chatterbox
  uv venv
  uv pip install chatterbox-tts torch torchaudio
  ```
- [ ] Test voice cloning with a sample line:
  ```bash
  python tts.py "Fourteen commits hit the main branch today, and I'm not even mad. That's amazing." \
    -o test_ron.wav -v voices/ron_burgundy.wav
  ```
- [ ] Tune `exaggeration` (try 0.5-0.9) until the voice sounds right
- [ ] Decide on final exaggeration/temperature/cfg_weight values

## Persona

- [x] Add `ron_burgundy` host to `HOSTS` dict in `mac/content_generator/persona.py`

## GitHub Activity Fetcher

- [x] Add `fetch_github_activity()` to `mac/content_generator/helpers.py`
- [x] Add `format_github_activity()` for prompt injection
- [ ] Decide: does this need a `GITHUB_TOKEN` for rate limits, or is unauthenticated (60 req/hr) sufficient?
  - Set `GITHUB_TOKEN` env var for 5000 req/hr if needed

## Segment Type

- [x] Add `repo_report` to `VALID_SEGMENT_TYPES` in `mac/schedule.py`
- [x] Add `repo_report` word targets (800-1500) to `SEGMENT_WORD_TARGETS`
- [x] Add `repo_report` prompt template to `SEGMENT_PROMPTS`
- [x] Add `github_activity` topic pool to `TOPIC_POOLS`
- [x] Wire `build_generation_prompt()` to call `fetch_github_activity()`

## TTS Routing

- [x] Chatterbox routing via `chatterbox:` voice prefix in `render_single_voice()`
- [ ] Create `mac/chatterbox/voices/` directory and add reference WAV

## Schedule Integration

- [x] Add `repo_report` show definition in `config/schedule.yaml`
- [x] Add weekday 12:00-13:00 override slot for repo_report

## Testing

- [ ] Generate one segment end-to-end manually:
  ```bash
  uv run python mac/content_generator/talk_generator.py --show repo_report --type repo_report --count 1
  ```
- [ ] Verify the audio sounds right (voice, pacing, content)
- [ ] Test that the streamer picks it up and plays it
- [ ] Verify the operator daemon stocks it correctly
