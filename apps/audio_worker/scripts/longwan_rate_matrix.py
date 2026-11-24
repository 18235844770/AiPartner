"""
Longwan v2 独立听感矩阵：6 段情绪文本 × 3 档语速。

不导入 audio_worker，不改音色表、对话链路或 TTS 后端。
longwan_v2 属于 cosyvoice-v2，官方不支持 Instruct，本脚本不传情绪指令。
情绪差异只来自方案里的六段文本；唯一合成变量是语速。

凭据（不要写进命令行，避免留在 shell 历史里）：
  DASHSCOPE_API_KEY
  DASHSCOPE_WORKSPACE_ID   华北 2（北京）业务空间 ID
已存在的环境变量优先。否则读取 apps/audio_worker/.env，该文件已被 git 忽略。

用法：
  python apps/audio_worker/scripts/longwan_rate_matrix.py --dry-run
  python apps/audio_worker/scripts/longwan_rate_matrix.py
"""

from __future__ import annotations

import argparse
import array
import json
import math
import os
import sys
import time
import urllib.error
import urllib.request
import wave
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[3]
WORKER_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = REPO / "audio" / "longwan-v2-rate-matrix"

MODEL = "cosyvoice-v2"
VOICE = "longwan_v2"
PITCH = 1.0
VOLUME = 50
SAMPLE_RATE = 24000
AUDIO_FORMAT = "wav"
SEED = 0
RATES = (0.90, 0.95, 1.05)

OPTIONS_PATH = Path(__file__).with_name("cloud_voice_options.json")
# 试听过、尚未收成方案的音色。已保留的方案在 cloud_voice_options.json。
VOICE_CONFIGS: dict[str, dict[str, Any]] = {
    "longantai_v3": {"model": "cosyvoice-v3-flash", "instruct": False},
    "longfeifei_v3": {"model": "cosyvoice-v3-flash", "instruct": False},
}

# 文本来自《Longwan 音色调整方案 V1.0》第四节。语速三档覆盖方案给出的 0.90–1.05。
SAMPLES: tuple[dict[str, str], ...] = (
    {
        "emotion": "neutral",
        "label": "日常",
        "text": "今天过得怎么样？我刚刚想到一件挺有意思的事情，想跟你说。",
    },
    {
        "emotion": "joy",
        "label": "开心",
        "text": "哈哈，真的假的？这也太有意思了吧，我突然有点想试试看！",
    },
    {
        "emotion": "affection",
        "label": "亲密",
        "text": "其实我还挺喜欢跟你待在一起的，有时候也会希望时间过得慢一点。",
    },
    {
        "emotion": "sadness",
        "label": "委屈",
        "text": "你刚才那样说，我其实有一点不开心。我也不是完全不在意的。",
    },
    {
        "emotion": "jealousy",
        "label": "嫉妒",
        "text": "哦，原来你今天跟别人玩得这么开心啊。我倒也没说什么，就是有一点点在意。",
    },
    {
        "emotion": "anger",
        "label": "生气",
        "text": "这件事我确实不太认同，而且我不想每次都因为怕你不高兴就不表达自己的想法。",
    },
)

# 相对同语速 Neutral 的期望方向。1 表示应更高，-1 表示应更低，0 表示不纳入。
# 嫉妒、亲密的方向很弱，代理分不能代替听感。
EMOTION_DIRECTION: dict[str, dict[str, int]] = {
    "joy": {"f0_median": 1, "rms": 1, "silence_ratio": -1},
    "affection": {"f0_median": -1, "rms": -1, "silence_ratio": 1},
    "sadness": {"f0_median": -1, "rms": -1, "silence_ratio": 1},
    "jealousy": {"rms": -1, "silence_ratio": 1, "f0_std": 1},
    "anger": {"rms": 1, "silence_ratio": -1, "f0_std": 1},
}


def load_voice_options() -> dict[str, dict[str, Any]]:
    payload = json.loads(OPTIONS_PATH.read_text(encoding="utf-8"))
    options = payload.get("options")
    if not isinstance(options, list):
        raise ValueError(f"{OPTIONS_PATH.name} 缺少 options")
    return {str(item["id"]): item for item in options}


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


# longanhuan 在 cosyvoice-v3-plus 的场景枚举。陪伴实景用闲聊对话。
CHAT_SCENE = "闲聊对话"
# 官方情感只有这 7 个。亲密、嫉妒没有对应值，实景里保持 neutral，并在结果里标明。
API_EMOTION: dict[str, str] = {
    "neutral": "neutral",
    "joy": "happy",
    "affection": "neutral",
    "sadness": "sad",
    "jealousy": "neutral",
    "anger": "angry",
}


def scene_instruction(api_emotion: str, scene: str = CHAT_SCENE) -> str:
    """官方句式，句号不能省。汉字按 2 计，总长度须小于 100。"""
    instruction = f"你正在进行{scene}，你说话的情感是{api_emotion}。"
    weighted = sum(2 if "\u4e00" <= char <= "\u9fff" else 1 for char in instruction)
    if weighted > 100:
        raise ValueError(f"instruction 长度 {weighted} 超过 100: {instruction}")
    return instruction


def jobs(
    rates: tuple[float, ...] = RATES,
    *,
    use_instruction: bool = False,
    emotion_map: dict[str, str] | None = None,
    scene: str = CHAT_SCENE,
) -> list[dict[str, Any]]:
    mapping = emotion_map or API_EMOTION
    rows: list[dict[str, Any]] = []
    for sample in SAMPLES:
        instruction = None
        api_emotion = None
        if use_instruction:
            api_emotion = mapping[sample["emotion"]]
            instruction = scene_instruction(api_emotion, scene)
        rate_list: tuple[float | None, ...] = (None,) if use_instruction else rates
        for rate in rate_list:
            if rate is None:
                file_name = f"{sample['emotion']}_{api_emotion}.wav"
            else:
                rate_tag = f"{rate:.2f}".replace(".", "")
                file_name = f"{sample['emotion']}_r{rate_tag}.wav"
            rows.append(
                {
                    **sample,
                    "rate": rate,
                    "api_emotion": api_emotion,
                    "instruction": instruction,
                    "file_name": file_name,
                }
            )
    return rows


def synthesize(
    workspace_id: str,
    api_key: str,
    text: str,
    rate: float | None,
    *,
    model: str = MODEL,
    voice: str = VOICE,
    instruction: str | None = None,
) -> dict[str, Any]:
    url = (
        f"https://{workspace_id}.cn-beijing.maas.aliyuncs.com"
        "/api/v1/services/audio/tts/SpeechSynthesizer"
    )
    body = {
        "model": model,
        "input": {
            "text": text,
            "voice": voice,
            "format": AUDIO_FORMAT,
            "sample_rate": SAMPLE_RATE,
            "volume": VOLUME,
            "pitch": PITCH,
            "seed": SEED,
            "language_hints": ["zh"],
        },
    }
    if rate is not None:
        body["input"]["rate"] = rate
    if instruction:
        body["input"]["instruction"] = instruction
    request = urllib.request.Request(
        url,
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=90) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code}: {detail[:500]}") from exc
    audio = (payload.get("output") or {}).get("audio") or {}
    audio_url = audio.get("url")
    if not audio_url:
        raise RuntimeError(f"响应里没有音频地址: {json.dumps(payload, ensure_ascii=False)[:500]}")
    return {
        "request_id": payload.get("request_id"),
        "characters": (payload.get("usage") or {}).get("characters"),
        "audio_url": audio_url,
    }


def download(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    temporary = dest.with_suffix(".part")
    try:
        with urllib.request.urlopen(url, timeout=90) as response:
            data = response.read()
        if len(data) < 44 or data[:4] != b"RIFF":
            raise RuntimeError(f"下载内容不是 WAV，长度 {len(data)}")
        temporary.write_bytes(data)
        temporary.replace(dest)
    finally:
        if temporary.exists():
            temporary.unlink()


def read_mono_float(path: Path) -> tuple[int, list[float]]:
    with wave.open(str(path), "rb") as handle:
        channels = handle.getnchannels()
        width = handle.getsampwidth()
        rate = handle.getframerate()
        frames = handle.getnframes()
        raw = handle.readframes(frames)
    if width != 2:
        raise ValueError(f"{path.name} 不是 16-bit WAV")
    samples = array.array("h")
    samples.frombytes(raw)
    if sys.byteorder != "little":
        samples.byteswap()
    if channels > 1:
        samples = array.array("h", (samples[index] for index in range(0, len(samples), channels)))
    return rate, [sample / 32768.0 for sample in samples]


def _percentile(values: list[float], ratio: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    index = min(len(ordered) - 1, max(0, int(round((len(ordered) - 1) * ratio))))
    return ordered[index]


def _f0_hz(frame: list[float], rate: int) -> float | None:
    mean = sum(frame) / len(frame)
    centered = [value - mean for value in frame]
    energy = sum(value * value for value in centered)
    if energy < 1e-4:
        return None
    min_lag = max(1, int(rate / 400))
    max_lag = min(int(rate / 80), len(centered) - 1)
    best_lag = 0
    best = 0.0
    for lag in range(min_lag, max_lag + 1):
        corr = 0.0
        limit = len(centered) - lag
        for index in range(limit):
            corr += centered[index] * centered[index + lag]
        corr /= energy
        if corr > best:
            best = corr
            best_lag = lag
    if best_lag == 0 or best < 0.35:
        return None
    return rate / best_lag


def analyze(path: Path, text: str) -> dict[str, float]:
    rate, samples = read_mono_float(path)
    if not samples:
        raise ValueError(f"{path.name} 没有采样")
    duration = len(samples) / rate
    peak = max(abs(sample) for sample in samples)
    clip_ratio = sum(abs(sample) >= 0.98 for sample in samples) / len(samples)
    frame = max(1, int(rate * 0.03))
    hop = max(1, int(rate * 0.01))
    rms_frames: list[float] = []
    f0_values: list[float] = []
    # 基频降到 8 kHz 估算，避免纯 Python 自相关过慢。
    step = max(1, rate // 8000)
    f0_rate = rate // step
    f0_frame = max(1, int(f0_rate * 0.04))
    start = 0
    while start + frame <= len(samples):
        window = samples[start : start + frame]
        rms = math.sqrt(sum(sample * sample for sample in window) / len(window))
        rms_frames.append(rms)
        start += hop
    voiced_gate = max(0.02, _percentile(rms_frames, 0.6) * 0.45) if rms_frames else 0.02
    start = 0
    down = samples[::step]
    while start + f0_frame <= len(down):
        window = down[start : start + f0_frame]
        rms = math.sqrt(sum(sample * sample for sample in window) / len(window))
        if rms >= voiced_gate:
            f0 = _f0_hz(window, f0_rate)
            if f0 is not None:
                f0_values.append(f0)
        start += max(1, int(f0_rate * 0.01))
    silence_ratio = (
        sum(value < voiced_gate * 0.35 for value in rms_frames) / len(rms_frames) if rms_frames else 1.0
    )
    mean_rms = sum(rms_frames) / len(rms_frames) if rms_frames else 0.0
    f0_median = _percentile(f0_values, 0.5)
    f0_std = 0.0
    if f0_values:
        f0_mean = sum(f0_values) / len(f0_values)
        f0_std = math.sqrt(sum((value - f0_mean) ** 2 for value in f0_values) / len(f0_values))
    char_count = max(1, len(text.replace(" ", "")))
    return {
        "duration_s": round(duration, 3),
        "chars_per_s": round(char_count / duration, 3) if duration else 0.0,
        "peak": round(peak, 4),
        "clip_ratio": round(clip_ratio, 6),
        "rms": round(mean_rms, 5),
        "silence_ratio": round(silence_ratio, 4),
        "f0_median": round(f0_median, 2),
        "f0_std": round(f0_std, 2),
        "voiced_frames": float(len(f0_values)),
    }


def _band_score(value: float, center: float, half_width: float) -> float:
    distance = abs(value - center) / half_width
    return max(0.0, 100.0 - distance * 40.0)


def naturalness(metrics: dict[str, float]) -> float:
    if metrics["clip_ratio"] > 0:
        clip_score = 40.0
    elif metrics["peak"] > 0.95:
        clip_score = 70.0
    else:
        clip_score = 100.0
    silence_score = _band_score(metrics["silence_ratio"], 0.14, 0.12)
    if metrics["voiced_frames"] < 8 or metrics["f0_median"] <= 0:
        contour_score = 45.0
    else:
        contour_score = _band_score(metrics["f0_std"], 32.0, 28.0)
    return round(0.25 * clip_score + 0.35 * silence_score + 0.40 * contour_score, 1)


def emotion_match(metrics: dict[str, float], baseline: dict[str, float], emotion: str) -> float | None:
    direction = EMOTION_DIRECTION.get(emotion)
    if direction is None:
        return None
    hits = 0
    total = 0
    for key, sign in direction.items():
        if sign == 0:
            continue
        delta = metrics[key] - baseline[key]
        # 相对变化太小视为没分开，不计成功。
        scale = max(abs(baseline[key]), 1e-6)
        if abs(delta) < scale * 0.03:
            total += 1
            continue
        total += 1
        if delta * sign > 0:
            hits += 1
    if total == 0:
        return None
    return round(100.0 * hits / total, 1)


def rank_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    baseline = {
        (row["emotion"], row["rate"]): row["metrics"]
        for row in rows
        if row["emotion"] == "neutral" and "metrics" in row
    }
    ranked: list[dict[str, Any]] = []
    for row in rows:
        metrics = row.get("metrics")
        if not metrics:
            continue
        nature = naturalness(metrics)
        reference = baseline.get(("neutral", row["rate"]))
        express = emotion_match(metrics, reference, row["emotion"]) if reference else None
        if express is None:
            combined = nature
        else:
            combined = round(0.6 * nature + 0.4 * express, 1)
        ranked.append(
            {
                "emotion": row["emotion"],
                "label": row["label"],
                "rate": row["rate"],
                "file_name": row["file_name"],
                "naturalness_proxy": nature,
                "emotion_proxy": express,
                "combined_proxy": combined,
            }
        )
    return ranked


def write_report(
    out_dir: Path,
    ranked: list[dict[str, Any]],
    *,
    voice: str = VOICE,
    model: str = MODEL,
    rates: tuple[float, ...] = RATES,
    instruct_supported: bool = False,
) -> None:
    best: list[dict[str, Any]] = []
    for sample in SAMPLES:
        group = [row for row in ranked if row["emotion"] == sample["emotion"]]
        if not group:
            continue
        winner = max(group, key=lambda row: row["combined_proxy"])
        best.append(winner)
    report = {
        "voice": voice,
        "model": model,
        "pitch": PITCH,
        "volume": VOLUME,
        "sample_rate": SAMPLE_RATE,
        "seed": SEED,
        "rates": list(rates),
        "instruct_supported": instruct_supported,
        "proxy_note": (
            "naturalness_proxy 与 emotion_proxy 是声学代理，不是人工听感。"
            "嫉妒和亲密的方向分尤其不可靠。最终组合要以连听同一情绪的三档 WAV 为准。"
        ),
        "scores": ranked,
        "proxy_best_per_emotion": best,
    }
    (out_dir / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--option", default=None, help="cloud_voice_options.json 里的方案 id")
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--voice", default=None)
    parser.add_argument("--model", default=None)
    parser.add_argument("--rates", default=None)
    parser.add_argument("--instruct", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    options = load_voice_options()
    option = options.get(args.option) if args.option else None
    if args.option and option is None:
        known = ", ".join(sorted(options))
        print(f"未知方案 {args.option}。可选：{known}", file=sys.stderr)
        return 2
    voice = args.voice or (option["voice"] if option else VOICE)
    voice_config = VOICE_CONFIGS.get(voice, {})
    if option is not None:
        voice_config = {**voice_config, "model": option["model"], "instruct": option.get("instruct") is not None}
    model = args.model or voice_config.get("model", MODEL)
    instruct_supported = bool(voice_config.get("instruct", False))
    use_instruction = bool(args.instruct or (option and option.get("instruct")))
    if args.rates:
        rates = tuple(float(item) for item in args.rates.split(",") if item.strip())
    elif option and option.get("rates"):
        rates = tuple(float(item) for item in option["rates"])
    else:
        rates = RATES
    emotion_map = None
    scene = CHAT_SCENE
    if option and option.get("instruct"):
        emotion_map = option["instruct"]["emotion_map"]
        scene = option["instruct"]["scene"]
    if use_instruction and not instruct_supported:
        print(f"{voice} 不支持 Instruct，未发起合成。", file=sys.stderr)
        return 2
    plan = jobs(rates, use_instruction=use_instruction, emotion_map=emotion_map, scene=scene)
    run_config = {
        "option": args.option,
        "model": model,
        "voice": voice,
        "format": AUDIO_FORMAT,
        "sample_rate": SAMPLE_RATE,
        "volume": VOLUME,
        "pitch": PITCH,
        "seed": SEED,
        "language_hints": ["zh"],
        "rates": None if use_instruction else list(rates),
        "rate_sent": not use_instruction,
        "scene": scene if use_instruction else None,
        "instruct_supported": instruct_supported,
        "instructions": [
            {
                "emotion": job["emotion"],
                "label": job["label"],
                "api_emotion": job["api_emotion"],
                "instruction": job["instruction"],
            }
            for job in plan
            if job["instruction"]
        ],
    }
    if args.dry_run:
        print(
            json.dumps(
                {
                    "option": args.option,
                    "model": model,
                    "voice": voice,
                    "config": run_config,
                    "pitch": PITCH,
                    "volume": VOLUME,
                    "sample_rate": SAMPLE_RATE,
                    "count": len(plan),
                    "jobs": plan,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    load_env_file(WORKER_ROOT / ".env")
    api_key = os.environ.get("DASHSCOPE_API_KEY", "").strip()
    workspace_id = os.environ.get("DASHSCOPE_WORKSPACE_ID", "").strip()
    if not api_key or not workspace_id:
        print(
            "缺少 DASHSCOPE_API_KEY 或 DASHSCOPE_WORKSPACE_ID，未发起合成。",
            file=sys.stderr,
        )
        return 2

    if args.out is not None:
        out_dir = args.out.resolve()
    elif option and option.get("output_dir"):
        out_dir = (REPO / option["output_dir"]).resolve()
    else:
        out_dir = DEFAULT_OUT.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "config.json").write_text(
        json.dumps(run_config, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    manifest: list[dict[str, Any]] = []
    for index, job in enumerate(plan, start=1):
        dest = out_dir / job["file_name"]
        record = {key: value for key, value in job.items()}
        rate_label = "unset" if job["rate"] is None else f"{job['rate']:.2f}"
        print(
            f"[{index}/{len(plan)}] {job['emotion']} rate={rate_label} instruction={job['instruction']}",
            flush=True,
        )
        if args.resume and dest.is_file() and dest.stat().st_size > 44:
            record["audio_path"] = str(dest)
            record["skipped"] = True
        else:
            result = synthesize(
                workspace_id,
                api_key,
                job["text"],
                job["rate"],
                model=model,
                voice=voice,
                instruction=job["instruction"],
            )
            download(result["audio_url"], dest)
            record["audio_path"] = str(dest)
            record["request_id"] = result["request_id"]
            record["characters"] = result["characters"]
            time.sleep(0.4)
        record["metrics"] = analyze(dest, job["text"])
        manifest.append(record)
        print(json.dumps(record["metrics"], ensure_ascii=False), flush=True)

    (out_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    write_report(
        out_dir,
        rank_rows(manifest),
        voice=voice,
        model=model,
        rates=() if use_instruction else rates,
        instruct_supported=instruct_supported,
    )
    print(f"wrote {out_dir / 'report.json'}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"longwan matrix failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
