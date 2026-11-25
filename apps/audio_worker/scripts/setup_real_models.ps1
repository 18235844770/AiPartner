# 安装 SenseVoice 识别所需组件（Windows 原生）。本地语音合成已移除。
# 用法（在 apps/audio_worker 下）:
#   powershell -ExecutionPolicy Bypass -File .\scripts\setup_real_models.ps1
param(
    [switch]$SkipAsr
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
    # funasr 依赖约束
    uv pip install "numpy==1.26.4" "setuptools==69.5.1"
    uv pip install "funasr>=1.1.0" modelscope
}

Write-Host "== Verify torch CUDA"
uv run python -c "import torch; print('cuda', torch.cuda.is_available(), torch.cuda.get_device_name(0) if torch.cuda.is_available() else None)"

Write-Host @"

Done.
Next:
  1. Copy .env.example -> .env
  2. Set ASR_BACKEND=sensevoice
  3. uv run uvicorn audio_worker.main:app --host 127.0.0.1 --port 8100
"@
