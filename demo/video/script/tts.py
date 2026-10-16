"""Generate one voiceover MP3 per scene from script/narration.json with ElevenLabs.

Budget notes: uses eleven_flash_v2_5 (half the per-character cost of multilingual v2), one
request per scene, and skips scenes whose MP3 already exists and whose text has not changed.
The API key is read from ELEVENLABS_API_KEY or from the file named by ELEVENLABS_KEY_FILE.

Usage: python3 script/tts.py [--force]
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "script" / "narration.json"


def api_key() -> str:
    key = os.environ.get("ELEVENLABS_API_KEY", "").strip()
    if not key and os.environ.get("ELEVENLABS_KEY_FILE"):
        key = Path(os.environ["ELEVENLABS_KEY_FILE"]).read_text().strip()
    if not key:
        sys.exit("set ELEVENLABS_API_KEY or ELEVENLABS_KEY_FILE")
    return key


def duration_s(path: Path) -> float:
    out = subprocess.check_output(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(path),
        ]
    )
    return float(out.decode().strip())


def main() -> None:
    force = "--force" in sys.argv
    voice_key = next((a.split("=", 1)[1] for a in sys.argv if a.startswith("--voice=")), "")
    spec = json.loads(SCRIPT.read_text())
    # The default voice is the top level of narration.json; alternates live under "voices" and
    # write to assets/voice-<key>/ so several recordings of one script can coexist.
    voice = spec["voices"][voice_key] if voice_key else spec
    out = ROOT / "assets" / (f"voice-{voice_key}" if voice_key else "voice")
    manifest_path = out / "manifest.json"
    out.mkdir(parents=True, exist_ok=True)
    manifest: dict = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
    key = api_key()
    scenes = spec["scenes"]
    total_chars = 0
    for i, scene in enumerate(scenes):
        text = scene["text"]
        digest = hashlib.sha256(text.encode()).hexdigest()[:16]
        mp3 = out / f"{scene['id']}.mp3"
        entry = manifest.get(scene["id"])
        if not force and mp3.exists() and entry and entry.get("sha") == digest:
            print(f"skip   {scene['id']} ({entry['duration_s']:.2f}s, cached)")
            continue
        body = {
            "text": text,
            "model_id": spec["model_id"],
            # previous/next text keep prosody continuous across per-scene requests; no extra cost.
            "previous_text": scenes[i - 1]["text"] if i > 0 else None,
            "next_text": scenes[i + 1]["text"] if i + 1 < len(scenes) else None,
            "voice_settings": voice.get(
                "voice_settings",
                {"stability": 0.5, "similarity_boost": 0.8, "style": 0.0, "speed": 1.0},
            ),
        }
        body = {k: v for k, v in body.items() if v is not None}
        url = (
            f"https://api.elevenlabs.io/v1/text-to-speech/{voice['voice_id']}"
            f"?output_format={spec['output_format']}"
        )
        # curl rather than urllib: the python.org interpreter ships without CA certificates.
        subprocess.run(
            [
                "curl", "-sS", "--fail", "-X", "POST", url,
                "-H", f"xi-api-key: {key}", "-H", "Content-Type: application/json",
                "--data-binary", "@-", "-o", str(mp3),
            ],
            input=json.dumps(body).encode(),
            check=True,
        )
        # A stale raw clip from an earlier recording would make tighten.py rebuild the old audio.
        (out / f"{scene['id']}.raw.mp3").unlink(missing_ok=True)
        total_chars += len(text)
        d = duration_s(mp3)
        manifest[scene["id"]] = {"sha": digest, "duration_s": d, "chars": len(text)}
        print(f"wrote  {scene['id']} {d:.2f}s {len(text)} chars")
    manifest_path.write_text(json.dumps(manifest, indent=2))
    total = sum(m["duration_s"] for m in manifest.values())
    print(f"billed ~{total_chars} chars this run; total voice {total:.1f}s")


if __name__ == "__main__":
    main()
