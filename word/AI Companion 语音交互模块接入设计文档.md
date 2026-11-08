# AI Companion 语音交互模块接入设计文档

**版本：** V1.1  
**模块：** Audio Engine（`app.modules.audio`）  
**状态：** 待实施（V1.0 审查修订稿）  
**适用项目：** AI Companion  
**技术架构：** Electron + Vue 3 + TypeScript + Python FastAPI  
**部署方式：** 本地部署、本地模型推理  
**修订说明：** 相对 V1.0，对齐现有模块路径、State 情绪量纲、Dialogue Turn/SSE 挂接、服务端表达控制权、Model Adapter 契约、Audio Worker 与 ARQ 分工，并砍掉重复的 `audio_sessions`。

---

# 一、建设目标

为 AI Companion 增加完整的语音输入与语音输出能力，使陪伴者能够通过语音与用户交流。

本模块实现 ASR 与 TTS，并与现有 Persona、Memory、Dialogue、State（Emotion / Relationship / Interaction / Motivation）深度集成。不引入独立的「Emotion Engine」命名；情绪与关系一律走现有 State 模块公开接口。

核心目标：

1. 用户能够通过麦克风与陪伴者交流。
2. 语音输入转换为文字后，复用现有 Dialogue Turn 流程。
3. 陪伴者使用固定、可配置的专属音色输出语音。
4. 语音输出根据当前情绪表现出不同的语气、语速和韵律。
5. 不同人格可以具有不同的语音表达风格。
6. 语音表达与文字表达保持一致。
7. 支持播放、暂停、停止与打断；流式合成在后续阶段接入。
8. 全部语音模型在本地运行，不依赖付费语音 API。

设计原则：

- 不改变现有 Dialogue Engine 的核心职责（Decision → Realization → 文本）。
- 语音能力作为独立模块接入，模块间只通过公开 Service 调用。
- 模型与业务逻辑解耦，支持后续替换。
- 音色属于长期稳定配置，情绪属于动态状态。
- 语音表达必须由陪伴者当前人格和情绪状态驱动，且由服务端计算。
- 语音功能异常不能影响原有文字交流。
- Quiet / `should_send=false` 时不得触发 TTS。

# 二、模型选型

## 2.1 语音识别 ASR

采用：

**SenseVoice-Small**

项目地址：https://github.com/QwenAudio/SenseVoice

模型地址：https://huggingface.co/FunAudioLLM/SenseVoiceSmall

主要能力：

- 中文语音识别。
- 英语、日语、韩语、粤语识别。
- 语种识别。
- 情绪识别。
- 音频事件识别。

主要用途：

将用户的语音转换为文本，作为普通用户消息进入现有 Dialogue Turn API。

注意：

- SenseVoice 的情绪识别结果是**用户侧语音情绪线索**，不能直接写入或覆盖陪伴者 Emotion State。
- V1 可将该线索作为带推断标记的可选 turn 元数据提供给 Decision 上下文；不得写成用户明确陈述的事实，也不得触发陪伴者情绪快照写入。
- Memory 提取若使用该线索，只能记为低置信度观察，并保留来源为 `asr_emotion_hint`。

部署建议：

- 优先使用 CPU 推理。
- 通过 VAD 进行语音分段。
- 对较长音频进行分段识别。
- 保留原始识别文本和识别元数据。
- 识别失败时允许用户切换文字输入。

## 2.2 语音合成 TTS

采用：

**Fun-CosyVoice3-0.5B-2512**

项目地址：https://github.com/QwenAudio/CosyVoice

模型地址：https://huggingface.co/FunAudioLLM/Fun-CosyVoice3-0.5B-2512

主要能力：

- 中文自然语音合成。
- 参考音频零样本音色克隆。
- 多语言语音合成。
- 自然语言指令控制。
- 情绪、语速、音量等表达控制。
- 流式语音生成（Phase 5 再接入）。

主要用途：

将陪伴者已经生成的文字转换为具有固定音色和动态情绪表达的语音。

部署建议：

- 使用 NVIDIA GPU 推理。
- 第一版单模型、单推理队列。
- 优先实现非流式合成，再接入流式输出。
- 使用独立 Python Worker 运行模型（不把 GPU 模型塞进 ARQ Worker）。

重要限制：

CosyVoice3 的音色克隆需要参考音频及其对应文本，不等同于通过文字描述直接设计音色。

V1 通过参考音频建立陪伴者音色，未来可以增加支持文字驱动音色设计的可选 TTS 引擎。

指令可靠性：自然语言 `tts_instruction` 可能不稳定。TTS Adapter 必须同时下发确定性参数（如 `speed`）与尽力而为的指令；指令效果异常时以降级参数合成，不得失败后改写文字或伪造情绪。

## 2.3 模型许可

- CosyVoice 项目及 Fun-CosyVoice3 模型使用 Apache 2.0 许可。
- SenseVoice 源代码采用 MIT 许可，官方模型权重需要遵守其独立模型许可及署名要求。
- Phase 1 交付「许可核查记录」；商业部署前应重新核对实际使用的模型权重、依赖和第三方组件许可。

# 三、整体技术架构

新增 Audio 模块，不改变现有模块之间的主要关系。

```text
Electron Desktop
      |
      | 音频采集 / 音频播放
      |
      v
FastAPI Application
      |
      +--------------------------+
      |                          |
      v                          v
 Audio Input               Audio Output
      |                          |
      v                          v
  VAD Service             Audio Expression
      |                          |
      v                          v
  ASR Adapter               TTS Adapter
  (via Model Adapter)     (via Model Adapter)
      |                          |
      v                          v
 ASR Worker                TTS Worker
 SenseVoice                CosyVoice3
      |                          |
      v                          v
 User text + optional      Audio asset
 asr_emotion_hint                |
      |                          v
      v                    Electron Player
 Existing Turn API
 (SSE text events)
      |
      v
 Persona / Memory / State
```

## 3.1 模块划分

后端路径必须落在现有约定下：

```text
apps/server/app/modules/audio/
├── domain/
│   ├── enums.py
│   ├── expression.py
│   └── schemas.py
│
├── services/
│   ├── asr_service.py
│   ├── tts_service.py
│   ├── vad_service.py
│   ├── audio_expression_service.py
│   ├── voice_profile_service.py
│   ├── audio_text_normalizer.py
│   └── audio_manager.py
│
├── repositories/
│   ├── voice_repository.py
│   ├── audio_task_repository.py
│   └── audio_asset_repository.py
│
├── adapters/
│   ├── asr_adapter.py
│   └── tts_adapter.py
│
└── api/
    ├── asr.py
    ├── tts.py
    ├── voices.py
    └── assets.py
```

说明：

- 依赖方向：API → Service → Repository。
- Audio Service 可调用 Persona / State / Dialogue / Identity 的**公开 Service**，禁止直接访问其他模块 Repository。
- 长驻推理进程代码可放在仓库内独立入口（如 `apps/audio_worker/`），由 FastAPI 通过 localhost HTTP 调用；不在每次请求中加载模型。

桌面端贴合现有结构（不使用虚构的 `modules/audio/` 树）：

```text
apps/desktop/src/
├── services/
│   ├── audio.ts              # API 客户端（ASR/TTS/voices/assets）
│   ├── microphone.ts         # 采集与格式转换
│   └── audio-player.ts       # 播放 / 暂停 / 停止 / 打断
├── composables/
│   └── useAudio.ts           # 录音、识别预览、播放状态机
└── components/
    ├── VoiceInput.vue
    ├── VoicePlayer.vue
    └── AudioSettings.vue
```

类型优先由 OpenAPI 生成，请求走统一 `services/http.ts`。

麦克风采集可使用 Renderer 的 Web API。参考音频上传、生成音频缓存路径与清理须经主进程受控能力；Renderer 不得直接访问任意文件系统。

## 3.2 Model Adapter 与调用日志

ASR / TTS 属于本地推理模型，必须纳入统一配置与可观测性：

1. 扩展 `ModelConfigKey`：
   - `asr_model`
   - `tts_model`
2. Provider 为 `local`；业务模块不得硬编码模型名或 API Key。
3. Audio 模块内的 `asr_adapter` / `tts_adapter` 只做协议转换，实际调用经 Model Adapter（或同等门面）转发到 Audio Worker。
4. 每次调用写入与现网一致的模型调用日志字段：`task_type`、`model_name`、`latency`、`status`、`error`、`trace_id`；音频任务另记 `input_duration_ms` / `output_duration_ms`（无 token 时允许为空）。
5. 模型失败时不得伪造人格、记忆或情绪变化；TTS 失败只影响语音通道。

## 3.3 Audio Worker 与 ARQ 分工

| 组件 | 职责 |
|---|---|
| FastAPI | 鉴权、编排、Audio Expression、任务元数据写入 PostgreSQL |
| 长驻 Audio Worker | 加载 SenseVoice / CosyVoice，执行推理，单实例单队列 |
| Redis + ARQ | 继续服务记忆提取、Embedding、State 维护、主动消息等既有任务 |
| PostgreSQL `audio_tasks` | ASR/TTS 任务的正式状态与错误记录 |

禁止：

- 在 ARQ Worker 进程内加载 CosyVoice GPU 模型。
- 每次请求重新加载模型。
- 多个 TTS 模型实例并行占满显存。

FastAPI 与 Audio Worker 通过 localhost HTTP（或等价本地 IPC）通信。Worker 健康检查、加载状态、显存峰值查询由 Worker 暴露，经 Audio Service 汇总。

若任务投递与业务写入需要强一致，可对「对话消息已落库后的 TTS 触发」使用现有 Outbox 模式；Outbox 投递目标是 Audio 编排，不是 ARQ 加载 GPU。

# 四、Dialogue 挂接契约（P0）

这是相对 V1.0 最重要的补全。

## 4.1 语音输入如何进入对话

```text
用户录音
  → Electron 采集为 WAV PCM 16kHz mono
  → POST /api/audio/asr（multipart，带归属校验）
  → ASR Worker 识别
  → 返回 text + 可选 user emotion meta
  → 用户确认或自动提交
  → 复用现有 POST turn / SSE 流式接口提交文本
```

V1 **不**新增独立 audio-turn API。ASR 只负责「语音 → 文本（+ 元数据）」；交流决策、Quiet、Realization、SSE 文本事件全部走现有 Dialogue Turn。

可选 turn 元数据：

```json
{
  "input_modality": "voice",
  "asr_task_id": "uuid",
  "asr_emotion_hint": {
    "label": "sad",
    "source": "sensevoice",
    "confidence": null,
    "inferred": true
  }
}
```

约束：

- `asr_emotion_hint` 仅作 Decision 上下文的用户侧线索。
- 不得直接调用 State 写入接口修改陪伴者情绪。
- 不得在 Memory 中写成用户明确表达的事实。

## 4.2 语音输出何时触发

```text
Turn 决策
  → 若 Quiet 或 should_send=false：不创建 TTS 任务，直接 turn.completed(outcome=quiet)
  → Realization 生成文字
  → SSE：message.started / message.delta / message.completed
  → message.completed 之后（V1：全文完成后再合成，不分句流式）
  → Audio Expression（服务端）
  → 创建 audio_task(type=tts) 绑定 message_id / turn_id / companion_id
  → TTS Worker 合成
  → 写入 audio_assets
  → 客户端按 message_id 拉取或接收音频就绪事件
```

规则：

1. TTS 只朗读已确定的陪伴者消息文本；不得改写 Dialogue 输出。
2. 若需朗读规范化（数字、省略号等），由 Audio 模块 `audio_text_normalizer` 生成 `speak_text`，并保存 `source_text` 与 `speak_text` 映射；界面仍展示原始 `source_text`。
3. V1 主动消息（proactive）：在用户开启语音回复时，与普通回复同样在 `message.completed` 后触发 TTS。
4. 同一 `message_id` 默认只保留一份有效 TTS 资产；重试覆盖或标记旧任务取消。

## 4.3 与文字 SSE 的同步

沿用现有文字事件：`turn.started`、`message.started`、`message.delta`、`message.completed`、`turn.completed`、`turn.failed`、`turn.cancelled`。

音频控制面事件（V1 可通过同一会话的附加 SSE 通道，或独立 `GET/POST` 轮询任务状态；Phase 5 统一进流式）：

- `audio.started`
- `audio.ready`（非流式：资产可下载）
- `audio.chunk`（仅 Phase 5 流式）
- `audio.completed`
- `audio.failed`
- `audio.cancelled`

每个音频事件必须包含：`turn_id`、`message_id`、`task_id`、递增 `sequence`。客户端用 `message_id` 关联气泡，用 `sequence` 去重。

## 4.4 打断

当用户开始新一轮录音，或主动停止播放时：

1. 取消未完成的 TTS 任务（Worker 协作取消）。
2. 停止当前播放并清空未播缓冲。
3. 更新 `audio_tasks.status=cancelled`。
4. 已完成的文字消息保持不变。

Phase 3 即要求「停播 + 取消任务」；Phase 5 再完善流式分块打断。

# 五、语音输入设计

## 5.1 输入流程

第一版支持：

1. 按住说话：按下开始录音，松开结束。
2. 点击录音：开始录音，再次点击结束。

V1 不实现持续监听和自动语音唤醒。

## 5.2 音频格式

统一输入格式：

- 容器：WAV。
- 编码：PCM 16-bit。
- 声道：单声道。
- 采样率：优先 16kHz。

Electron 端负责采集和初步格式转换，Python 端进行格式校验。

## 5.3 识别结果

ASR 返回：

```json
{
  "task_id": "uuid",
  "text": "今天工作有点累",
  "language": "zh",
  "emotion": "sad",
  "audio_events": [],
  "duration_ms": 3200,
  "confidence": null,
  "status": "completed"
}
```

说明：

- `confidence` 无可靠模型输出时允许为空。
- `emotion` 为用户语音情绪线索，不得写入陪伴者 Emotion State。
- 用户原始录音默认不永久保存；若短期缓存用于重试，须可清理并归属校验。

# 六、语音输出设计

## 6.1 输出流程

见第四章。客户端**不得**自行拼装情绪指令调用正式 TTS。

## 6.2 音色管理

每个 Companion 绑定一个默认 Voice Profile。

```json
{
  "voice_id": "uuid",
  "companion_id": "uuid",
  "voice_name": "艺",
  "engine": "cosyvoice3",
  "model": "Fun-CosyVoice3-0.5B-2512",
  "reference_audio_path": "voices/{companion_id}/{voice_id}/reference.wav",
  "reference_text": "参考音频对应的完整文字",
  "reference_checksum": "sha256:...",
  "language": "zh",
  "default_speed": 1.0,
  "is_default": true,
  "enabled": true
}
```

音色配置要求：

1. 每个陪伴者至少绑定一个默认音色。
2. 支持上传参考音频与对应文本。
3. 支持试听、更换、多配置与设置默认。
4. 音色配置与人格版本、情绪状态分离（音色表独立；人格只存表达倾向）。
5. 数据库约束：同一 `companion_id` 至多一个 `is_default=true`（部分唯一索引）。
6. 更换参考音频时更新 checksum；旧文件按清理策略删除或归档，不在 PostgreSQL 存大文件。

音色属于陪伴者长期身份配置，不能因为情绪变化而重新生成基础音色。

## 6.3 正式 TTS 请求（服务端计算表达）

客户端正式合成请求只允许：

```json
{
  "companion_id": "uuid",
  "message_id": "uuid",
  "voice_profile_id": null
}
```

服务端步骤：

1. `get_owned_companion(user_id, companion_id)` 归属校验。
2. 校验 `message_id` 属于该用户与陪伴者，且角色为 companion，内容非空。
3. 读取当前 Persona（含 Voice Expression）、Emotion State。
4. 读取该回合已校验决策中的 Realization 相关字段（见 7.8）。
5. Audio Expression 生成内部契约。
6. 规范化 `speak_text`。
7. 调用 TTS Adapter → Worker。

禁止客户端在正式路径上传 `expression` / `tts_instruction`。

试听接口（`POST /api/audio/voices/{voice_id}/preview`）可接受受控 preview 参数（测试文本 + 有限情绪枚举），仍须归属校验，不得写 State。

# 七、情绪语音表达系统

## 7.1 设计原则

TTS 不直接读取全部 Emotion State 并自行判断表达方式。

由 Audio Expression 负责：

```text
Persona Voice Expression（persona_versions 数据）
      |
Emotion State（levels + primary/secondary）
      |
Validated Decision cues（primary_action / motivations）
      |
      v
Audio Expression
      |
      v
TTS Instruction + deterministic params
```

V1：**Relationship State 只读可观测，不参与 Audio Expression 计算。** 图中不再把 Relationship 作为表达输入，避免无规则的隐含行为。后续版本若引入，须单独增补映射表与测试。

## 7.2 情绪量纲（与现网对齐）

现网 State 约定：

- `EmotionState.levels[key]`：十维情绪强度，**0～100**。
- `EmotionState.intensity`：主情绪整体强度快照，**0～1**。
- `EmotionState.primary` / `secondary`：主次情绪标签（可为中文展示名）。

Audio Expression **主输入**：

1. 将 `primary` 归一到 `EMOTION_KEYS`（joy、affection、longing、comfort、excitement、sadness、anxiety、jealousy、anger、hurt；calm 视为无明显情绪修饰）。
2. 取 `level = levels[primary_key]`（0～100）作为表达强度主依据。
3. `EmotionState.intensity`（0～1）仅作校验与兜底：当 levels 缺失或全 0 时，用 `intensity * 100`。

禁止把 0～100 与 0～1 混写进同一字段而不标注单位。

## 7.3 情绪映射

| 情绪 key | 语音表达方向 |
|---|---|
| joy | 开心、轻快、自然 |
| affection | 温柔、亲近 |
| longing | 温柔、略带思念 |
| comfort | 放松、平和 |
| excitement | 兴奋、有活力 |
| sadness | 低落、缓慢 |
| anxiety | 犹豫、略显不安 |
| jealousy | 带有酸意和轻微不满 |
| anger | 坚定、有力度 |
| hurt | 委屈、克制、略带失落 |
| calm / 无显著情绪 | 不产生明显情绪修饰 |

## 7.4 情绪组合

允许多个情绪同时影响语音：主情绪决定基调，次要情绪（来自 `secondary` 与较高的 levels）做有限修饰。

例如：

- 开心 + 亲密：整体轻快，语气柔和。
- 想念 + 不安：语速略慢，略犹豫，保留亲近。
- 嫉妒 + 委屈：轻微不满，克制，不攻击。
- 愤怒 + 委屈：更坚定，可稍快，不强制喊叫。

## 7.5 情绪强度分档

对主情绪 `level`（0～100）：

| level | 表达处理 |
|---|---|
| 0～19 | 不产生明显情绪修饰 |
| 20～39 | 轻微语气变化 |
| 40～59 | 中等情绪表达 |
| 60～79 | 明显情绪表达 |
| 80～100 | 强烈表达，但避免夸张失真 |

情绪数值不能直接等同于音量。愤怒值高不代表必须提高音量，委屈值高也不代表必须哭腔。

内部输出字段 `intensity` **统一为 0～1**，由 `level / 100` 得到，避免与 State 快照字段混淆时在文档中写明「expression.intensity ∈ [0,1]，来源于 level」。

## 7.6 人格差异

同一种情绪允许不同人格产生不同语音表达（由 Voice Expression Profile 调节，而非改情绪定义）。

例如：

- ENFP：开心更活泼；兴奋语速更快；委屈更直接。
- INFP：开心更柔和；亲密更细腻；委屈更低落。
- INTJ：开心相对克制；愤怒坚定；亲密不过度甜腻。

## 7.7 Audio Expression 输出结构

```json
{
  "primary_emotion": "joy",
  "secondary_emotions": ["affection"],
  "intensity": 0.65,
  "intensity_source_level": 65.0,
  "expression_style": "warm_and_lively",
  "speed": 1.05,
  "volume": 1.0,
  "pause_style": "natural",
  "tts_instruction": "用自然、轻快、亲近的语气表达，带有明显的愉悦感，但不要夸张"
}
```

字段说明：

- `intensity`：表达强度，**0～1**。
- `intensity_source_level`：来源的 levels 值，**0～100**，便于审计。
- 其余字段为内部统一表达契约；TTS Adapter 转换为 CosyVoice 实际参数。

Audio Expression 不得修改 Emotion State。

## 7.8 Realization / Decision 输入（已定义）

V1 从**已校验**的决策结果读取以下线索，不把模型原始 JSON 直接塞给 TTS：

| 字段 | 用途 |
|---|---|
| `primary_action` | respond/share/ask/react/continue/close；quiet 已在上游拦截 |
| `emotional_motivation` | 若存在，辅助选择表达侧重点 |
| `relationship_motivation` | V1 可记录到任务元数据，**不**驱动音色参数 |
| `motivation.summary` / `reasoning_summary` | 仅用于生成更贴切的 `tts_instruction` 摘要，须截断与消毒 |

Python 拥有最终表达参数裁定权；LLM 不得在 Realization 文本中夹带隐藏 TTS 指令。

## 7.9 情绪表达优先级

1. 不把多个情绪数值简单相加。
2. 优先主情绪（primary / dominant level）。
3. 保留重要次要情绪做有限修饰。
4. 用 Voice Expression Profile 调节表现幅度。
5. 消除互相冲突的指令（例如同时要求「大声」与「低落」时以主情绪与人格克制规则为准）。

# 八、人格与语音表达的关系

增加 Voice Expression Profile，作为 **Persona 版本数据** 的一部分，不得只活在业务硬编码里。

## 8.1 数据位置

写入 `persona_versions` 的结构化数据（建议 `behavior_traits.voice_expression` 或 archive 下独立经校验的对象），并满足：

- 随人格版本号变更。
- 修改必须创建新版本并记录变更原因。
- 初始值进入六种 MBTI 模板 JSON（数据化初始化，幂等脚本）。
- 普通对话模型输出不得直接覆盖该配置。

## 8.2 结构

```json
{
  "voice_expression": {
    "expressiveness": 0.8,
    "speaking_pace": 1.0,
    "intonation_variation": 0.8,
    "emotional_expressiveness": 0.8,
    "pause_preference": 0.5,
    "directness": 0.7
  }
}
```

参数解释：

- `expressiveness`：声音表现力。
- `speaking_pace`：基础语速。
- `intonation_variation`：语调变化幅度。
- `emotional_expressiveness`：情绪表达程度。
- `pause_preference`：停顿倾向。
- `directness`：表达直接程度。

最终语音表达：

**稳定音色（Voice Profile） + 稳定人格语音倾向（Persona 版本） + 动态情绪表达（Audio Expression）**。

# 九、数据库设计

不将大体积音频写入 PostgreSQL。结构变更只用 Alembic。

所有 Audio API 必须经服务端归属校验（如 `get_owned_companion`），不得仅凭客户端传入的 `companion_id` 认定权限。表以 `companion_id` 为范围键；用户归属通过 Companion 所有权间接保证。需要时查询侧 join 校验。

## 9.1 companion_voice_profiles

| 字段 | 说明 |
|---|---|
| id | UUID PK |
| companion_id | FK，归属范围 |
| voice_name | 名称 |
| engine | 如 cosyvoice3 |
| model_name | 模型标识 |
| reference_audio_path | 本地路径 |
| reference_text | 参考文本 |
| reference_checksum | 校验和 |
| language | 语言 |
| default_speed | 默认语速 |
| is_default | 是否默认 |
| enabled | 是否启用 |
| created_at / updated_at | 时间 |

约束：

- `UNIQUE` 部分索引：`(companion_id) WHERE is_default AND enabled`（或等价：每个 companion 至多一个 default）。
- 参考音频文件在本地目录；库中只存路径与 checksum。

## 9.2 audio_tasks

| 字段 | 说明 |
|---|---|
| id | UUID PK |
| companion_id | FK |
| conversation_id | 可选 |
| turn_id | 可选，TTS 关联回合 |
| message_id | TTS 必填；ASR 可空 |
| voice_profile_id | TTS 使用的音色 |
| task_type | `asr` / `tts` |
| task_status | pending/running/completed/failed/cancelled |
| model_name | 实际模型 |
| speak_text | TTS 朗读文本（可空） |
| source_text | 原始消息文本（可空） |
| expression_json | 服务端计算的表达快照（可空） |
| error_code / error_message | 错误 |
| duration_ms | 耗时 |
| created_at / completed_at | 时间 |

## 9.3 audio_assets

| 字段 | 说明 |
|---|---|
| id | UUID PK |
| companion_id | FK |
| audio_task_id | FK |
| message_id | 与消息关联（TTS） |
| file_path | 本地路径 |
| format | wav 等 |
| sample_rate | 如 24000 |
| duration_ms | 时长 |
| file_size | 大小 |
| checksum | 校验 |
| created_at | 时间 |

## 9.4 不创建 audio_sessions

V1.0 的 `audio_sessions` 与现有 `conversation_id` / turn 生命周期重叠，**砍掉**。录音与播放状态由桌面端状态机 + `audio_tasks` 表达即可。

## 9.5 数据管理原则

- PostgreSQL 保存路径与元数据；音频在本地目录。
- 参考音频与生成音频分目录。
- 提供清理策略；用户可删除自己的录音缓存与生成音频。
- 不默认永久保存所有用户原始录音。
- 应用重启后音色配置与资产元数据可恢复。

# 十、API 接口设计

所有接口校验当前用户对 `companion_id` 的所有权。

## 10.1 语音识别

`POST /api/audio/asr`

请求：multipart/form-data，字段含 `companion_id`、`audio`、可选 `language`、`conversation_id`。

响应：

```json
{
  "task_id": "uuid",
  "text": "今天工作有点累",
  "language": "zh",
  "emotion": "sad",
  "status": "completed"
}
```

## 10.2 语音合成（正式）

`POST /api/audio/tts`

请求：

```json
{
  "companion_id": "uuid",
  "message_id": "uuid",
  "voice_profile_id": null
}
```

响应：

```json
{
  "task_id": "uuid",
  "status": "completed",
  "message_id": "uuid",
  "audio_url": "/api/audio/assets/{audio_id}",
  "format": "wav",
  "sample_rate": 24000
}
```

异步场景可先返回 `status=pending|running`，客户端轮询任务或等待 `audio.ready`。

## 10.3 音色列表 / 创建 / 更新

- `GET /api/audio/voices?companion_id=...`
- `POST /api/audio/voices`（上传参考音频、参考文本、名称）
- `PUT /api/audio/voices/{voice_id}`（名称、语速、语言、默认音色）

## 10.4 音色试听

`POST /api/audio/voices/{voice_id}/preview`

允许受控测试文本与有限情绪枚举；服务端生成临时 Expression，不写 State，不绑定正式 `message_id`。

## 10.5 资产下载

`GET /api/audio/assets/{audio_id}`

归属校验后返回音频文件。

## 10.6 任务取消

`POST /api/audio/tasks/{task_id}/cancel`

用于打断。

## 10.7 流式语音（Phase 5）

**架构决议：不引入 WebSocket 作为 V1/V1.1 默认音频传输。**

- V1：HTTP 非流式合成 + 资产下载。
- Phase 5：优先使用与文字一致的 **SSE 业务事件** 推送 `audio.*` 元数据，音频分块可用 Base64 字段或并行 HTTP 分块拉取；控制面字段必须含 `turn_id`、`message_id`、`task_id`、`sequence`。
- 若未来确需 WebSocket 仅承载媒体二进制，必须先修订技术架构文档，并保持控制面事件字段与 SSE 契约一致。

# 十一、桌面端交互设计

第一版提供：

1. 麦克风录音按钮。
2. 录音状态显示。
3. 识别文本预览与确认发送。
4. 语音播放 / 进度 / 暂停 / 继续 / 停止。
5. 打断当前语音。
6. 语音设置与音色试听入口。

语音交互状态：

- `idle`
- `recording`
- `recognizing`
- `thinking`（复用文字 turn 进行中）
- `synthesizing`
- `playing`
- `interrupted`
- `failed`

语音输出失败时，文字回复仍然正常展示。Quiet 只结束加载，不生成空语音气泡。

# 十二、模型运行与资源管理

## 12.1 硬件环境

当前开发环境：

- NVIDIA GPU：8～11GB 显存。
- 系统内存：32GB。
- 本地模型推理。
- Windows 桌面端为主要使用场景。

## 12.2 资源分配

| 模块 | 运行方式 |
|---|---|
| SenseVoice | CPU 优先（Audio Worker） |
| CosyVoice3 | NVIDIA GPU（Audio Worker） |
| BGE-M3 | CPU 优先（既有 local embedding） |
| DeepSeek | 远程模型 API |
| FastAPI | CPU |
| ARQ Worker | CPU 后台任务（不含 TTS GPU） |
| Electron | 本地桌面进程 |

## 12.3 显存管理

必须实现：

- TTS 模型单实例加载。
- TTS 推理任务单队列。
- 禁止多个请求重复加载模型。
- 支持任务取消。
- 支持模型加载状态查询。
- 记录显存峰值。
- CUDA OOM 时返回可恢复错误。
- 不允许模型异常导致整个 FastAPI 进程退出。

Phase 1 门禁：在锁定「单实例单队列」前，必须实测显存峰值、单条延迟与队列堆积表现，并留下记录。

第一版不要求 ASR 与 TTS 同时占用 GPU。

## 12.4 环境隔离

使用独立 Python 环境运行 CosyVoice3 / SenseVoice Worker。

原因：

- 依赖可能与主业务冲突。
- PyTorch / CUDA 版本需单独管理。
- 避免语音模型升级影响 FastAPI。

在正式选择 Windows 原生或 WSL2 之前，完成 CUDA、PyTorch 与模型加载验证；**未通过不得进入 Phase 2**。

# 十三、实施阶段

## Phase 1：模型部署

- 安装 SenseVoice、CosyVoice3，下载权重。
- 验证 CUDA 环境（原生或 WSL2 二选一落定）。
- ASR / TTS 独立测试；显存峰值与延迟记录。
- 许可核查记录。
- 可运行的 ASR/TTS Worker 与健康检查。

## Phase 2：语音输入

- Electron 麦克风采集、VAD、ASR、文本预览。
- 提交至现有 Dialogue Turn API。
- 可选 `asr_emotion_hint` 元数据通路（不写 State）。

## Phase 3：基础语音输出

- Voice Profile；固定音色合成；播放。
- `message.completed` 后服务端 TTS。
- **最小打断：停播 + 取消任务。**
- TTS 失败不影响文字。

## Phase 4：情绪语音

- Audio Expression；接入 Emotion levels 与 Persona Voice Expression。
- 多情绪修饰；音色在不同情绪下身份一致。
- Adapter 降级策略验证。

## Phase 5：流式交互

- 流式 TTS + SSE `audio.*` 事件。
- 分块播放与完善打断。
- 异常恢复；语音与文字同步展示。

# 十四、测试与验收标准

## 14.1 ASR

普通话、快速说话、长句、停顿、中英混合、噪声、不同麦克风。

## 14.2 TTS

同一音色同一文本，覆盖十维情绪听感；检查音色一致、不过度夸张、无损坏与错误断句。

## 14.3 人格

六种 MBTI 配置听感差异；不能只靠语速区分。

## 14.4 状态与决策一致性

- 文字开心时语音不得明显悲伤。
- Quiet 不产生 TTS 任务。
- TTS 不修改 Emotion State，不改写消息文本。
- `asr_emotion_hint` 不写入陪伴者情绪快照。
- 正式 TTS 接口拒绝客户端自定义 `tts_instruction`。
- 情绪状态未变时，不得无依据随机切换语气。

## 14.5 工程验收

- 模型只加载一次；连续合成不重复加载。
- TTS 异常不影响文字。
- 可打断；取消后无残余播放。
- 归属校验拒绝跨用户资产访问。
- 音频可清理；OOM 可恢复；重启后音色配置可恢复。
- ASR/TTS 调用日志可按 `task_type` / `trace_id` 追踪。

# 十五、V1 不实现的内容

- 实时语音唤醒词与全天候监听。
- 语音实时双向全双工打断对话。
- 语音情绪自动修改陪伴者自身情绪。
- Relationship State 驱动语音参数。
- 声音训练 / 微调 / 多人声纹。
- 语音通话模拟；多陪伴者同时语音。
- 文字描述直接生成全新音色。
- 默认 WebSocket 音频传输。

# 十六、最终技术决策

| 项目 | 确定方案 |
|---|---|
| ASR | SenseVoice-Small |
| TTS | Fun-CosyVoice3-0.5B-2512 |
| 音色 | 参考音频零样本克隆 |
| 情绪控制 | 服务端 Audio Expression |
| 人格语音差异 | Persona 版本内 Voice Expression Profile |
| 情绪量纲 | levels 0～100 为主；expression.intensity 输出 0～1 |
| Relationship | V1 不参与表达计算 |
| 音频格式 | 输入 16kHz PCM WAV；输出 24kHz WAV |
| ASR 推理 | CPU 优先，长驻 Worker |
| TTS 推理 | NVIDIA GPU，长驻 Worker 单队列 |
| 模型配置 | Model Adapter：`asr_model` / `tts_model` |
| 后台任务 | ARQ 不跑 GPU TTS；PG `audio_tasks` 记状态 |
| 对话挂接 | 复用现有 Turn + SSE；Quiet 跳过 TTS |
| TTS 触发 | `message.completed` 后全文合成 |
| 音频传输 | V1 HTTP 资产；Phase 5 SSE 事件（非默认 WebSocket） |
| 模块路径 | `apps/server/app/modules/audio/` |
| 桌面结构 | `services/` + `composables/` + `components/` |
| 数据存储 | PostgreSQL 元数据 + 本地音频文件 |
| 部署方式 | 本地部署 |

**最终目标：**

让语音成为陪伴者人格与情绪表达的一部分，而不是给文字回复简单增加一个朗读功能。

艺应拥有稳定的声音身份，并能根据自己的情绪与人格自然改变说话方式。

语音模块不得取代现有交流决策、人格和状态系统，而应成为这些内部机制对外表达的另一个通道。
