# 语音模块 Phase 2 验证记录

**日期：** 2026-11-07  
**依据：** V1.1 设计文档 Phase 2（语音输入）

## 交付

1. 桌面麦克风采集：`apps/desktop/src/services/microphone.ts`（16kHz mono PCM WAV）
2. ASR API 客户端：`apps/desktop/src/services/audio.ts`
3. 状态机：`apps/desktop/src/composables/useAudio.ts`
4. UI：`VoiceInput.vue` 接入 `ChatPanel.vue`（按住说话 / 点击切换）
5. Electron 允许 `media` 权限
6. 识别预览确认后复用现有 `sendMessage` → Turn SSE

## 验证

| 项 | 结果 |
|---|---|
| Electron / vue-tsc | 通过 |
| 麦克风 helper 脚本 | 通过 |
| `GET /api/audio/health`（8001 + stub worker） | ok |
| `POST .../asr` 上传 stub WAV | 200，返回 stub 文本并写入 `audio_tasks` |

## 使用注意

- 需同时运行 **FastAPI** 与 **Audio Worker**（`127.0.0.1:8100`）。
- 若桌面仍指向旧服务进程，重启 Electron / Python 服务以加载 audio 路由。
- 当前 ASR 后端为 stub；真实 SenseVoice 仍属 Phase 1 门禁未完成项。

## 下一步（Phase 3）

- Voice Profile、固定音色 TTS、`message.completed` 后合成、最小打断。
