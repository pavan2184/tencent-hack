"""Write the scene schedule into index.html from a voice manifest.

Each scene's clip is LEAD seconds of lead-in, the voice clip, then TAIL seconds of tail. The
script rewrites, in place and idempotently:

  * the `S` table (start, voice, vdur and the narration text used for phrase cues),
  * the `<audio id="vo-sN">` elements (src, data-start, data-duration),
  * every `<section id="sN" class="clip">` data-start/data-duration,
  * `#root` data-duration and `const TOTAL`.

Run it after regenerating a voice, then `captions.py` (which reads the S table back).

Usage: python3 script/schedule.py [--voice han] [--lead 0.5] [--tail 1.0] [--end-hold 4.0]
  --voice KEY   use assets/voice-KEY/ (default: assets/voice/)
  --end-hold    extra seconds after the last scene's tail for the end card
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "index.html"
NARRATION = ROOT / "script" / "narration.json"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--voice", default="")
    ap.add_argument("--lead", type=float, default=0.5)
    ap.add_argument("--tail", type=float, default=1.0)
    ap.add_argument("--end-hold", type=float, default=4.0)
    args = ap.parse_args()

    voice_dir = f"assets/voice-{args.voice}" if args.voice else "assets/voice"
    manifest = json.loads((ROOT / voice_dir / "manifest.json").read_text())
    spec = json.loads(NARRATION.read_text())
    page = INDEX.read_text()

    rows, audio, t = [], [], 0.0
    for i, scene in enumerate(spec["scenes"], start=1):
        sid = scene["id"]
        if sid not in manifest:
            sys.exit(f"{voice_dir}/manifest.json has no entry for {sid}")
        vdur = round(manifest[sid]["duration_s"], 2)
        start, voice = round(t, 2), round(t + args.lead, 2)
        dur = round(args.lead + vdur + args.tail, 2)
        if i == len(spec["scenes"]):
            dur = round(dur + args.end_hold, 2)
        text = json.dumps(scene["text"], ensure_ascii=False)
        rows.append(f"        s{i}: {{ start: {start}, voice: {voice}, vdur: {vdur}, text: {text} }},")
        audio.append(
            f'      <audio id="vo-s{i}" data-audio-group="voiceover" src="{voice_dir}/{sid}.mp3" '
            f'data-start="{voice}" data-duration="{vdur}" data-track-index="9"></audio>'
        )
        page, n = re.subn(
            rf'(<section id="s{i}" class="clip" data-start=")[\d.]+(" data-duration=")[\d.]+(")',
            rf"\g<1>{start}\g<2>{dur}\g<3>",
            page,
        )
        if n != 1:
            sys.exit(f"section s{i} not found")
        t += dur
    total = round(t, 2)

    page, n1 = re.subn(
        r"      const S = \{\n(?:        s\d+: \{.*\n)+      \};",
        "      const S = {\n" + "\n".join(rows) + "\n      };",
        page,
    )
    page, n2 = re.subn(r"      const TOTAL = [\d.]+;", f"      const TOTAL = {total};", page)
    page, n3 = re.subn(
        r'(      <audio id="vo-s1" .*\n)(?:      <audio id="vo-s\d+" .*\n)*',
        "\n".join(audio) + "\n",
        page,
    )
    page, n4 = re.subn(
        r'(id="root"\n(?:.*\n)*?      data-duration=")[\d.]+(")',
        rf"\g<1>{total}\g<2>",
        page,
    )
    if (n1, n2, n3, n4) != (1, 1, 1, 1):
        sys.exit(f"markers not matched: S={n1} TOTAL={n2} audio={n3} root={n4}")
    INDEX.write_text(page)
    print(f"{voice_dir}: {len(rows)} scenes, total {total}s ({total / 60:.1f} min)")


if __name__ == "__main__":
    main()
