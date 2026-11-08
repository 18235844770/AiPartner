"""
CosyVoice3 逐字顿挫对照诊断（独立脚本，不改生产代码）。

输出目录默认：仓库根 /audio
实验：
  A_raw.wav              — 官方非流式，完整文本，text_frontend=True
  A_frontend_off.wav     — 非流式，text_frontend=False（对照）
  B_stream_merged.wav    — 官方流式，硬拼接（无淡入淡出）
  B_chunk_XX.wav         — 各流式 chunk 原始片段
  P_prod_path.wav        — 复现当前生产路径：分段 + 响度对齐 + 交叉淡化（仅对照）
  diagnose_report.json   — 指标与判断
  silence_stats.json     — 静音分析
  waveform_*.png         — 波形/RMS（若 matplotlib 可用）
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = Path(__file__).resolve().parents[3]
DEFAULT_OUT = REPO / "audio"
TEST_TEXT = (
    "今天晚上我想和你聊聊最近发生的事情。"
    "其实有些想法我已经考虑很久了，只是一直没有找到合适的机会告诉你。"
)
# 官方 CosyVoice3 instruct2 必须带 <|endofprompt|>
INSTRUCT_OFFICIAL = "You are a helpful assistant. Speak naturally and calmly.<|endofprompt|>"
# 当前生产常见写法（缺 endofprompt，会触发模型断言）
INSTRUCT_PROD_BROKEN = "Speak naturally and calmly."
OFFICIAL_PROMPT_TEXT = "希望你以后能够做的比我还好呦。"
ZERO_SHOT_PROMPT = f"You are a helpful assistant.<|endofprompt|>{OFFICIAL_PROMPT_TEXT}"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--model-dir", type=Path, default=ROOT / "models" / "tts" / "Fun-CosyVoice3-0.5B")
    parser.add_argument("--repo-dir", type=Path, default=ROOT / "vendor" / "CosyVoice")
    parser.add_argument("--prompt-wav", type=Path, default=None)
    parser.add_argument("--fp16", action="store_true", default=True)
    parser.add_argument("--no-fp16", action="store_true")
    parser.add_argument("--text", type=str, default=TEST_TEXT)
    args = parser.parse_args()
    fp16 = False if args.no_fp16 else True

    out_dir: Path = args.out.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    prompt_wav = (args.prompt_wav or (args.repo_dir / "asset" / "zero_shot_prompt.wav")).resolve()
    if not prompt_wav.is_file():
        raise FileNotFoundError(f"prompt wav missing: {prompt_wav}")
    if not args.model_dir.is_dir():
        raise FileNotFoundError(f"model dir missing: {args.model_dir}")

    _ensure_sys_path(args.repo_dir.resolve())
    import torch
    import torchaudio
    from cosyvoice.cli.cosyvoice import AutoModel  # type: ignore

    env = {
        "gpu_available": bool(torch.cuda.is_available()),
        "gpu_name": torch.cuda.get_device_name(0) if torch.cuda.is_available() else None,
        "model_dir": str(args.model_dir.resolve()),
        "prompt_wav": str(prompt_wav),
        "fp16": fp16,
        "text": args.text,
        "text_chars": len(args.text),
        "instruct_official": INSTRUCT_OFFICIAL,
        "instruct_prod_broken": INSTRUCT_PROD_BROKEN,
        "api": "inference_instruct2 / inference_zero_shot",
    }
    print(json.dumps({"phase": "env", **env}, ensure_ascii=False, indent=2))

    t_load0 = time.perf_counter()
    model = AutoModel(
        model_dir=str(args.model_dir.resolve()),
        load_trt=False,
        load_vllm=False,
        fp16=fp16,
    )
    sample_rate = int(getattr(model, "sample_rate", 24000))
    load_ms = int((time.perf_counter() - t_load0) * 1000)
    print(f"model loaded sample_rate={sample_rate} load_ms={load_ms}")

    report: dict = {
        "env": {**env, "sample_rate": sample_rate, "load_ms": load_ms},
        "experiments": {},
        "conclusion": {},
    }

    # ---- A: non-stream official instruct2 ----
    a_meta, a_speech = _run_infer(
        model,
        args.text,
        prompt_wav,
        mode="instruct2",
        instruct=INSTRUCT_OFFICIAL,
        stream=False,
        text_frontend=True,
        label="A_raw",
    )
    a_path = out_dir / "A_raw.wav"
    _save_wav(a_path, a_speech, sample_rate)
    a_meta.update(_wav_meta(a_path, a_meta["generate_ms"]))
    report["experiments"]["A_raw"] = a_meta
    print(f"A_raw saved {a_path} duration_ms={a_meta['audio_duration_ms']} rtf={a_meta['rtf']:.3f}")

    # ---- A': frontend off ----
    a2_meta, a2_speech = _run_infer(
        model,
        args.text,
        prompt_wav,
        mode="instruct2",
        instruct=INSTRUCT_OFFICIAL,
        stream=False,
        text_frontend=False,
        label="A_frontend_off",
    )
    a2_path = out_dir / "A_frontend_off.wav"
    _save_wav(a2_path, a2_speech, sample_rate)
    a2_meta.update(_wav_meta(a2_path, a2_meta["generate_ms"]))
    report["experiments"]["A_frontend_off"] = a2_meta
    print(f"A_frontend_off saved duration_ms={a2_meta['audio_duration_ms']} rtf={a2_meta['rtf']:.3f}")

    # ---- A_zs: official zero_shot（生产 instruct2 失败后的回退形态）----
    az_meta, az_speech = _run_infer(
        model,
        args.text,
        prompt_wav,
        mode="zero_shot",
        instruct=ZERO_SHOT_PROMPT,
        stream=False,
        text_frontend=True,
        label="A_zero_shot",
    )
    az_path = out_dir / "A_zero_shot.wav"
    _save_wav(az_path, az_speech, sample_rate)
    az_meta.update(_wav_meta(az_path, az_meta["generate_ms"]))
    report["experiments"]["A_zero_shot"] = az_meta
    print(f"A_zero_shot saved duration_ms={az_meta['audio_duration_ms']} rtf={az_meta['rtf']:.3f}")

    # ---- A_broken: 复现生产缺 endofprompt（预期失败，写入证据）----
    try:
        ab_meta, ab_speech = _run_infer(
            model,
            args.text,
            prompt_wav,
            mode="instruct2",
            instruct=INSTRUCT_PROD_BROKEN,
            stream=False,
            text_frontend=False,
            label="A_broken_instruct",
        )
        ab_path = out_dir / "A_broken_instruct.wav"
        _save_wav(ab_path, ab_speech, sample_rate)
        ab_meta.update(_wav_meta(ab_path, ab_meta["generate_ms"]))
        ab_meta["unexpected_success"] = True
        report["experiments"]["A_broken_instruct"] = ab_meta
        print("A_broken_instruct unexpectedly succeeded")
    except Exception as exc:  # noqa: BLE001
        report["experiments"]["A_broken_instruct"] = {
            "label": "A_broken_instruct",
            "failed": True,
            "error_type": type(exc).__name__,
            "error": str(exc)[:500],
            "note": "生产 instruct 缺 <|endofprompt|> 时的失败证据",
        }
        print(f"A_broken_instruct failed as expected: {type(exc).__name__}: {exc}")

    # ---- B: stream, hard concat ----
    b_meta, b_speech, chunk_logs = _run_infer_stream(
        model,
        args.text,
        prompt_wav,
        instruct=INSTRUCT_OFFICIAL,
        text_frontend=True,
        label="B_stream",
        out_dir=out_dir,
        sample_rate=sample_rate,
    )
    b_path = out_dir / "B_stream_merged.wav"
    _save_wav(b_path, b_speech, sample_rate)
    b_meta.update(_wav_meta(b_path, b_meta["generate_ms"]))
    b_meta["chunks"] = chunk_logs
    report["experiments"]["B_stream_merged"] = b_meta
    print(
        f"B_stream_merged saved chunks={len(chunk_logs)} "
        f"duration_ms={b_meta['audio_duration_ms']} rtf={b_meta['rtf']:.3f}"
    )

    # ---- P: production-like path WITH corrected instruct（隔离拼接影响）----
    from audio_worker.backends.cosyvoice import (  # noqa: WPS433
        _concat_tensors_smooth,
        _split_speak_segments,
    )

    segs = _split_speak_segments(args.text, max_chars=72)
    p_parts = []
    p_chunk_logs = []
    t_p0 = time.perf_counter()
    for i, seg in enumerate(segs):
        t0 = time.perf_counter()
        chunks = list(
            model.inference_instruct2(
                seg,
                INSTRUCT_OFFICIAL,
                str(prompt_wav),
                stream=False,
                text_frontend=False,
            )
        )
        parts = [c["tts_speech"].cpu().float() for c in chunks if "tts_speech" in c]
        for j, part in enumerate(parts):
            if part.dim() == 1:
                part = part.unsqueeze(0)
            peak = float(part.abs().max().clamp(min=1e-6))
            leveled = part / peak * 0.90
            p_parts.append(leveled)
            p_chunk_logs.append(
                {
                    "segment_index": i,
                    "part_index": j,
                    "segment_text": seg,
                    "generate_ms": int((time.perf_counter() - t0) * 1000),
                    "samples": int(leveled.shape[-1]),
                    "audio_duration_ms": int(leveled.shape[-1] * 1000 / sample_rate),
                }
            )
    if len(p_parts) == 1:
        p_speech = p_parts[0]
    else:
        p_speech = _concat_tensors_smooth(p_parts, sample_rate, fade_ms=28.0)
    p_speech = p_speech.cpu().float()
    peak = float(p_speech.abs().max().clamp(min=1e-6))
    p_speech = (p_speech / peak * 0.92).clamp(-1.0, 1.0)
    p_generate_ms = int((time.perf_counter() - t_p0) * 1000)
    p_path = out_dir / "P_prod_path.wav"
    _save_wav(p_path, p_speech, sample_rate)
    p_meta = {
        "label": "P_prod_path",
        "segments": segs,
        "segment_count": len(segs),
        "generate_ms": p_generate_ms,
        "parts": p_chunk_logs,
        "note": "生产拼接逻辑 + 官方正确 instruct（含 endofprompt）；仅诊断对照",
        "instruct": INSTRUCT_OFFICIAL,
    }
    p_meta.update(_wav_meta(p_path, p_generate_ms))
    report["experiments"]["P_prod_path"] = p_meta
    print(f"P_prod_path saved segments={len(segs)} duration_ms={p_meta['audio_duration_ms']}")

    # ---- silence / waveform analysis ----
    silence = {}
    for name, path in [
        ("A_raw", a_path),
        ("A_frontend_off", a2_path),
        ("A_zero_shot", az_path),
        ("B_stream_merged", b_path),
        ("P_prod_path", p_path),
    ]:
        silence[name] = _analyze_silence(path)
        _try_plot(path, out_dir / f"waveform_{name}.png", silence[name])
    (out_dir / "silence_stats.json").write_text(
        json.dumps(silence, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    report["silence"] = {
        k: {
            "duration_ms": v["duration_ms"],
            "silence_ratio": v["silence_ratio"],
            "silence_interval_count": v["silence_interval_count"],
            "median_silence_ms": v["median_silence_ms"],
            "short_gap_count_20_120ms": v["short_gap_count_20_120ms"],
            "rms_threshold": v["rms_threshold"],
        }
        for k, v in silence.items()
    }
    report["conclusion"] = _conclude(report, silence)
    (out_dir / "diagnose_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    _write_markdown(out_dir / "diagnose_report.md", report, silence)
    print(json.dumps(report["conclusion"], ensure_ascii=False, indent=2))
    print(f"done -> {out_dir}")
    return 0


def _ensure_sys_path(repo: Path) -> None:
    for path in (ROOT, repo, repo / "third_party" / "Matcha-TTS"):
        text = str(path)
        if path.is_dir() and text not in sys.path:
            sys.path.insert(0, text)


def _run_infer(
    model,
    text: str,
    prompt_wav: Path,
    *,
    mode: str,
    instruct: str,
    stream: bool,
    text_frontend: bool,
    label: str,
):
    import torch

    t0 = time.perf_counter()
    if mode == "zero_shot":
        raw = list(
            model.inference_zero_shot(
                text,
                instruct,
                str(prompt_wav),
                stream=stream,
                text_frontend=text_frontend,
            )
        )
    else:
        raw = list(
            model.inference_instruct2(
                text,
                instruct,
                str(prompt_wav),
                stream=stream,
                text_frontend=text_frontend,
            )
        )
    generate_ms = int((time.perf_counter() - t0) * 1000)
    parts = []
    for item in raw:
        if isinstance(item, dict) and "tts_speech" in item:
            tensor = item["tts_speech"].cpu().float()
            if tensor.dim() == 1:
                tensor = tensor.unsqueeze(0)
            parts.append(tensor)
    if not parts:
        raise RuntimeError(f"{label}: empty speech")
    speech = parts[0] if len(parts) == 1 else torch.cat(parts, dim=-1)
    meta = {
        "label": label,
        "mode": mode,
        "instruct": instruct,
        "stream": stream,
        "text_frontend": text_frontend,
        "yield_count": len(parts),
        "generate_ms": generate_ms,
        "yield_samples": [int(p.shape[-1]) for p in parts],
    }
    return meta, speech


def _run_infer_stream(
    model,
    text: str,
    prompt_wav: Path,
    *,
    instruct: str,
    text_frontend: bool,
    label: str,
    out_dir: Path,
    sample_rate: int,
):
    import torch

    chunk_logs = []
    parts = []
    t_all0 = time.perf_counter()
    prev_end = t_all0
    for index, item in enumerate(
        model.inference_instruct2(
            text,
            instruct,
            str(prompt_wav),
            stream=True,
            text_frontend=text_frontend,
        )
    ):
        t_end = time.perf_counter()
        if not isinstance(item, dict) or "tts_speech" not in item:
            continue
        tensor = item["tts_speech"].cpu().float()
        if tensor.dim() == 1:
            tensor = tensor.unsqueeze(0)
        generate_ms = int((t_end - prev_end) * 1000)
        interval_ms = generate_ms
        duration_ms = int(tensor.shape[-1] * 1000 / sample_rate)
        head_sil, tail_sil = _edge_silence_ms(tensor, sample_rate)
        chunk_path = out_dir / f"B_chunk_{index:02d}.wav"
        _save_wav(chunk_path, tensor, sample_rate)
        log = {
            "task_id": "test_001",
            "chunk_index": index,
            "generate_start": prev_end - t_all0,
            "generate_end": t_end - t_all0,
            "sample_rate": sample_rate,
            "channels": 1,
            "audio_duration_ms": duration_ms,
            "audio_bytes": int(tensor.numel() * 2),
            "generate_ms": generate_ms,
            "arrival_interval_ms": interval_ms,
            "head_silence_ms": head_sil,
            "tail_silence_ms": tail_sil,
            "file": chunk_path.name,
        }
        chunk_logs.append(log)
        parts.append(tensor)
        prev_end = t_end
        print(
            f"  B chunk[{index}] dur={duration_ms}ms gen={generate_ms}ms "
            f"head_sil={head_sil}ms tail_sil={tail_sil}ms"
        )
    generate_ms = int((time.perf_counter() - t_all0) * 1000)
    if not parts:
        raise RuntimeError(f"{label}: empty speech")
    # 文档要求：先硬拼，不加淡入淡出
    speech = torch.cat(parts, dim=-1)
    meta = {
        "label": label,
        "stream": True,
        "text_frontend": text_frontend,
        "yield_count": len(parts),
        "generate_ms": generate_ms,
    }
    return meta, speech, chunk_logs


def _save_wav(path: Path, speech, sample_rate: int) -> None:
    import torch
    import torchaudio

    tensor = speech.cpu().float()
    if tensor.dim() == 1:
        tensor = tensor.unsqueeze(0)
    peak = float(tensor.abs().max().clamp(min=1e-8))
    # 仅做安全削峰，避免 clipping；不做响度美化
    if peak > 1.0:
        tensor = tensor / peak
    pcm = (tensor.clamp(-1.0, 1.0) * 32767.0).to(torch.int16)
    torchaudio.save(str(path), pcm, sample_rate, encoding="PCM_S", bits_per_sample=16)


def _wav_meta(path: Path, generate_ms: int) -> dict:
    with wave.open(str(path), "rb") as handle:
        rate = handle.getframerate()
        frames = handle.getnframes()
        channels = handle.getnchannels()
        sampwidth = handle.getsampwidth()
        duration_ms = int(frames * 1000 / rate) if rate else 0
    rtf = (generate_ms / duration_ms) if duration_ms > 0 else 0.0
    return {
        "file": path.name,
        "sample_rate": rate,
        "channels": channels,
        "sample_width_bytes": sampwidth,
        "frames": frames,
        "audio_duration_ms": duration_ms,
        "file_bytes": path.stat().st_size,
        "rtf": rtf,
    }


def _edge_silence_ms(tensor, sample_rate: int, thresh: float = 0.01) -> tuple[int, int]:
    import torch

    x = tensor.squeeze().abs()
    if x.numel() == 0:
        return 0, 0
    mask = x > thresh
    if not bool(mask.any()):
        return int(x.numel() * 1000 / sample_rate), int(x.numel() * 1000 / sample_rate)
    idx = torch.where(mask)[0]
    head = int(idx[0].item() * 1000 / sample_rate)
    tail = int((x.numel() - 1 - idx[-1].item()) * 1000 / sample_rate)
    return head, tail


def _analyze_silence(path: Path, frame_ms: float = 20.0) -> dict:
    import array
    import statistics

    with wave.open(str(path), "rb") as handle:
        rate = handle.getframerate()
        channels = handle.getnchannels()
        sampwidth = handle.getsampwidth()
        frames = handle.readframes(handle.getnframes())
    if sampwidth != 2:
        raise ValueError(f"expect 16-bit wav, got sampwidth={sampwidth}")
    samples = array.array("h")
    samples.frombytes(frames)
    if channels > 1:
        mono = samples[0::channels]
    else:
        mono = samples
    if not mono:
        return {
            "duration_ms": 0,
            "silence_ratio": 0,
            "silence_interval_count": 0,
            "median_silence_ms": 0,
            "short_gap_count_20_120ms": 0,
            "rms_threshold": 0,
            "intervals_ms": [],
        }

    frame_len = max(1, int(rate * frame_ms / 1000))
    rms_list: list[float] = []
    for i in range(0, len(mono), frame_len):
        chunk = mono[i : i + frame_len]
        if not chunk:
            break
        acc = 0.0
        for v in chunk:
            acc += float(v) * float(v)
        rms_list.append((acc / len(chunk)) ** 0.5)

    # 相对阈值：全局 RMS 中位数的 15%
    global_med = statistics.median(rms_list) if rms_list else 1.0
    thresh = max(50.0, global_med * 0.15)
    silent = [r < thresh for r in rms_list]
    intervals: list[tuple[int, int]] = []
    start = None
    for i, flag in enumerate(silent):
        if flag and start is None:
            start = i
        if not flag and start is not None:
            intervals.append((start, i))
            start = None
    if start is not None:
        intervals.append((start, len(silent)))

    intervals_ms = [
        (int(a * frame_ms), int(b * frame_ms), int((b - a) * frame_ms)) for a, b in intervals
    ]
    durations = [d for _, _, d in intervals_ms]
    short_gaps = [d for d in durations if 20 <= d <= 120]
    silence_frames = sum(1 for f in silent if f)
    return {
        "duration_ms": int(len(mono) * 1000 / rate),
        "silence_ratio": round(silence_frames / max(1, len(silent)), 4),
        "silence_interval_count": len(intervals_ms),
        "median_silence_ms": int(statistics.median(durations)) if durations else 0,
        "short_gap_count_20_120ms": len(short_gaps),
        "rms_threshold": round(thresh, 2),
        "global_rms_median": round(global_med, 2),
        "intervals_ms": intervals_ms[:80],
        "frame_ms": frame_ms,
    }


def _try_plot(wav_path: Path, png_path: Path, silence: dict) -> None:
    try:
        import array
        import wave as wave_mod

        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import numpy as np
    except Exception as exc:  # noqa: BLE001
        print(f"skip plot {wav_path.name}: {exc}")
        return

    with wave_mod.open(str(wav_path), "rb") as handle:
        rate = handle.getframerate()
        n = handle.getnframes()
        raw = handle.readframes(n)
        channels = handle.getnchannels()
    samples = np.frombuffer(raw, dtype=np.int16)
    if channels > 1:
        samples = samples.reshape(-1, channels)[:, 0]
    times = np.arange(len(samples)) / float(rate)
    frame = max(1, int(rate * 0.02))
    rms = []
    rms_t = []
    for i in range(0, len(samples), frame):
        chunk = samples[i : i + frame].astype(np.float64)
        rms.append(float(np.sqrt(np.mean(chunk * chunk))) if len(chunk) else 0.0)
        rms_t.append((i + len(chunk) / 2) / rate)

    fig, axes = plt.subplots(2, 1, figsize=(14, 6), sharex=True)
    axes[0].plot(times, samples, linewidth=0.3, color="#334155")
    axes[0].set_title(f"{wav_path.name} waveform")
    axes[0].set_ylabel("PCM")
    axes[1].plot(rms_t, rms, linewidth=0.8, color="#0f766e")
    axes[1].axhline(silence.get("rms_threshold", 0), color="#b91c1c", linestyle="--", linewidth=0.8)
    axes[1].set_title("short-time RMS")
    axes[1].set_xlabel("time (s)")
    axes[1].set_ylabel("RMS")
    fig.tight_layout()
    fig.savefig(png_path, dpi=120)
    plt.close(fig)
    print(f"plot -> {png_path.name}")


def _conclude(report: dict, silence: dict) -> dict:
    a = silence.get("A_raw", {})
    b = silence.get("B_stream_merged", {})
    p = silence.get("P_prod_path", {})
    a_short = a.get("short_gap_count_20_120ms", 0)
    b_short = b.get("short_gap_count_20_120ms", 0)
    a_bad = a_short >= 25 or a.get("silence_ratio", 0) > 0.35
    b_bad = b_short >= 25 or b.get("silence_ratio", 0) > 0.35
    yield_a = report["experiments"]["A_raw"].get("yield_count", 1)
    broken = report["experiments"].get("A_broken_instruct", {})
    notes = []

    if broken.get("failed"):
        notes.append(
            "关键证据：生产常用 instruct 缺少 <|endofprompt|>，"
            f"A_broken_instruct 失败为 {broken.get('error_type')}。"
            "官方 example 要求 instruct2 形如 "
            "'You are a helpful assistant. ...<|endofprompt|>'。"
        )
        notes.append(
            "生产 cosyvoice.py 在 instruct2 异常后回退 zero_shot；"
            "但 instruct2 的断言发生在后台线程，主线程可能先报 token2wav 尺寸错误，"
            "导致失败路径不稳定，是高优先级根因候选。"
        )

    if a_bad and b_bad:
        root = "model_or_input"
        notes.append("A/B 原始合并音频均有大量短静音间隙，优先查模型推理/参考音频/文本前端，而非播放器。")
    elif (not a_bad) and b_bad:
        root = "stream_concat"
        notes.append("A 正常而 B 异常：流式 chunk 或硬拼接引入断续。")
    elif a_bad and (not b_bad):
        root = "non_stream_path"
        notes.append("非流式异常、流式合并相对正常：检查 text_frontend 分句与非流式 yield 合并。")
    elif broken.get("failed"):
        root = "invalid_instruct_endofprompt"
        notes.append("官方格式 A/B 若听感正常，则逐字顿挫更可能来自错误 instruct / 失败回退，而非播放器。")
    else:
        root = "downstream_likely"
        notes.append("A/B 静音统计未见明显逐字间隙特征；若听感仍断，继续查播放器/传输（C/D）。")

    if yield_a > 1:
        notes.append(
            f"A_raw 在 stream=False 时仍有 {yield_a} 次 yield（官方 text_frontend 分句），"
            "句间硬拼可能造成句级顿挫，但通常不是逐字断续。"
        )
    p_short = p.get("short_gap_count_20_120ms", 0)
    notes.append(
        f"生产路径对照 P_prod_path short_gap={p_short}；"
        f"A_raw short_gap={a_short}；B short_gap={b_short}。"
    )
    conf = "high" if broken.get("failed") and not a_bad else ("medium" if a_bad or b_bad else "low_needs_listening")
    return {
        "most_likely_root": root,
        "confidence": conf,
        "notes": notes,
        "c_d_status": (
            "本脚本完成 A/B/P 与静音分析；C/D：当前桌面是整段 WAV 播放、非真流式 TTS。"
            "请先听 A_raw.wav；若自然，再听桌面现网结果对比。"
        ),
        "fix_suggestion": (
            "最小修复：instruct2 的 instruct_text 强制追加 <|endofprompt|>；"
            "禁止把决策/中文元信息送进 instruct；失败回退前先校验 token。"
            "待确认后再改生产代码。"
        ),
    }


def _write_markdown(path: Path, report: dict, silence: dict) -> None:
    lines = [
        "# CosyVoice3 逐字顿挫诊断报告",
        "",
        "## 环境",
        f"- GPU: {report['env'].get('gpu_name')}",
        f"- 模型: `{report['env'].get('model_dir')}`",
        f"- FP16: {report['env'].get('fp16')}",
        f"- sample_rate: {report['env'].get('sample_rate')}",
        f"- API: `{report['env'].get('api')}`",
        f"- 文本字数: {report['env'].get('text_chars')}",
        "",
        "## 实验指标",
        "",
        "| 实验 | 时长ms | 生成ms | RTF | yield数 | short_gap(20-120ms) | silence_ratio |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for key in ("A_raw", "A_frontend_off", "A_zero_shot", "B_stream_merged", "P_prod_path"):
        exp = report["experiments"].get(key, {})
        sil = silence.get(key, {})
        if exp.get("failed"):
            lines.append(f"| {key} | FAIL | - | - | - | - | - |")
            continue
        rtf = exp.get("rtf", 0) or 0
        lines.append(
            f"| {key} | {exp.get('audio_duration_ms')} | {exp.get('generate_ms')} | "
            f"{rtf:.3f} | {exp.get('yield_count', exp.get('segment_count'))} | "
            f"{sil.get('short_gap_count_20_120ms')} | {sil.get('silence_ratio')} |"
        )
    broken = report["experiments"].get("A_broken_instruct", {})
    lines.extend(["", "## 错误 instruct 对照", ""])
    if broken.get("failed"):
        lines.append(f"- `A_broken_instruct`: FAILED `{broken.get('error_type')}` — {broken.get('error')}")
    else:
        lines.append("- `A_broken_instruct`: 未按预期失败，需人工复核。")
    lines.extend(["", "## 结论", ""])
    conc = report.get("conclusion", {})
    lines.append(f"- 最可能根因: **{conc.get('most_likely_root')}**")
    lines.append(f"- 置信度: {conc.get('confidence')}")
    for note in conc.get("notes", []):
        lines.append(f"- {note}")
    lines.append(f"- C/D: {conc.get('c_d_status')}")
    lines.append(f"- 修复建议: {conc.get('fix_suggestion')}")
    lines.extend(
        [
            "",
            "## 试听建议",
            "1. 先听 `A_raw.wav`（官方正确 instruct2）。",
            "2. 再听 `A_zero_shot.wav`（生产回退形态）。",
            "3. 再听 `B_stream_merged.wav` / `P_prod_path.wav`。",
            "4. 桌面端整段播 `A_raw.wav` 即实验 C 近似验收。",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
