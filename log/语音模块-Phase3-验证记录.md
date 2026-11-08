# 语音模块 Phase 3 验证记录

**日期：** 2026-11-07  
**依据：** V1.1 设计文档 Phase 3（基础语音输出）

## 交付

1. 默认 Voice Profile（stub 参考音频自动创建）
2. `POST .../tts`：按 `message_id` 归属校验、固定音色合成、资产落库
3. `GET .../assets/{id}` 下载；`POST .../tasks/{id}/cancel` 取消
4. `GET .../voices` 列表并确保默认音色
5. 桌面：`message.completed` 后自动 TTS 播放；气泡播放/暂停/停止；录音或新回合打断
6. 「自动朗读回复」开关

## 验证

| 项 | 结果 |
|---|---|
| OpenAPI 注册 TTS/voices/assets/cancel | 通过 |
| stub TTS 合成 | 200，生成 wav 资产 |
| 资产下载 | 200，`audio/wav` |
| 桌面 vue-tsc / electron tsc | 通过 |

## 说明

- Phase 3 使用中性表达（`calm`），情绪驱动留到 Phase 4。
- TTS 失败不影响文字气泡展示。
- 需 Audio Worker + 含 audio 路由的 FastAPI 同时运行；Electron 需重启以加载新 UI。

## 下一步

- Phase 4：Audio Expression 接入 Emotion levels 与 Persona Voice Expression。
