# 语音模块 Phase 1 验证记录

**日期：** 2026-11-07  
**依据：** `word/AI Companion 语音交互模块接入设计文档.md` V1.1  
**环境：** Windows + NVIDIA GeForce RTX 3060 Ti 8GB / Driver 560.94 / CUDA 12.6 / Python 3.11

## 已完成交付

1. 独立 Audio Worker：`apps/audio_worker/`
   - `GET /health`
   - `POST /v1/asr`
   - `POST /v1/tts`
   - 默认 `stub` 后端（契约联调）
   - SenseVoice / CosyVoice 后端工厂与可选依赖入口
2. 业务侧 Audio 模块：`apps/server/app/modules/audio/`
   - Audio Expression 领域实现（levels 0–100 → intensity 0–1）
   - Worker HTTP 客户端
   - `/api/audio/health`、归属校验后的 ASR 接口
3. 模型配置扩展：`asr_model` / `tts_model`（provider=`local`）
4. Alembic `0016_audio_engine`：音色表、audio_tasks、audio_assets、配置约束

## 本地验证（stub）

| 项 | 结果 |
|---|---|
| `uv sync`（audio_worker） | 通过 |
| stub 单元测试 | 通过（2） |
| server Expression / client 测试 | 通过（8） |
| Worker `GET /health` | `status=ok`，asr/tts loaded，backend=stub |
| Worker `POST /v1/tts` | 生成 `outputs/stub_*.wav`，24kHz |
| GPU 在 stub 环境可见 | `gpu_available=false`（未装 torch，符合隔离） |
| Alembic `0016_audio_engine` | 已应用到本地 PostgreSQL |
| OpenAPI 注册 `/api/audio/*` | 通过 |

启动命令：

```powershell
cd apps/audio_worker
uv run uvicorn audio_worker.main:app --host 127.0.0.1 --port 8100
```

## 许可核查要点

| 组件 | 许可 | 状态 |
|---|---|---|
| CosyVoice / Fun-CosyVoice3 | Apache 2.0（项目与模型页标注） | 需在正式下载权重时再次核对卡片页 |
| SenseVoice 源码 | MIT | 已记录 |
| SenseVoice 官方权重 | 独立模型许可 + 署名要求 | **未最终确认**；启用真实 ASR 前必须核对 Hugging Face / 官方声明 |

## 门禁状态

| 项 | 结果 |
|---|---|
| CUDA 驱动可见 | 通过（nvidia-smi） |
| 业务 venv 含 torch | 否（符合隔离设计） |
| Stub Worker 健康检查 | 通过 |
| SenseVoice 真实加载 | 未执行（需 `uv sync --extra asr` + 权重下载） |
| CosyVoice 真实加载 / 显存峰值 | 未执行 |
| Windows 原生 vs WSL2 | **未落定**；进入 Phase 2 前必须二选一并记录 |

## 下一步

1. `alembic upgrade head` 应用 `0016`（若尚未执行）。
2. 独立环境安装 ASR extra，验证 SenseVoice CPU 推理。
3. 安装 CosyVoice3，测显存峰值与单队列延迟后，打开真实 TTS 推理。
4. Phase 2：Electron 麦克风采集 + ASR → 现有 Turn API。
