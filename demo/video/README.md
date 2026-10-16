# Demo video

Last updated: 2026-10-16

A narrated 1080p walkthrough of Brain Sauce for the Tencent Cloud AI CAN DO IT Hackathon
submission (the handbook asks for 5–8 minutes). Eleven scenes: the first cited answer, the
pipeline, access control before any model, revocation at the source, freshness with a receipt,
model-free groundedness, verification and partial answers, the hash-chained audit log with a
recorded reveal, the stack, and how the team built it. About 6 min 44 s.

Built with [HyperFrames](https://github.com/heygen-com/hyperframes) (HTML composition rendered
frame-by-frame with Chrome + FFmpeg) and an ElevenLabs voiceover. The design follows the web UI's
own language (`frontend/app/globals.css`): Inter Tight, near-monochrome neutrals with one muted
green accent, flat surfaces, pills, hairlines and numbered markers; text samples meet WCAG AA.

## Layout

```text
demo/video/
├── index.html            the composition: eleven scenes, one paused GSAP timeline, phrase-synced
├── script/narration.json the voiceover script, voice, model, speed and post settings
├── script/tts.py         narration.json → assets/voice/<scene>.mp3 (+ manifest with durations)
├── script/tighten.py     caps long pauses and applies the tempo top-up; keeps <scene>.raw.mp3
├── script/shoot.mjs      real-UI screenshots via puppeteer-core + system Chrome (+ facts.json)
├── assets/fonts/         Inter Tight (OFL, variable TTF from google/fonts), Geist Mono
├── assets/voice/         generated narration, one file per scene (committed so renders repeat)
├── assets/shots/         UI screenshots and facts.json (real ids, hashes and 404 bodies)
└── out/                  renders (ignored)
```

## Regenerate

Requires Node 22+, FFmpeg and Google Chrome. The CLI is pinned to `hyperframes@0.8.157`.

```bash
cd demo/video
npx hyperframes@0.8.157 check            # lint + runtime + layout + motion + contrast
npx hyperframes@0.8.157 preview --background   # Studio preview at the printed URL
npx hyperframes@0.8.157 render --quality looks --output out/brain-sauce-demo.mp4
```

### Voiceover

Only when `script/narration.json` changes; scenes whose text is unchanged are skipped.

```bash
ELEVENLABS_API_KEY=… python3 script/tts.py
python3 script/tighten.py --max-pause 0.4 --min-silence 0.5 --tempo 1.0417 --apply
```

The voice is "Ziyu - Friendly but Unclear" (`1a0nAYA3FcNQcMMfbddY`, a shared library voice that
must be added to the account once) on `eleven_flash_v2_5`, one request per scene with
`previous_text`/`next_text` for prosody continuity. This voice speaks slowly and pauses long, so
clips are generated at the API's maximum `speed` of 1.2 and `tighten.py` caps pauses at 0.4 s and
adds a pitch-preserving `atempo` of 1.0417 (an effective 1.25×). The script is ~5,100 characters,
about 2,600 credits per full regeneration. After regenerating, copy the durations from
`assets/voice/manifest.json` into the `S` table and the `data-start`/`data-duration` attributes in
`index.html` (each scene's clip is 0.5 s lead + voice + 1 s tail).

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
identical asks; the composition's audit chain, verify result and 404 band are filled from it.
Restart the API before re-shooting: the revocation lives in process memory.

## Scene sync

Each scene's visuals are cued from the narration by character position (`at(scene, phrase)` in
`index.html`), which is within about ±0.4 s once pauses are capped. If a cue drifts, change the
phrase or add an offset; nothing else needs to move.
