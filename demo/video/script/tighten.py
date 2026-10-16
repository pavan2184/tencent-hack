"""Cap long pauses in the narration clips.

ElevenLabs voices differ a lot in how long they pause between sentences. This keeps every word
and every pause, but shortens any silence longer than MAX_PAUSE to exactly MAX_PAUSE, so the
narration keeps its rhythm without the dead air. Reads assets/voice/<id>.mp3, writes
assets/voice/<id>.tight.mp3 and reports before/after durations.

Usage: python3 script/tighten.py [--max-pause 0.4] [--min-silence 0.5] [--apply]
  --apply   replace the originals (the raw clip is kept as <id>.raw.mp3) and refresh manifest.json
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VOICE = ROOT / "assets" / "voice"
MANIFEST = VOICE / "manifest.json"
NOISE_DB = -38


def duration_s(path: Path) -> float:
    out = subprocess.check_output(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)]
    )
    return float(out.decode().strip())


def silences(path: Path, min_silence: float) -> list[tuple[float, float]]:
    proc = subprocess.run(
        [
            "ffmpeg", "-hide_banner", "-nostats", "-i", str(path),
            "-af", f"silencedetect=noise={NOISE_DB}dB:d={min_silence}", "-f", "null", "-",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    starts = [float(m) for m in re.findall(r"silence_start: ([0-9.]+)", proc.stderr)]
    ends = [float(m) for m in re.findall(r"silence_end: ([0-9.]+)", proc.stderr)]
    return list(zip(starts, ends, strict=False))


def tighten(
    src: Path, dst: Path, max_pause: float, min_silence: float, tempo: float = 1.0
) -> tuple[float, float]:
    total = duration_s(src)
    gaps = silences(src, min_silence)
    # Keep the audio outside each long silence plus `max_pause` of the silence itself (centred).
    keep: list[tuple[float, float]] = []
    cursor = 0.0
    for s, e in gaps:
        length = e - s
        if length <= max_pause:
            continue
        trim = (length - max_pause) / 2
        keep.append((cursor, s + trim))
        cursor = e - trim
    keep.append((cursor, total))
    keep = [(a, b) for a, b in keep if b - a > 0.01]
    parts = []
    for i, (a, b) in enumerate(keep):
        parts.append(f"[0:a]atrim=start={a:.3f}:end={b:.3f},asetpts=PTS-STARTPTS[p{i}]")
    chain = ";".join(parts) + ";" + "".join(f"[p{i}]" for i in range(len(keep)))
    chain += f"concat=n={len(keep)}:v=0:a=1[cat]"
    # atempo is pitch-preserving; small factors (≤1.1) are inaudible as artefacts.
    chain += f";[cat]atempo={tempo:.4f}[out]"
    subprocess.run(
        [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(src),
            "-filter_complex", chain, "-map", "[out]", "-c:a", "libmp3lame", "-b:a", "128k", str(dst),
        ],
        check=True,
    )
    return total, duration_s(dst)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-pause", type=float, default=0.4)
    ap.add_argument("--min-silence", type=float, default=0.5)
    ap.add_argument("--tempo", type=float, default=1.0, help="extra atempo factor (1.0 = none)")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    manifest = json.loads(MANIFEST.read_text()) if MANIFEST.exists() else {}
    before_total = after_total = 0.0
    for scene_id in manifest:
        src = VOICE / f"{scene_id}.mp3"
        raw = VOICE / f"{scene_id}.raw.mp3"
        if raw.exists():
            src = raw
        dst = VOICE / f"{scene_id}.tight.mp3"
        before, after = tighten(src, dst, args.max_pause, args.min_silence, args.tempo)
        before_total += before
        after_total += after
        print(f"{scene_id:24s} {before:7.2f}s -> {after:7.2f}s  (-{(1 - after / before) * 100:4.1f}%)")
        if args.apply:
            if not raw.exists():
                shutil.copy(VOICE / f"{scene_id}.mp3", raw)
            shutil.move(dst, VOICE / f"{scene_id}.mp3")
            manifest[scene_id]["duration_s"] = after
            manifest[scene_id]["raw_duration_s"] = before
    if args.apply:
        MANIFEST.write_text(json.dumps(manifest, indent=2))
    print(f"total {before_total:.1f}s -> {after_total:.1f}s")


if __name__ == "__main__":
    main()
