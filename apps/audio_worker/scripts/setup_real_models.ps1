# 安装真实 SenseVoice / CosyVoice 运行所需组件（Windows 原生）
# 用法（在 apps/audio_worker 下）:
#   powershell -ExecutionPolicy Bypass -File .\scripts\setup_real_models.ps1
#   powershell -ExecutionPolicy Bypass -File .\scripts\setup_real_models.ps1 -SkipCosyVoice
param(
    [switch]$SkipCosyVoice,
    [switch]$SkipAsr,
    [string]$CosyVoiceRepo = "https://github.com/FunAudioLLM/CosyVoice.git"
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

Write-Host "== Audio Worker root: $Root"

if (-not $SkipAsr) {
    Write-Host "== Install CUDA torch + funasr (ASR)"
    $Wheels = Join-Path $Root ".wheels"
    New-Item -ItemType Directory -Force -Path $Wheels | Out-Null
    $TorchWhl = Join-Path $Wheels "torch-2.5.1+cu121-cp311-cp311-win_amd64.whl"
    $TaWhl = Join-Path $Wheels "torchaudio-2.5.1+cu121-cp311-cp311-win_amd64.whl"
    if (-not (Test-Path $TorchWhl)) {
        Write-Host "Downloading torch wheel (Aliyun mirror)..."
        curl.exe -L --retry 3 -o $TorchWhl "https://mirrors.aliyun.com/pytorch-wheels/cu121/torch-2.5.1%2Bcu121-cp311-cp311-win_amd64.whl"
    }
    if (-not (Test-Path $TaWhl)) {
        Write-Host "Downloading torchaudio wheel (Aliyun mirror)..."
        curl.exe -L --retry 3 -o $TaWhl "https://mirrors.aliyun.com/pytorch-wheels/cu121/torchaudio-2.5.1%2Bcu121-cp311-cp311-win_amd64.whl"
    }
    uv pip install $TorchWhl $TaWhl
    # CosyVoice / onnxruntime 依赖约束
    uv pip install "numpy==1.26.4" "setuptools==69.5.1"
    uv pip install "funasr>=1.1.0" modelscope
}

if (-not $SkipCosyVoice) {
    $Vendor = Join-Path $Root "vendor"
    $Repo = Join-Path $Vendor "CosyVoice"
    New-Item -ItemType Directory -Force -Path $Vendor | Out-Null
    if (-not (Test-Path (Join-Path $Repo "cosyvoice\cli\cosyvoice.py"))) {
        Write-Host "== Clone CosyVoice into vendor/"
        if (Test-Path $Repo) { Remove-Item -Recurse -Force $Repo }
        git clone --recursive $CosyVoiceRepo $Repo
        Push-Location $Repo
        git submodule update --init --recursive
        Pop-Location
    } else {
        Write-Host "== CosyVoice repo already present"
    }

    Write-Host "== Install CosyVoice Python deps (Windows subset)"
    uv pip install `
        "numpy==1.26.4" `
        "setuptools==69.5.1" `
        "conformer==0.3.2" `
        "diffusers==0.29.0" `
        "HyperPyYAML==1.2.3" `
        "inflect==7.3.1" `
        "librosa==0.10.2" `
        "modelscope==1.20.0" `
        "networkx==3.1" `
        "omegaconf==2.3.0" `
        "onnx==1.16.0" `
        "onnxruntime==1.18.0" `
        "openai-whisper" `
        "protobuf==4.25" `
        "pyarrow==18.1.0" `
        "pyworld==0.3.4" `
        "soundfile==0.12.1" `
        "transformers==4.51.3" `
        "x-transformers==2.11.24" `
        "wetext==0.0.4" `
        "wget==3.2" `
        "gdown==5.1.0" `
        "matplotlib==3.7.5" `
        "lightning==2.2.4"

    $ModelDir = Join-Path $Root "models\tts\Fun-CosyVoice3-0.5B"
    if (-not (Test-Path (Join-Path $ModelDir "llm.pt"))) {
        Write-Host "== Download Fun-CosyVoice3-0.5B-2512 weights (ModelScope)"
        New-Item -ItemType Directory -Force -Path $ModelDir | Out-Null
        .\.venv\Scripts\python.exe -c @"
from modelscope import snapshot_download
snapshot_download('FunAudioLLM/Fun-CosyVoice3-0.5B-2512', local_dir=r'$ModelDir')
print('model ok', r'$ModelDir')
"@
    } else {
        Write-Host "== Model weights already present: $ModelDir"
    }
}

Write-Host "== Verify torch CUDA"
uv run python -c "import torch; print('cuda', torch.cuda.is_available(), torch.cuda.get_device_name(0) if torch.cuda.is_available() else None)"

Write-Host @"

Done.
Next:
  1. Copy .env.example -> .env
  2. Set ASR_BACKEND=sensevoice and/or TTS_BACKEND=cosyvoice3
  3. uv run uvicorn audio_worker.main:app --host 127.0.0.1 --port 8100
"@
