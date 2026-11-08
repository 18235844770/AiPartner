# AI Companion Audio Worker

独立本地推理进程，与 FastAPI 业务进程隔离。默认 `stub` 后端用于契约联调；安装真实依赖后再切换。

**运行平台决议（Phase 1 门禁）：Windows 原生 + CUDA**（本机 RTX 3060 Ti / Driver 560.94）。不使用 WSL2，除非后续 Windows 原生推理失败再评估。

## 启动（stub）

```powershell
cd apps/audio_worker
uv sync
uv run uvicorn audio_worker.main:app --host 127.0.0.1 --port 8100
```

健康检查：`GET http://127.0.0.1:8100/health`

## 真实模型一键准备

```powershell
cd apps/audio_worker
# 建议把缓存放到 D 盘，避免 C: 空间不足：
$env:UV_CACHE_DIR='D:\AiLove\.cache\uv'
$env:TMP='D:\AiLove\.cache\tmp'; $env:TEMP=$env:TMP
powershell -ExecutionPolicy Bypass -File .\scripts\setup_real_models.ps1
```

脚本会：安装 CUDA torch（阿里云 wheel）、funasr、克隆 CosyVoice 到 `vendor/CosyVoice`、安装 TTS 依赖子集、经 ModelScope 下载 `Fun-CosyVoice3-0.5B-2512`。

注意：`numpy<2`、`setuptools==69.5.1`；实测显存峰值约 4.3GB。

## ASR（SenseVoice）

```powershell
# .env
ASR_BACKEND=sensevoice
ASR_MODEL_NAME=iic/SenseVoiceSmall
```

- 设备：CPU（设计约定）
- 权重首次运行由 FunASR / ModelScope 下载到 `models/asr`
- SenseVoice 情绪标签是**用户侧语音线索**，不得直接覆盖陪伴者 Emotion State
- 启用前核对模型权重许可与署名要求

## TTS（CosyVoice3）

```powershell
# .env
TTS_BACKEND=cosyvoice3
TTS_MODEL_NAME=Fun-CosyVoice3-0.5B-2512
COSYVOICE_REPO=./vendor/CosyVoice
TTS_FP16=true
```

- 设备：NVIDIA GPU，单实例单队列
- 需要参考音频（`reference_audio_path`）或默认 `vendor/CosyVoice/asset/zero_shot_prompt.wav`
- `instruction` 会拼进 CosyVoice3 prompt（`<|endofprompt|>`）
- 真实流式推理可替换 `/v1/tts/stream`；当前也可先整段合成再分块

## 接口

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/health` | 后端、加载状态、GPU、队列深度 |
| POST | `/v1/asr` | multipart：`audio` + 可选 `language` |
| POST | `/v1/tts` | JSON：`text`、可选参考音频路径与 instruction |
| POST | `/v1/tts/stream` | NDJSON 分块 WAV |
