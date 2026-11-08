# 语音模块 Phase 5 验证记录

**日期：** 2026-11-07  
**依据：** V1.1 设计文档 Phase 5（流式交互）

## 交付

1. 服务端 `POST .../tts/stream`：SSE 事件  
   `audio.started` / `audio.chunk` / `audio.completed` / `audio.failed` / `audio.cancelled`
2. WAV 分块工具：完整音频切成可独立播放的小 WAV（Base64 下发）
3. Audio Worker `POST /v1/tts/stream`：NDJSON 分块契约（便于后续换真实 CosyVoice 流）
4. 桌面端改为消费 TTS SSE，分块入队播放；流结束 `markStreamComplete`
5. 打断：AbortController 取消 SSE + 停播 + 尽力 cancel 任务

## 验证

| 项 | 结果 |
|---|---|
| `test_audio_stream` | 分块与 SSE 帧格式 |
| 桌面 vue-tsc | 通过 |

## 说明

- 当前 stub / 非流式模型路径仍是「先合成完整文件，再分块推送」，协议与边收边播已就绪。
- 真实 CosyVoice token 流可替换 Worker `/v1/tts/stream`，业务 SSE 契约不变。
- 未引入 WebSocket（符合 V1.1 决议）。

## 后续

- 接入真实 CosyVoice 流式推理
- 可选：把 `audio.*` 挂到 Turn SSE 同通道，进一步统一同步
