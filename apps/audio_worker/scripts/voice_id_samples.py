"""按指定音色 id 生成同一组试听。不接入 audio_worker。"""

from __future__ import annotations

import json
import struct
import sys
from pathlib import Path

import vendor_tts_probe as probe

OUT = probe.DEFAULT_OUT / "voices"
FISH_MODEL = "s2.1-pro"
FISH_FALLBACK = "s2.1-pro-free"

VOICES = (
    {
        "slug": "xue-zhiqian",
        "name": "薛之谦",
        "vendor": "fish",
        "voice_id": "61b33c9a45324f69a22dbb5f91a526d0",
    },
    {
        "slug": "deng-ziqi",
        "name": "邓紫棋",
        "vendor": "fish",
        "voice_id": "885171cb0820413caf62d515c286ce1d",
    },
    {
        "slug": "wang-sulong",
        "name": "汪苏泷",
        "vendor": "fish",
        "voice_id": "092d735394c64eefba2f966432c7526e",
    },
    {
        "slug": "xiaohe-3",
        "name": "小何 3.0",
        "vendor": "volcengine",
        "voice_id": "multi_female_xiaohe_taiwan_v3_uranus_bigtts",
    },
    {
        "slug": "soft-girl",
        "name": "Chinese (Mandarin)_Soft_Girl",
        "vendor": "minimax",
        "voice_id": "Chinese (Mandarin)_Soft_Girl",
    },
)


def repair_fish_wav(path: Path) -> None:
    raw = path.read_bytes()
    if len(raw) < 44 or raw[:4] != b"RIFF":
        return
    pcm = raw[44:]
    header = struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF",
        36 + len(pcm),
        b"WAVE",
        b"fmt ",
        16,
        1,
        1,
        24000,
        48000,
        2,
        16,
        b"data",
        len(pcm),
    )
    path.write_bytes(header + pcm)


def main() -> int:
    probe.load_env_file(probe.WORKER_ROOT / ".env")
    fish_key = probe.os.environ.get("FISH_API_KEY", "").strip()
    volc_key = probe.os.environ.get("VOLCENGINE_API_KEY", "").strip()
    minimax_key = probe.os.environ.get("MINIMAX_API_KEY", "").strip()
    fish_model = FISH_MODEL
    results: list[dict[str, str]] = []
    only = {item.strip() for item in sys.argv[1:] if item.strip()}
    selected = [voice for voice in VOICES if not only or voice["slug"] in only or voice["name"] in only]

    for voice in selected:
        vendor = voice["vendor"]
        key = {"fish": fish_key, "volcengine": volc_key, "minimax": minimax_key}[vendor]
        folder = OUT / voice["slug"]
        if not key:
            record = {"voice": voice["name"], "status": "skipped", "reason": "missing api key"}
            results.append(record)
            print(json.dumps(record, ensure_ascii=False), flush=True)
            continue
        for sample in probe.SAMPLES:
            emotion = sample["emotion"]
            dest = folder / f"{emotion}.wav"
            record = {
                "voice": voice["name"],
                "vendor": vendor,
                "voice_id": voice["voice_id"],
                "emotion": emotion,
                "model": {
                    "fish": fish_model,
                    "volcengine": "doubao-seed-tts-3.0",
                    "minimax": "speech-2.8-hd",
                }[vendor],
                "status": "ok",
            }
            try:
                if vendor == "fish":
                    probe.fish_one(key, voice["voice_id"], sample, dest, fish_model)
                    repair_fish_wav(dest)
                elif vendor == "volcengine":
                    probe.volc3_one(key, voice["voice_id"], sample["text"], sample["volc"], dest)
                else:
                    probe.minimax_one(key, voice["voice_id"], sample, dest)
            except Exception as exc:
                message = str(exc)
                if vendor == "fish" and fish_model == FISH_MODEL and "402" in message:
                    fish_model = FISH_FALLBACK
                    record["model"] = fish_model
                    record["note"] = "s2.1-pro returned 402, switched to s2.1-pro-free"
                    try:
                        probe.fish_one(key, voice["voice_id"], sample, dest, fish_model)
                        repair_fish_wav(dest)
                    except Exception as retry_exc:
                        record["status"] = "failed"
                        record["error"] = str(retry_exc)
                else:
                    record["status"] = "failed"
                    record["error"] = message
            results.append(record)
            print(json.dumps(record, ensure_ascii=False), flush=True)
            if record["status"] == "failed" and any(
                token in record.get("error", "") for token in ("1008", "403", "resource not granted")
            ):
                break

    OUT.mkdir(parents=True, exist_ok=True)
    report_path = OUT / "report.json"
    if only and report_path.is_file():
        previous = json.loads(report_path.read_text(encoding="utf-8"))
        kept = [item for item in previous if item.get("voice") not in {voice["name"] for voice in selected}]
        results = kept + results
    report_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {report_path}")
    return 0 if any(item.get("status") == "ok" for item in results) else 2


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"voice id samples failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
