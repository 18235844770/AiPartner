"""CosyVoice3 后端。依赖官方仓库路径 + GPU torch；不可用时由工厂回退 stub。"""

from __future__ import annotations

import asyncio
import logging
import sys
import time
import wave
from pathlib import Path

from audio_worker.schemas import TtsRequest, TtsResult

logger = logging.getLogger(__name__)

# 官方 zero_shot_prompt.wav 对应文案（必须与 wav 内容一致；仅作克隆条件，不得当合成正文）
_OFFICIAL_PROMPT_TEXT = "希望你以后能够做的比我还好呦。"
_BAD_REF_TEXTS = {
    "这是默认参考音频对应的文字。",
    "这是默认参考音频对应的文字",
    "默认参考音频",
}


class CosyVoiceTtsBackend:
    name = "cosyvoice3"
    loaded = False

    def __init__(
        self,
        model_name: str,
        model_dir: Path,
        output_dir: Path,
        *,
        repo_dir: Path | None = None,
        default_prompt_wav: Path | None = None,
        fp16: bool = True,
    ) -> None:
        self.model_name = model_name
        self._model_dir = model_dir
        self._output_dir = output_dir
        self._repo_dir = repo_dir
        self._default_prompt_wav = default_prompt_wav
        self._fp16 = fp16
        self._model: object | None = None
        self._sample_rate = 24000
        self._counter = 0
        self._last_peak_vram_mb: float | None = None

    async def load(self) -> None:
        if self.loaded:
            return
        await asyncio.to_thread(self._load_sync)
        self.loaded = True

    def _load_sync(self) -> None:
        if not cosyvoice_available(self._repo_dir):
            raise RuntimeError("CosyVoice 依赖或仓库未就绪")
        self._ensure_sys_path()
        from cosyvoice.cli.cosyvoice import AutoModel  # type: ignore[import-not-found]

        self._model_dir.mkdir(parents=True, exist_ok=True)
        self._output_dir.mkdir(parents=True, exist_ok=True)
        model_path = self._resolve_model_dir()
        logger.info("Loading CosyVoice3 from %s", model_path)
        before = _cuda_used_mb()
        self._model = AutoModel(model_dir=str(model_path), load_trt=False, load_vllm=False, fp16=self._fp16)
        after = _cuda_used_mb()
        if after is not None and before is not None:
            self._last_peak_vram_mb = max(after - before, 0.0)
            logger.info("CosyVoice load delta VRAM ≈ %.1f MB", self._last_peak_vram_mb)
        self._sample_rate = int(getattr(self._model, "sample_rate", 24000))
        logger.info("CosyVoice3 loaded: sample_rate=%s", self._sample_rate)

    def _resolve_model_dir(self) -> Path:
        candidates = [
            self._model_dir,
            self._model_dir / "Fun-CosyVoice3-0.5B",
            self._model_dir / self.model_name,
        ]
        for path in candidates:
            if (path / "cosyvoice3.yaml").is_file():
                return path
        return Path(self.model_name)

    def _ensure_sys_path(self) -> None:
        if self._repo_dir is None:
            return
        repo = self._repo_dir.resolve()
        matcha = repo / "third_party" / "Matcha-TTS"
        for path in (repo, matcha):
            text = str(path)
            if path.is_dir() and text not in sys.path:
                sys.path.insert(0, text)

    async def synthesize(self, request: TtsRequest) -> TtsResult:
        if not self.loaded:
            await self.load()
        return await asyncio.to_thread(self._synthesize_sync, request)

    def _synthesize_sync(self, request: TtsRequest) -> TtsResult:
        assert self._model is not None
        import torch
        import torchaudio

        prompt_wav = self._resolve_prompt_wav(request.reference_audio_path, request.reference_text)
        instruct = self._safe_instruct(request.instruction)
        target_text = request.text.strip()
        if not target_text:
            raise ValueError("TTS 文本为空")

        self._counter += 1
        out_path = self._output_dir / f"cosyvoice_{self._counter:06d}.wav"
        t0 = time.perf_counter()
        if torch.cuda.is_available():
            torch.cuda.reset_peak_memory_stats()

        # 对齐诊断 A_raw：整段一次、官方 text_frontend=True、不做自研切段/响度重标定
        # （先前 text_frontend=False + 分段峰值归一 + volume 硬削峰 会引入明显顿挫/失真）
        speed = float(request.speed)
        logger.info(
            "CosyVoice synth start chars=%s speed=%.3f volume=%.3f instruct=%r prompt=%s",
            len(target_text),
            speed,
            float(request.volume),
            instruct,
            prompt_wav.name,
        )
        raw_chunks = self._infer(target_text, instruct, prompt_wav, speed=speed)
        speech_parts = [
            item["tts_speech"] for item in raw_chunks if isinstance(item, dict) and "tts_speech" in item
        ]
        if not speech_parts:
            raise RuntimeError("CosyVoice 未返回音频")
        logger.info("CosyVoice yield_count=%s", len(speech_parts))

        if len(speech_parts) == 1:
            speech = speech_parts[0]
        else:
            # 官方分句多段：轻交叉淡化，避免硬接点；不做逐段响度拉齐
            speech = _concat_tensors_smooth(speech_parts, self._sample_rate, fade_ms=20.0)
        speech = speech.cpu().float()
        if speech.dim() == 1:
            speech = speech.unsqueeze(0)
        # 先增益，再峰值限幅，避免「先归一再 *1.7 硬裁切」造成破碎感
        gain = max(0.1, min(2.0, float(request.volume)))
        speech = speech * gain
        peak = float(speech.abs().max().clamp(min=1e-6))
        if peak > 0.99:
            speech = speech / peak * 0.99
        speech_i16 = (speech.clamp(-1.0, 1.0) * 32767.0).to(torch.int16)
        torchaudio.save(str(out_path), speech_i16, self._sample_rate, encoding="PCM_S", bits_per_sample=16)
        duration_ms = max(1, int(speech_i16.shape[-1] * 1000 / self._sample_rate))
        elapsed_ms = int((time.perf_counter() - t0) * 1000)
        if torch.cuda.is_available():
            peak_mb = torch.cuda.max_memory_allocated() / (1024 * 1024)
            self._last_peak_vram_mb = round(peak_mb, 1)
            logger.info(
                "CosyVoice synth done duration_ms=%s latency_ms=%s peak_vram_mb=%.1f chars=%s",
                duration_ms,
                elapsed_ms,
                peak_mb,
                len(target_text),
            )
        else:
            logger.info("CosyVoice synth done duration_ms=%s latency_ms=%s", duration_ms, elapsed_ms)

        return TtsResult(
            file_path=str(out_path.resolve()),
            format="wav",
            sample_rate=self._sample_rate,
            duration_ms=duration_ms,
            model_name=self.model_name,
            backend=self.name,
        )

    def _infer(self, target_text: str, instruct: str, prompt_wav: Path, *, speed: float) -> list[object]:
        assert self._model is not None
        # 与官方 example / 诊断 A_raw 一致：启用 text_frontend
        kwargs: dict[str, object] = {"stream": False, "text_frontend": True}
        if abs(speed - 1.0) > 1e-6:
            kwargs["speed"] = speed

        # CosyVoice2/3: inference_instruct2(tts_text, instruct_text, prompt_wav)
        if hasattr(self._model, "inference_instruct2"):
            infer = getattr(self._model, "inference_instruct2")
            try:
                return list(infer(target_text, instruct, str(prompt_wav), **kwargs))
            except TypeError:
                kwargs.pop("speed", None)
                return list(infer(target_text, instruct, str(prompt_wav), **kwargs))
            except Exception:
                logger.exception("inference_instruct2 failed; falling back to zero_shot with official prompt text")

        # 回退 zero_shot：prompt_text = 风格提示 + endofprompt + 官方 wav 文案
        infer_zs = getattr(self._model, "inference_zero_shot")
        style = instruct.replace("<|endofprompt|>", "").strip()
        prompt_text = f"{style}<|endofprompt|>{_OFFICIAL_PROMPT_TEXT}"
        try:
            return list(infer_zs(target_text, prompt_text, str(prompt_wav), **kwargs))
        except TypeError:
            kwargs.pop("speed", None)
            return list(infer_zs(target_text, prompt_text, str(prompt_wav), **kwargs))

    def _resolve_prompt_wav(self, reference_audio_path: str | None, reference_text: str | None) -> Path:
        bundled = self._bundled_prompt_wav()
        ref_text = (reference_text or "").strip()
        # 占位文案 / stub 静音 wav 一律改用官方 prompt，避免念出“这是默认参考音频…”
        if ref_text in _BAD_REF_TEXTS or "默认参考音频" in ref_text:
            if bundled is None:
                raise FileNotFoundError("缺少 CosyVoice 官方 zero_shot_prompt.wav")
            logger.info("ignoring placeholder reference_text; using official prompt wav")
            return bundled

        if reference_audio_path:
            path = Path(reference_audio_path)
            if path.is_file() and "reference_stub" not in path.name.lower():
                return path
            logger.warning("invalid/stub reference wav %s; using official prompt", reference_audio_path)

        if self._default_prompt_wav and self._default_prompt_wav.is_file():
            return self._default_prompt_wav
        if bundled is not None:
            return bundled
        raise FileNotFoundError(
            "CosyVoice 需要可用参考音频或仓库 asset/zero_shot_prompt.wav"
        )

    def _bundled_prompt_wav(self) -> Path | None:
        if self._repo_dir is None:
            return None
        bundled = self._repo_dir / "asset" / "zero_shot_prompt.wav"
        return bundled if bundled.is_file() else None

    def _safe_instruct(self, instruction: str | None) -> str:
        return normalize_cosyvoice_instruct(instruction)


def normalize_cosyvoice_instruct(instruction: str | None) -> str:
    """CosyVoice3 instruct2/zero_shot 的 prompt 必须包含 <|endofprompt|>。"""
    text = (instruction or "Speak naturally and calmly.").strip()
    if _contains_cjk(text) or "意图" in text or "决策" in text or "参考音频" in text:
        logger.warning("rejecting unsafe CosyVoice instruct")
        text = "Speak naturally and calmly."
    text = text.replace("<|endofprompt|>", "").strip()
    if len(text) > 160:
        text = text[:160].rstrip()
    text = text or "Speak naturally and calmly."
    # 与官方 example 对齐，稳定韵律条件
    if not text.lower().startswith("you are a helpful assistant"):
        text = f"You are a helpful assistant. {text}"
    return f"{text}<|endofprompt|>"


def _contains_cjk(text: str) -> bool:
    return any("\u4e00" <= ch <= "\u9fff" for ch in text)


def cosyvoice_available(repo_dir: Path | None = None) -> bool:
    try:
        import torch  # noqa: F401
        import torchaudio  # noqa: F401
    except ImportError:
        return False
    if repo_dir is None:
        try:
            import cosyvoice.cli.cosyvoice  # noqa: F401
        except ImportError:
            return False
        return True
    repo = repo_dir.resolve()
    return (repo / "cosyvoice" / "cli" / "cosyvoice.py").is_file()


def _split_speak_segments(text: str, *, max_chars: int = 72) -> list[str]:
    """按句读断点切段，控制单段长度；短于 max 的文本整段返回。"""
    import re

    cleaned = re.sub(r"\s*\n+\s*", "。", text.strip())
    cleaned = re.sub(r"[。！？；]{2,}", "。", cleaned)
    cleaned = re.sub(r"\s{2,}", " ", cleaned).strip()
    if not cleaned:
        return []
    if len(cleaned) <= max_chars:
        return [cleaned]

    parts = re.split(r"(?<=[。！？；!?])", cleaned)
    parts = [p.strip() for p in parts if p and p.strip()]
    if not parts:
        return [cleaned]

    segments: list[str] = []
    buf = ""
    for part in parts:
        candidate = f"{buf}{part}"
        if buf and len(candidate) > max_chars:
            segments.append(buf)
            buf = part
        else:
            buf = candidate
        # 单句本身超长时硬切，避免模型 token 爆掉
        while len(buf) > max_chars:
            segments.append(buf[:max_chars])
            buf = buf[max_chars:]
    if buf:
        segments.append(buf)
    return segments or [cleaned]


def _concat_tensors(chunks: list[object]) -> object:
    import torch

    return torch.cat([c.cpu() if hasattr(c, "cpu") else c for c in chunks], dim=1)


def _concat_tensors_smooth(chunks: list[object], sample_rate: int, *, fade_ms: float = 28.0) -> object:
    """段间交叉淡化，消除硬拼接咔哒声与气口断层。"""
    import torch

    tensors = []
    for chunk in chunks:
        tensor = chunk.cpu() if hasattr(chunk, "cpu") else chunk
        tensor = tensor.float()
        if tensor.dim() == 1:
            tensor = tensor.unsqueeze(0)
        tensors.append(tensor)
    if not tensors:
        raise ValueError("empty speech chunks")
    if len(tensors) == 1:
        return tensors[0]

    fade = max(1, int(sample_rate * fade_ms / 1000.0))
    out = tensors[0]
    for nxt in tensors[1:]:
        n = min(fade, out.shape[-1] // 4, nxt.shape[-1] // 4)
        if n < 2:
            out = torch.cat([out, nxt], dim=-1)
            continue
        fade_out = torch.linspace(1.0, 0.0, n, dtype=out.dtype).view(1, -1)
        fade_in = torch.linspace(0.0, 1.0, n, dtype=nxt.dtype).view(1, -1)
        left = out[..., :-n]
        overlap = out[..., -n:] * fade_out + nxt[..., :n] * fade_in
        right = nxt[..., n:]
        out = torch.cat([left, overlap, right], dim=-1)
    return out


def _wav_duration_ms(path: Path) -> int:
    with wave.open(str(path), "rb") as handle:
        frames = handle.getnframes()
        rate = handle.getframerate() or 24000
        return int(frames * 1000 / rate)


def _cuda_used_mb() -> float | None:
    try:
        import torch

        if not torch.cuda.is_available():
            return None
        free_b, total_b = torch.cuda.mem_get_info()
        return (total_b - free_b) / (1024 * 1024)
    except Exception:
        return None
