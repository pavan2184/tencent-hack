# Demo video

Last updated: 2026-10-16

A narrated, subtitled 1080p walkthrough of Brain Sauce for the Tencent Cloud AI CAN DO IT
Hackathon submission (the handbook asks for 5–8 minutes). Eleven scenes told in plain language
for a non-technical judging panel: the first answer with its receipts, the one path every
question takes, permissions read from the source, access removed at the source, freshness with a
receipt, showing the working without a second AI, the three checks on every sentence, the audit
log with a recorded reveal, the six parts of the package, and how the team built it. Two
recordings of the same script exist, one per voice: about 6 min 0 s (Ziyu) and 6 min 35 s (Han).

Built with [HyperFrames](https://github.com/heygen-com/hyperframes) (HTML composition rendered
frame-by-frame with Chrome + FFmpeg) and an ElevenLabs voiceover. The design follows the web UI's
own language (`frontend/app/globals.css`): Inter Tight, near-monochrome neutrals with one muted
green accent, flat surfaces, pills, hairlines and numbered markers; text samples meet WCAG AA.
The mascot (`assets/mascot/`) replaces the text chrome: a small lockup top-left on every scene and
the full character on the end card. Burned-in captions run along the bottom, one sentence at a time.

## Layout

```text
demo/video/
├── index.html            the composition: eleven scenes, one paused GSAP timeline, phrase-synced
├── script/narration.json the voiceover script, default voice, alternate voices, model and post settings
├── script/tts.py         narration.json → assets/voice[-<key>]/<scene>.mp3 (+ manifest with durations)
├── script/tighten.py     caps long pauses and applies the tempo top-up; keeps <scene>.raw.mp3
├── script/schedule.py    writes the scene schedule (S table, <audio>, data-start/duration, TOTAL)
├── script/captions.py    generates the burned-in captions and their tweens from the S table
├── script/frame.mjs      screenshots the composition at given times (review without a render)
├── script/shoot.mjs      real-UI screenshots via puppeteer-core + system Chrome (+ facts.json)
├── script/fill.py        fills ids, hashes and 404 bodies from assets/shots/facts.json
├── assets/fonts/         Inter Tight (OFL, variable TTF from google/fonts), Geist Mono
├── assets/mascot/        character.png (end card), character-small.png + wordmark-small.png (chrome)
├── assets/voice/         Ziyu narration, one file per scene (committed so renders repeat)
├── assets/voice-han/     Han narration, same scenes
├── assets/shots/         UI screenshots and facts.json (real ids, hashes and 404 bodies)
└── out/                  renders (ignored)
```

## Regenerate

Requires Node 22+, FFmpeg and Google Chrome. The CLI is pinned to `hyperframes@0.8.157`.

```bash
cd demo/video
python3 script/schedule.py                 # or --voice han: schedule from that voice's manifest
python3 script/captions.py                 # captions follow the S table, so re-run after schedule.py
npx hyperframes@0.8.157 check            # lint + runtime + layout + motion + contrast
node script/frame.mjs out/frames 20 131  # stills at those times, for review
npx hyperframes@0.8.157 render --quality looks --output out/brain-sauce-demo-ziyu.mp4
```

To render the other voice, run `schedule.py --voice han` and `captions.py`, then render to a
different output name. `index.html` is committed with the Ziyu schedule.

### Voiceover

Only when `script/narration.json` changes; scenes whose text is unchanged are skipped.

```bash
ELEVENLABS_API_KEY=… python3 script/tts.py                      # default voice → assets/voice/
python3 script/tighten.py --max-pause 0.4 --min-silence 0.5 --tempo 1.0417 --apply
ELEVENLABS_API_KEY=… python3 script/tts.py --voice=han          # alternate → assets/voice-han/
python3 script/tighten.py --voice han --max-pause 0.4 --min-silence 0.5 --tempo 1.1 --apply
```

Voices, both shared library voices that must be added to the account once
(`POST /v1/voices/add/{public_owner_id}/{voice_id}`, owner id from `GET /v1/shared-voices?search=<id>`),
on `eleven_flash_v2_5`, one request per scene with `previous_text`/`next_text` for prosody:

- **Ziyu - Friendly but Unclear** (`1a0nAYA3FcNQcMMfbddY`, default). Speaks slowly and pauses
  long, so clips are generated at the API's maximum `speed` of 1.2 and `tighten.py` caps pauses
  at 0.4 s and adds a pitch-preserving `atempo` of 1.0417 (an effective 1.25×).
- **Han - Thoughtful, Clear and Profound** (`OAQQSa5rh6bJe9HgSD5E`, `voices.han`). Fast at the
  default speed, so clips are generated at `speed` 0.8 and tightened with `atempo` 1.1.

The script is ~4,900 characters, about 2,450 credits per voice per full regeneration.
`tts.py` deletes a scene's stale `.raw.mp3` when it re-records it; otherwise `tighten.py` would
rebuild the previous recording from the raw clip.

### Screenshots

Needs the API in memory mode on a _copy_ of the seed corpus (scene 5 edits the board deck's Drive
ACL in that copy and triggers a sync) and the Next.js dev server:

```bash
cp -R backend/seed /tmp/seed-copy
cd backend && REPO_BACKEND=memory CELERY_TASK_ALWAYS_EAGER=true SEED_DIR=/tmp/seed-copy \
  uv run uvicorn app.main:app --port 8000
cd frontend && npm run dev
cd demo/video && npm i --no-save puppeteer-core && node script/shoot.mjs assets/shots /tmp/seed-copy
```

The shoot syncs every source first (confidential permission snapshots expire five minutes after
capture), then runs the scenario in order: John's Rail-B cutover and failover asks, Mei's
abstention, John's cited deck answer, the leadership group removed from the deck's share and a
sync, John's second answer and the withheld history row, Sam's audit view (withheld answer,
reason, reveal, the `audit.reveal` event), and Mei's byte-identical 404s. It writes
`assets/shots/facts.json` with the ids, hashes, 404 bodies and two grounding-report hashes from
identical asks; `fill.py` puts them into the composition's audit chain, verify pill and 404 band.
Restart the API before re-shooting: the revocation lives in process memory.

## Scene sync

Each scene's visuals are cued from the narration by character position (`at(scene, phrase)` in
`index.html`), which is within about ±0.4 s once pauses are capped. The phrases must be exact
substrings of the scene text in `narration.json` (`schedule.py` copies that text into the `S`
table, and `at()` throws at build time if a phrase is missing). If a cue drifts, change the
phrase or add an offset; nothing else needs to move.
