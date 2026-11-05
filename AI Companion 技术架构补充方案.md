# AI Companion 技术架构补充方案

**版本：V1.0**  
**主题：记忆检索机制、Embedding 能力与 SSE 流式通信**

## 一、设计背景

当前系统在进入实际开发阶段后发现三个架构缺口：

1. 候选记忆无法参与回复，导致长期记忆不能有效影响 AI 的交流行为。
2. DeepSeek 没有可用的官方 Embedding 接口，导致向量检索缺乏实际实现方案。
3. SSE 只有技术选型，没有明确的事件协议，前后端无法形成稳定的流式通信契约。

本次设计补充三个方面的工程规范，使系统从架构设计进入可实施状态。

---

# 二、Memory Engine：记忆检索资格与长期记忆晋升分离

## 2.1 核心问题

原设计中，记忆生命周期包含：

- candidate
- pending
- active
- archived
- rejected

但没有明确规定候选记忆能否参与对话上下文。

如果只有 active 记忆允许参与检索，就会导致新提取的信息无法及时影响当前或后续回复。

同时，记忆长期价值评分公式只是辅助评估工具，没有规定升级阈值，不应该人为补充未经验证的固定阈值。

## 2.2 核心设计决议

**记忆是否可以参与当前回复，与记忆是否可以晋升为正式长期记忆，是两个独立判断。**

保留原有记忆生命周期，不增加或修改原有状态定义。

新增独立的记忆检索资格机制。

| 记忆状态 | 正常对话检索资格 | 使用约束 |
|---|---|---|
| candidate | 有条件允许 | 来源可靠、内容有效且与当前话题高度相关时允许 |
| pending | 允许 | 可以参与上下文，必须保留不确定性 |
| active | 允许 | 正常参与检索 |
| archived | 默认禁止 | 仅在历史回顾或明确查询时使用 |
| rejected | 禁止 | 不参与正常检索 |

检索资格不改变记忆生命周期状态。

候选记忆参与回复，不意味着它已经成为正式记忆。

## 2.3 记忆评分机制

保留原有长期记忆评分公式：

S = 0.30I + 0.25T + 0.15R + 0.20C + 0.10F

该评分只用于辅助判断长期保存价值，不直接决定当前对话能否使用。

新增两个独立概念：

**promotion_score**

用于评估记忆是否适合晋升为正式长期记忆。

**retrieval_score**

用于评估记忆与当前对话的匹配程度。

retrieval_score 综合考虑：

- 当前话题相关性。
- 记忆置信度。
- 来源可靠性。
- 时间有效性。
- 当前记忆状态。
- 记忆重要性。

检索过程必须先进行资格校验，再进行相关性排序。

不得仅根据一个综合分数决定记忆是否允许使用。

## 2.4 记忆上下文组装

Dialogue Engine 获取记忆时，必须通过 Memory Engine 的公开检索服务。

检索流程：

1. 获取当前对话上下文。
2. 根据当前话题检索候选、待评估和正式记忆。
3. 过滤无效、过期、被拒绝的记忆。
4. 对推断性记忆标注推断属性和置信度。
5. 根据相关性排序。
6. 将合适的记忆放入决策上下文。
7. 由 LLM 根据记忆证据决定是否使用。

上下文中的记忆必须保留必要的元信息：

- memory_id
- memory_type
- memory_status
- content
- confidence
- is_inference
- source_summary
- valid_from
- valid_until

LLM 不得将推断性记忆伪装成用户明确表达的事实。

## 2.5 当前消息的即时事实

新增明确规则：

**当前用户消息中的即时事实不需要等待后台记忆提取，就必须能够参与当前回合的上下文组装。**

例如，用户刚刚告诉 AI 自己正在准备某个项目，即使 Memory Worker 尚未完成提取，该信息也应当进入当前对话上下文。

即时事实与长期记忆分开管理，不必为了让当前回复获得上下文而强行提前创建正式记忆。

## 2.6 当前回合与后台记忆处理时序

推荐流程：

用户消息
→ 保存原始消息
→ 组装近期对话和即时事实
→ 检索已有记忆
→ Dialogue 决策
→ 生成回复
→ 后台提取和评估记忆
→ 创建或更新记忆
→ 生成 Embedding
→ 更新记忆关系

后台任务失败不能影响已经完成的正常对话。

---

# 三、Model Adapter：独立 Embedding Provider

## 3.1 核心问题

第一版模型供应商为 DeepSeek，但目前没有可用的官方 Embedding API 实现方案。

因此：

- 不能将 embedding_model 默认配置为 DeepSeek。
- 不能假设 DeepSeek 支持 Embedding。
- 在 Embedding 模型未确定前，不能锁定向量维度。
- 不能因为 Embedding 不可用而阻断整个记忆系统。

## 3.2 核心设计决议

第一版采用：

**本地 BGE-M3 作为默认 Embedding 模型。**

模型信息：

| 配置 | 默认值 |
|---|---|
| Provider | local |
| Model | BAAI/bge-m3 |
| Dimensions | 1024 |
| Device | auto |
| Task Type | embedding |

BGE-M3 支持多语言，适合中文语义检索，支持本地部署，不依赖额外的云端 Embedding API。

本地部署会占用额外计算资源，实际性能需要在开发环境中测试。

## 3.3 Model Adapter 调整

Embedding 必须作为独立 Provider 管理，不与对话模型绑定。

原有模型任务路由保留：

- conversation_model
- decision_model
- memory_model
- embedding_model

其中 embedding_model 默认指向本地 BGE-M3。

Model Adapter 负责统一：

- Embedding 模型选择。
- 文本向量生成。
- 向量维度校验。
- 模型版本管理。
- 异常处理。
- 超时与重试。
- 任务调用日志。

Memory Engine 不得直接依赖 BGE-M3 的 SDK 或内部实现。

未来更换 Embedding 模型时，只修改 Provider 和配置，不改变 Memory Engine 的业务接口。

## 3.4 数据库调整

`memory_embeddings` 表的向量维度正式确定为：

VECTOR(1024)

继续保留字段：

- id
- memory_version_id
- embedding_model
- content_hash
- embedding
- status
- created_at

其中：

- embedding 对应具体 MemoryVersion。
- content_hash 用于识别内容变化。
- embedding_model 用于识别向量来源。
- 不同模型生成的向量不能直接混合比较。

更换模型时必须重新生成对应版本的向量，不得直接混用不同模型的向量空间。

## 3.5 混合检索

向量检索不能成为唯一的记忆检索方式。

第一版使用混合检索：

| 检索方式 | 主要作用 |
|---|---|
| 关键词检索 | 精确匹配项目名、人名、技术名词 |
| 时间检索 | 检索近期事件和时间相关记忆 |
| 关系检索 | 沿记忆关联关系扩展检索 |
| 向量检索 | 发现语义相近但表达不同的记忆 |

即使 Embedding 服务不可用，关键词、时间和关系检索仍然可以运行。

Embedding 失败时：

- 原始记忆正常保存。
- Embedding 状态标记为 failed。
- 后台任务可以重试。
- 不影响记忆的其他检索方式。

---

# 四、Dialogue/API：统一 SSE 事件协议

## 4.1 核心问题

原架构确定使用 SSE，但没有定义业务事件类型、数据结构和结束语义。

目前回合接口一次返回完整回复，不满足逐段输出需求。

需要将模型供应商的流式协议与项目自身的业务通信协议分离。

## 4.2 核心设计决议

采用：

**POST + fetch + ReadableStream + SSE**

不直接向前端暴露 DeepSeek 原始流式响应。

后端将模型输出转换为项目统一的 SSE 事件协议。

## 4.3 事件类型

第一版定义七种业务事件：

| Event | 含义 |
|---|---|
| turn.started | 一次交流开始 |
| message.started | AI 开始生成一条消息 |
| message.delta | 收到一段文本增量 |
| message.completed | AI 消息生成完成 |
| turn.completed | 整个交流流程完成 |
| turn.failed | 整个交流流程失败 |
| turn.cancelled | 用户取消本次交流 |

连接保活使用 SSE 注释行，不作为业务事件。

## 4.4 事件数据结构

所有业务事件统一使用 JSON 作为 data 内容。

### turn.started

```json
{
  "turn_id": "uuid",
  "conversation_id": "uuid",
  "sequence": 0
}
```

### message.started

```json
{
  "turn_id": "uuid",
  "message_id": "uuid",
  "role": "companion",
  "sequence": 1
}
```

### message.delta

```json
{
  "turn_id": "uuid",
  "message_id": "uuid",
  "delta": "你好，",
  "index": 0,
  "sequence": 2
}
```

### message.completed

```json
{
  "turn_id": "uuid",
  "message_id": "uuid",
  "finish_reason": "stop",
  "usage": {
    "input_tokens": 100,
    "output_tokens": 50
  },
  "sequence": 3
}
```

### turn.completed

```json
{
  "turn_id": "uuid",
  "outcome": "replied",
  "sequence": 4
}
```

### turn.failed

```json
{
  "turn_id": "uuid",
  "error": {
    "code": "MODEL_REQUEST_FAILED",
    "message": "模型服务暂时不可用",
    "retryable": true
  },
  "sequence": 4
}
```

### turn.cancelled

```json
{
  "turn_id": "uuid",
  "sequence": 4
}
```

所有事件必须包含 turn_id 和递增 sequence。

存在消息时，消息相关事件还必须包含 message_id。

## 4.5 错误码

第一版统一维护以下错误码：

- MODEL_REQUEST_FAILED
- MODEL_TIMEOUT
- MODEL_OUTPUT_INVALID
- DECISION_FAILED
- CONTEXT_BUILD_FAILED
- INTERNAL_SERVER_ERROR

前端根据错误码决定展示方式，不依赖模型供应商的原始错误信息。

模型生成中途失败时：

- 不得发送 message.completed 假装成功。
- 必须发送 turn.failed。
- 根据实际持久化情况处理已生成的部分内容。
- 必须保留错误日志和 trace_id。

## 4.6 Quiet 决策

Quiet 是合法决策，不需要生成空消息。

事件流程：

turn.started
→ turn.completed

结束事件：

```json
{
  "turn_id": "uuid",
  "outcome": "quiet"
}
```

前端收到 outcome=quiet 后结束当前加载状态，不显示空消息。

## 4.7 SSE 消息持久化

流式生成和消息数据库状态必须保持一致。

推荐流程：

1. 开始生成时创建消息记录，状态为 generating。
2. 通过 message.delta 逐段向前端发送文本。
3. 生成成功后保存完整消息。
4. 将消息状态更新为 completed。
5. 发送 message.completed。
6. 发送 turn.completed。

如果生成失败或用户取消：

- 根据已生成内容和业务规则保存部分结果或标记中断。
- 不得将不完整消息标记为正常完成。
- 前端根据消息 ID 更新已有消息，不重复创建消息。

## 4.8 事件顺序与断线处理

每个事件增加递增 sequence，并使用 SSE 的 id 字段提供事件标识。

第一版必须保证事件顺序和前端重复处理保护。

暂不强制实现断线续传，但协议应预留基于事件 ID 恢复的扩展能力。

---

# 五、前端通信调整

前端使用：

- fetch
- ReadableStream
- AbortController

不使用原生 EventSource 直接发送本次 JSON 请求。

原因是本项目需要通过 POST 发送消息内容、conversation_id、client_message_id 等参数，并需要控制取消操作。

前端必须实现：

1. 发起对话请求。
2. 解析 SSE 事件。
3. 根据 event 类型分发处理。
4. 根据 message_id 更新消息内容。
5. 根据 delta 增量更新界面。
6. 正确处理 completed、failed、cancelled。
7. 用户主动停止生成。
8. 防止重复事件导致重复显示。
9. Quiet 结束时清理加载状态。

后端负责生成统一事件，前端不得依赖 DeepSeek 原始响应格式。

---

# 六、实施顺序

按照依赖关系，建议按以下顺序实施：

| 顺序 | 开发任务 | 验收目标 |
|---|---|---|
| 1 | 调整 Memory 检索资格 | candidate/pending 可以有条件参与回复 |
| 2 | 调整上下文组装 | 即时事实和已有记忆都能进入决策上下文 |
| 3 | 接入 BGE-M3 | 本地生成 1024 维向量 |
| 4 | 实现混合检索 | Embedding 不可用时仍可检索 |
| 5 | 定义 SSE Pydantic Schema | 前后端事件契约统一 |
| 6 | 改造 FastAPI 流式接口 | 后端逐段输出 |
| 7 | 改造 Vue 流式消费 | 前端逐段展示并支持取消 |
| 8 | 完整链路测试 | 验证正常、失败、Quiet 和取消场景 |

---

# 七、Cursor 开发约束补充

以下规则需要同步加入 `.cursor/rules/` 对应专项规则。

## Memory Engine

1. 记忆长期晋升资格与对话检索资格必须分开判断。
2. candidate 和 pending 可以在满足检索条件时参与回复。
3. 检索资格不得直接改变记忆生命周期状态。
4. 当前消息中的即时事实必须可以参与当前回合上下文。
5. 记忆推断必须保留来源和置信度。
6. 不得擅自设置长期记忆晋升固定阈值。
7. Embedding 不可用不能阻断其他记忆检索方式。

## Model Adapter

1. Embedding Provider 必须独立于对话模型 Provider。
2. 第一版默认使用本地 BGE-M3。
3. 向量维度固定为 1024。
4. Memory Engine 不得直接调用 Embedding SDK。
5. 不同 Embedding 模型的向量不得混合比较。
6. 更换模型时必须考虑向量重新生成。
7. Embedding 失败不得导致记忆保存失败。

## SSE

1. 前后端必须遵守统一 SSE 业务事件协议。
2. 不得直接向前端暴露供应商原始流式响应。
3. 使用 POST + fetch + ReadableStream。
4. 必须支持正常完成、失败、取消和 Quiet。
5. 每个事件必须具有 turn_id 和递增 sequence。
6. 消息必须通过 message_id 保持前后端一致。
7. 不得将未完成消息标记为正常完成。
8. SSE 事件必须有对应 Pydantic Schema。
9. 前端不得依赖模型供应商的原始错误格式。

---

# 八、数据库与架构影响

本次调整涉及：

**Memory**
- 明确 candidate/pending 的检索资格。
- 保留现有记忆状态定义。
- 增加检索评分及资格判断逻辑，不强制增加新的记忆生命周期状态。

**Embedding**
- memory_embeddings 使用 VECTOR(1024)。
- embedding_model 明确标识模型来源。
- 支持失败重试和模型更换后的向量重建。

**Conversation**
- messages 增加或明确生成中、完成、中断、失败等状态。
- 具体状态值应与现有 Message Schema 统一。
- SSE 事件 ID 和消息 ID 保持对应关系。

**Dialogue**
- Quiet 决策通过 turn.completed 的 outcome 表达。
- 失败和取消具有明确结束语义。

---

# 九、最终设计原则

本次补充遵循三个原则：

1. **记忆不必等到成为长期正式记忆，才能影响当前交流。**
2. **Embedding 是记忆检索的增强能力，不是记忆系统运行的前置条件。**
3. **SSE 是前后端业务通信协议，不是模型供应商流式接口的简单转发。**

所有实现必须遵守上述设计，不得为了快速跑通功能而破坏这些边界。