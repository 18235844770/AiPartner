# 语音模块 Phase 4 验证记录

**日期：** 2026-11-07  
**依据：** V1.1 设计文档 Phase 4（情绪语音）

## 交付

1. 六种 MBTI 的 `voice_expression` 数据文件：`persona/data/voice_expression_profiles.json`
2. 新初始化人格写入 `behavior_traits.voice_expression`（版本化）
3. 已有人格缺字段时按 MBTI 默认解析，不强制升版本
4. TTS 合成前读取 Emotion State（levels / primary / secondary）与 Persona 语音倾向
5. Audio Expression 生成 `speed` + `tts_instruction` 下发 Worker
6. Relationship 仍不参与表达（符合 V1.1）

## 验证

| 项 | 结果 |
|---|---|
| `test_voice_expression` + `test_audio_expression` + `test_persona` | 13 passed |
| ENFP 相对 INTJ：同情绪下语速/强度更高 | 断言通过 |
| 缺 persona/state 时降级 calm | 代码路径具备 |

## 说明

- 同一 `message_id` 已完成的 TTS 资产会复用，不会因后续情绪变化重合成。
- stub Worker 仍输出契约波形；听感差异要等真实 CosyVoice 打开后验证。
- 旧陪伴者可在下次人格版本更新时写入 `voice_expression`，当前靠 MBTI 默认兜底。

## 下一步

- Phase 5：流式 TTS + SSE `audio.*` 事件
- 或完成 Phase 1 门禁：真实 SenseVoice / CosyVoice 加载与显存峰值
