"""
Fish Audio、火山引擎、MiniMax 的独立试听。不接入 audio_worker。

密钥写在 apps/audio_worker/.env，不要写进命令行：
  FISH_API_KEY
  VOLCENGINE_API_KEY
  MINIMAX_API_KEY

可选覆盖：
  FISH_REFERENCE_ID
  VOLCENGINE_SPEAKER
  MINIMAX_VOICE_ID
"""

from __future__ import annotations

import base64
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
import uuid
import wave
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[3]
WORKER_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = REPO / "audio" / "vendor-compare"

# 文档里的 BV700_V2_streaming 属于旧版情感音色。豆包语音合成 2.0 的灿灿是这个 id。
VOLC_SPEAKER = "zh_female_cancan_uranus_bigtts"
# 2.0 资源未授权时改走已开通的语音合成 3.0。Vivi 3.0 是陪聊女声，支持表达指令。
VOLC3_VOICE = "multi_female_vv_xi_v3_uranus_bigtts"
FISH_REFERENCE_ID = "74c6aba5cbf94a15bbdc547ffce5cb38"
MINIMAX_VOICE_ID = "female-tianmei"

SAMPLES: tuple[dict[str, str], ...] = (
    {
        "emotion": "neutral",
        "text": "今天下班有点早，突然不知道该做什么了。",
        "fish": "[natural conversational tone]",
        "volc": "语气自然、放松，像日常聊天",
        "minimax": "",
    },
    {
        "emotion": "joy",
        "text": "哈哈哈，我刚刚发现一件特别有意思的事情！",
        "fish": "[happy, cheerful, slightly excited]",
        "volc": "语气开心、轻快，带一点笑意",
        "minimax": "happy",
    },
    {
        "emotion": "affection",
        "text": "没关系，你不用急着回答，我可以慢慢听你说。",
        "fish": "[warm, gentle, intimate]",
        "volc": "语气温柔、亲近，语速稍慢",
        "minimax": "calm",
    },
    {
        "emotion": "jealousy",
        "text": "哦，原来你今天和她聊了这么久啊。",
        "fish": "[slightly jealous, mildly annoyed]",
        "volc": "带有轻微吃醋和嗔怪，语气中有一点不满",
        "minimax": "",
    },
    {
        "emotion": "anger",
        "text": "我不是不讲道理，只是你真的有点过分了。",
        "fish": "[angry, firm, restrained]",
        "volc": "明显生气，但克制情绪，不要大声喊叫",
        "minimax": "angry",
    },
)

VOLC_EXTRA: tuple[dict[str, str], ...] = (
    {
        "emotion": "coquettish_blame",
        "text": "哦，原来你今天和她聊了这么久啊。",
        "volc": "带一点嗔怪，像在亲近的人面前抱怨",
    },
    {
        "emotion": "tsundere",
        "text": "哦，原来你今天和她聊了这么久啊。",
        "volc": "语气傲娇，嘴上不承认，其实有点在意",
    },
    {
        "emotion": "spoil",
        "text": "没关系，你不用急着回答，我可以慢慢听你说。",
        "volc": "语气撒娇、柔软，像在跟很亲近的人说话",
    },
)


def load_env_file(path: Path) -> None:
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def post_json(url: str, body: dict[str, Any], headers: dict[str, str], timeout: int = 90) -> tuple[bytes, str]:
    request = urllib.request.Request(
        url,
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            content_type = response.headers.get("Content-Type", "")
            return response.read(), content_type
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code}: {detail[:400]}") from exc


def write_wav(path: Path, pcm: bytes, sample_rate: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(pcm)


def save_audio(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if data[:4] == b"RIFF":
        path.write_bytes(data)
        return
    if data[:3] == b"ID3" or data[:2] == b"\xff\xfb":
        path.with_suffix(".mp3").write_bytes(data)
        return
    path.write_bytes(data)


def fish_one(api_key: str, reference_id: str, sample: dict[str, str], dest: Path, model: str) -> None:
    text = f"{sample['fish']}\n{sample['text']}"
    payload, _ = post_json(
        "https://api.fish.audio/v1/tts",
        {
            "text": text,
            "reference_id": reference_id,
            "format": "wav",
            "sample_rate": 24000,
            "language": "zh",
        },
        {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "model": model,
        },
    )
    if payload[:1] in (b"{", b"["):
        raise RuntimeError(payload[:400].decode("utf-8", errors="replace"))
    save_audio(dest, payload)


def volc_one(api_key: str, speaker: str, text: str, instruction: str, dest: Path) -> None:
    payload, _ = post_json(
        "https://openspeech.bytedance.com/api/v3/tts/unidirectional",
        {
            "user": {"uid": "aipartner-probe"},
            "req_params": {
                "text": text,
                "speaker": speaker,
                "audio_params": {"format": "pcm", "sample_rate": 24000},
                "additions": json.dumps({"context_texts": [instruction]}, ensure_ascii=False),
            },
        },
        {
            "X-Api-Key": api_key,
            "X-Api-Resource-Id": "seed-tts-2.0",
            "Content-Type": "application/json",
        },
    )
    audio = bytearray()
    error = ""
    for line in payload.decode("utf-8", errors="replace").splitlines():
        stripped = line.strip()
        if stripped.startswith("data:"):
            stripped = stripped[5:].strip()
        if not stripped:
            continue
        event = json.loads(stripped)
        code = event.get("code")
        if event.get("data"):
            audio.extend(base64.b64decode(event["data"]))
        if code not in (0, None, 20000000):
            error = json.dumps(event, ensure_ascii=False)[:400]
    if error and not audio:
        raise RuntimeError(error)
    if not audio:
        raise RuntimeError(payload[:400].decode("utf-8", errors="replace"))
    write_wav(dest, bytes(audio), 24000)


def volc3_one(api_key: str, voice_id: str, text: str, instruction: str, dest: Path) -> None:
    voice = urllib.parse.quote(voice_id, safe="")
    payload, _ = post_json(
        f"https://voice.cn-beijing.volces.com/api/v3/text-to-speech/{voice}/streaming",
        {
            "text": text,
            "model_id": "doubao-seed-tts-3.0",
            "language_code": "zh",
            "output_format": {"format": "pcm", "sample_rate": 24000},
            "voice_settings": {"speed": 1.0, "instructions": [instruction]},
        },
        {
            "X-Api-Key": api_key,
            "Content-Type": "application/json",
            "X-Request-Id": str(uuid.uuid4()),
        },
    )
    audio = bytearray()
    error = ""
    for line in payload.decode("utf-8", errors="replace").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        event = json.loads(stripped)
        if event.get("event") == "audio" and event.get("audio"):
            audio.extend(base64.b64decode(event["audio"]))
        elif event.get("event") == "error":
            error = json.dumps(event, ensure_ascii=False)[:400]
    if error and not audio:
        raise RuntimeError(error)
    if not audio:
        raise RuntimeError(payload[:400].decode("utf-8", errors="replace"))
    write_wav(dest, bytes(audio), 24000)


MINIMAX_EMOTIONS = {"happy", "sad", "angry", "fearful", "disgusted", "surprised", "calm", "fluent", "whisper"}


def minimax_one(api_key: str, voice_id: str, sample: dict[str, str], dest: Path) -> None:
    voice_setting: dict[str, Any] = {
        "voice_id": voice_id,
        "speed": 0.95,
        "vol": 1.0,
        "pitch": 0,
    }
    emotion = sample.get("minimax", "")
    if emotion in MINIMAX_EMOTIONS:
        voice_setting["emotion"] = emotion
    payload, _ = post_json(
        "https://api.minimax.cn/v1/t2a_v2",
        {
            "model": "speech-2.8-hd",
            "text": sample["text"],
            "stream": False,
            "output_format": "hex",
            "voice_setting": voice_setting,
            "audio_setting": {"sample_rate": 32000, "format": "wav", "channel": 1},
        },
        {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
    )
    body = json.loads(payload.decode("utf-8"))
    status = (body.get("base_resp") or {}).get("status_code")
    if status not in (0, None):
        raise RuntimeError(json.dumps(body.get("base_resp"), ensure_ascii=False)[:400])
    audio_hex = (body.get("data") or {}).get("audio")
    if not audio_hex:
        raise RuntimeError(json.dumps(body, ensure_ascii=False)[:400])
    save_audio(dest, bytes.fromhex(audio_hex))


def volc_key_error(api_key: str, speaker: str) -> str | None:
    dest = DEFAULT_OUT / "volcengine" / "_auth.wav"
    try:
        volc_one(api_key, speaker, "你好。", "语气自然、放松，像日常聊天", dest)
    except RuntimeError as exc:
        return str(exc)
    return None


def run_vendor(
    name: str,
    api_key: str,
    jobs: list[tuple[str, Any]],
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    if not api_key:
        return [{"vendor": name, "status": "skipped", "reason": "missing api key"}]
    for emotion, call in jobs:
        record: dict[str, Any] = {"vendor": name, "emotion": emotion, "status": "ok"}
        try:
            call()
        except Exception as exc:
            record["status"] = "failed"
            record["error"] = str(exc)
        results.append(record)
        print(json.dumps(record, ensure_ascii=False), flush=True)
        if record["status"] == "failed" and any(
            token in record["error"] for token in ("1008", "403", "resource not granted")
        ):
            break
    return results


def main() -> int:
    load_env_file(WORKER_ROOT / ".env")
    only = {item.strip() for item in sys.argv[1:] if item.strip()}
    out_dir = DEFAULT_OUT
    out_dir.mkdir(parents=True, exist_ok=True)
    fish_key = os.environ.get("FISH_API_KEY", "").strip()
    volc_key = os.environ.get("VOLCENGINE_API_KEY", "").strip()
    volc_key_id = os.environ.get("VOLCENGINE_API_KEY_ID", "").strip()
    minimax_key = os.environ.get("MINIMAX_API_KEY", "").strip()
    fish_model = os.environ.get("FISH_MODEL", "s2.1-pro").strip() or "s2.1-pro"
    fish_voice = os.environ.get("FISH_REFERENCE_ID", FISH_REFERENCE_ID).strip()
    volc_speaker = os.environ.get("VOLCENGINE_SPEAKER", VOLC_SPEAKER).strip()
    volc3_voice = os.environ.get("VOLCENGINE_VOICE_V3", VOLC3_VOICE).strip()
    minimax_voice = os.environ.get("MINIMAX_VOICE_ID", MINIMAX_VOICE_ID).strip()

    fish_jobs = []
    volc_jobs = []
    volc3_jobs = []
    minimax_jobs = []
    for sample in SAMPLES:
        emotion = sample["emotion"]
        fish_jobs.append(
            (
                emotion,
                lambda sample=sample, emotion=emotion: fish_one(
                    fish_key, fish_voice, sample, out_dir / "fish" / f"{emotion}.wav", fish_model
                ),
            )
        )
        volc_jobs.append(
            (
                emotion,
                lambda sample=sample, emotion=emotion: volc_one(
                    volc_key,
                    volc_speaker,
                    sample["text"],
                    sample["volc"],
                    out_dir / "volcengine" / f"{emotion}.wav",
                ),
            )
        )
        volc3_jobs.append(
            (
                emotion,
                lambda sample=sample, emotion=emotion: volc3_one(
                    volc_key,
                    volc3_voice,
                    sample["text"],
                    sample["volc"],
                    out_dir / "volcengine" / f"{emotion}.wav",
                ),
            )
        )
        minimax_jobs.append(
            (
                emotion,
                lambda sample=sample, emotion=emotion: minimax_one(
                    minimax_key, minimax_voice, sample, out_dir / "minimax" / f"{emotion}.wav"
                ),
            )
        )
    for sample in VOLC_EXTRA:
        emotion = sample["emotion"]
        volc_jobs.append(
            (
                emotion,
                lambda sample=sample, emotion=emotion: volc_one(
                    volc_key,
                    volc_speaker,
                    sample["text"],
                    sample["volc"],
                    out_dir / "volcengine" / f"{emotion}.wav",
                ),
            )
        )
        volc3_jobs.append(
            (
                emotion,
                lambda sample=sample, emotion=emotion: volc3_one(
                    volc_key,
                    volc3_voice,
                    sample["text"],
                    sample["volc"],
                    out_dir / "volcengine" / f"{emotion}.wav",
                ),
            )
        )

    report = {
        "voices": {
            "fish": {"model": fish_model, "reference_id": fish_voice},
            "volcengine": {
                "resource": "seed-tts-2.0",
                "speaker": volc_speaker,
                "fallback": {"model": "doubao-seed-tts-3.0", "voice_id": volc3_voice},
            },
            "minimax": {"model": "speech-2.8-hd", "voice_id": minimax_voice},
        },
        "results": [],
    }
    if not only or "fish" in only:
        report["results"].extend(run_vendor("fish", fish_key, fish_jobs))
    if not only or "volcengine" in only:
        if volc_key:
            secret_error = volc_key_error(volc_key, volc_speaker)
            if secret_error and "Invalid X-Api-Key" in secret_error and volc_key_id:
                id_error = volc_key_error(volc_key_id, volc_speaker)
                if id_error is None:
                    volc_key = volc_key_id
                else:
                    report["results"].append(
                        {
                            "vendor": "volcengine",
                            "status": "failed",
                            "error": id_error,
                        }
                    )
                    volc_key = ""
            elif secret_error and "requested resource not granted" in secret_error:
                report["results"].append(
                    {
                        "vendor": "volcengine",
                        "status": "fallback",
                        "model": "doubao-seed-tts-3.0",
                        "voice_id": volc3_voice,
                        "reason": secret_error,
                    }
                )
                report["results"].extend(run_vendor("volcengine", volc_key, volc3_jobs))
                volc_key = ""
            elif secret_error:
                report["results"].append(
                    {"vendor": "volcengine", "status": "failed", "error": secret_error}
                )
                volc_key = ""
        if volc_key:
            report["results"].extend(run_vendor("volcengine", volc_key, volc_jobs))
        elif not any(item.get("vendor") == "volcengine" for item in report["results"]):
            report["results"].extend(run_vendor("volcengine", "", volc_jobs))
    if not only or "minimax" in only:
        report["results"].extend(run_vendor("minimax", minimax_key, minimax_jobs))
    (out_dir / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {out_dir / 'report.json'}")
    synthesized = [item for item in report["results"] if item.get("status") == "ok"]
    return 0 if synthesized else 2


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"vendor probe failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
