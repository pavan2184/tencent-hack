"""Generate burned-in captions for the composition, one sentence at a time.

Reads script/narration.json and assets/voice/manifest.json, splits each scene's narration into
sentences, times them by character position inside the scene's clip (the same estimate the
composition uses for its cues, ±0.4 s once pauses are capped), and writes the caption elements
plus their timeline tweens into index.html between the marker comments:

    <!-- captions:start --> … <!-- captions:end -->      (markup, inside #root)
    // captions:start … // captions:end                  (tweens, inside the <script>)

The scene schedule (voice start per scene) is read from the `S` table in index.html so the two
can never drift apart. Idempotent: re-run after any narration or timing change.

Usage: python3 script/captions.py [--lead 0.5] [--tail 1.0]
"""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "index.html"
NARRATION = ROOT / "script" / "narration.json"

SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"'(])")


def split_sentences(text: str) -> list[tuple[int, int, str]]:
    """(char_start, char_end, sentence) for each sentence, positions in the full scene text."""
    out = []
    pos = 0
    for part in SENTENCE_END.split(text):
        start = text.index(part, pos)
        end = start + len(part)
        out.append((start, end, part.strip()))
        pos = end
    return out


def split_long(sentence: str, offset: int, max_chars: int) -> list[tuple[int, int, str]]:
    """Split a long sentence at the clause boundary nearest its middle, recursively."""
    if len(sentence) <= max_chars:
        return [(offset, offset + len(sentence), sentence)]
    cuts = [m.end() for m in re.finditer(r"[,;:]\s+", sentence)]
    if not cuts:
        return [(offset, offset + len(sentence), sentence)]
    mid = len(sentence) / 2
    cut = min(cuts, key=lambda c: abs(c - mid))
    left, right = sentence[:cut].rstrip(), sentence[cut:]
    return split_long(left, offset, max_chars) + split_long(right, offset + cut, max_chars)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-gap", type=float, default=0.12, help="gap between captions, seconds")
    ap.add_argument("--max-chars", type=int, default=130, help="split longer captions at a clause")
    args = ap.parse_args()

    page = INDEX.read_text()
    spec = json.loads(NARRATION.read_text())
    timing = {
        k: (float(v), float(d))
        for k, v, d in re.findall(
            r'\n        (s\d+): \{ start: [\d.]+, voice: ([\d.]+), vdur: ([\d.]+),', page
        )
    }
    if len(timing) != len(spec["scenes"]):
        sys.exit(f"S table has {len(timing)} scenes, narration has {len(spec['scenes'])}")

    caps: list[tuple[float, float, str]] = []
    for i, scene in enumerate(spec["scenes"], start=1):
        voice, vdur = timing[f"s{i}"]
        text = scene["text"]
        n = len(text)
        for cs, ce, sentence in split_sentences(text):
            for ps, pe, piece in split_long(sentence, cs, args.max_chars):
                start = voice + (ps / n) * vdur - 0.15
                end = voice + (pe / n) * vdur
                caps.append((round(max(start, 0.0), 2), round(end, 2), piece))
    # No overlaps: a caption ends before the next begins.
    for j in range(len(caps) - 1):
        s0, e0, t0 = caps[j]
        s1, _, _ = caps[j + 1]
        if e0 > s1 - args.min_gap:
            caps[j] = (s0, round(s1 - args.min_gap, 2), t0)

    markup = ["      <!-- captions:start -->", '      <div id="cap" data-layout-allow-overlap>']
    for j, (_, _, sentence) in enumerate(caps):
        markup.append(f'        <p class="c" data-i="{j}">{html.escape(sentence, quote=False)}</p>')
    markup.append("      </div>")
    markup.append("      <!-- captions:end -->")

    tweens = ["      // captions:start", "      {"]
    tweens.append(f"        const CAPS = {json.dumps([[s, e] for s, e, _ in caps])};")
    tweens.append("        CAPS.forEach(([s, e], j) => {")
    tweens.append('          const el = `#cap .c[data-i="${j}"]`;')
    tweens.append("          tl.fromTo(el, { opacity: 0, y: 8 }, { opacity: 1, y: 0, duration: 0.18, ease: \"power2.out\" }, s);")
    tweens.append("          tl.to(el, { opacity: 0, duration: 0.14, ease: \"power2.in\" }, Math.max(e - 0.14, s + 0.2));")
    tweens.append("        });")
    tweens.append("      }")
    tweens.append("      // captions:end")

    page, n1 = re.subn(
        r"      <!-- captions:start -->.*?<!-- captions:end -->",
        "\n".join(markup),
        page,
        flags=re.S,
    )
    page, n2 = re.subn(
        r"      // captions:start.*?// captions:end",
        "\n".join(tweens),
        page,
        flags=re.S,
    )
    if n1 != 1 or n2 != 1:
        sys.exit("caption markers not found in index.html (need both the HTML and the JS pair)")
    INDEX.write_text(page)
    total = sum(e - s for s, e, _ in caps)
    print(f"{len(caps)} captions, {total:.0f}s covered, longest {max(len(t) for _, _, t in caps)} chars")


if __name__ == "__main__":
    main()
