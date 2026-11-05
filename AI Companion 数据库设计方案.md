# AI Companion 数据库设计方案

**版本：V1.0**
**设计阶段：数据库结构设计完成，准备进入 ORM 实现**
**数据库：PostgreSQL + pgvector**
**后端：Python + FastAPI + SQLAlchemy 2.x**

------

# 一、设计目标与基本原则

## 1.1 数据库建设目标

AI Companion 并不是一个普通聊天应用。它需要具备独立人格、长期记忆、动态情绪、关系变化、主动交流和自主行为决策能力。

因此，数据库不仅需要保存用户与 AI 的对话，还需要支持：

1. AI 人格的长期稳定和版本演变。
2. 对话内容的完整保存与追溯。
3. 长期记忆的提取、归纳、修正和关联。
4. AI 情绪、关系和交流状态的持续变化。
5. AI 交流决策的记录和回溯。
6. 模型调用的统一管理和可观测性。
7. 后台任务的可靠调度、重试和幂等执行。
8. 未来多用户、多 Companion 和云端部署扩展。

## 1.2 核心设计原则

| 原则           | 具体要求                                |
| -------------- | --------------------------------------- |
| 长期连续性     | 用户、人格、记忆和关系数据能够长期保存  |
| 人格稳定性     | 人格定义与临时情绪状态分离              |
| 状态可追踪     | 当前状态与历史变化分别保存              |
| 决策可回溯     | 能够还原 AI 为什么选择某种交流行为      |
| 数据可修正     | 记忆和人格支持版本管理，不直接覆盖历史  |
| 任务可靠性     | 后台任务具备持久化、重试和幂等机制      |
| 数据隔离       | 不同用户、不同 Companion 的数据相互隔离 |
| 可扩展性       | 支持未来多模态、云端和实体设备          |
| 事实与认知分离 | 原始事实、AI 归纳认知、运行状态分别管理 |

## 1.3 数据库总体技术方案

- PostgreSQL：正式业务数据和关系数据。
- pgvector：记忆向量存储与语义检索。
- Redis：后台任务队列及运行时辅助能力。
- SQLAlchemy 2.x：Python ORM。
- Alembic：数据库结构迁移。
- Pydantic v2：数据结构和业务输入校验。

**PostgreSQL 是正式业务数据的唯一事实来源。** Redis 不保存正式记忆，也不作为业务数据的最终存储。

------

# 二、数据库总体结构

## 2.1 核心业务模块

第一版划分为七个数据库业务领域。

| 模块           | 职责                         | 核心实体数量 |
| -------------- | ---------------------------- | ------------ |
| Identity       | 用户和 AI 陪伴实例           | 2            |
| Conversation   | 会话和消息                   | 2            |
| Persona        | 人格主体和人格版本           | 2            |
| Memory         | 长期记忆及其关联数据         | 5            |
| State          | 当前状态和状态历史           | 2            |
| Dialogue       | 交流行为决策                 | 1            |
| Infrastructure | 模型配置、调用日志和后台任务 | 3            |
| **合计**       |                              | **17**       |

## 2.2 17 张核心表

### Identity

- `users`
- `companions`

### Conversation

- `conversations`
- `messages`

### Persona

- `persona_profiles`
- `persona_versions`

### Memory

- `memories`
- `memory_versions`
- `memory_sources`
- `memory_relations`
- `memory_embeddings`

### State

- `companion_states`
- `state_events`

### Dialogue

- `dialogue_decisions`

### Infrastructure

- `model_configs`
- `model_call_logs`
- `background_tasks`

## 2.3 整体实体关系

主要关系如下：

```
User
 └── Companion（一个用户可以拥有多个 Companion）
      ├── PersonaProfile（1:1）
      │    └── PersonaVersion（1:N）
      │
      ├── Conversation（1:N）
      │    └── Message（1:N）
      │
      ├── Memory（1:N）
      │    ├── MemoryVersion（1:N）
      │    ├── MemorySource（1:N）
      │    ├── MemoryRelation（自关联）
      │    └── MemoryEmbedding（通过 MemoryVersion 关联）
      │
      ├── CompanionState（1:1）
      │    └── StateEvent（1:N）
      │
      ├── DialogueDecision（1:N）
      │
      ├── ModelCallLog（1:N）
      │
      └── BackgroundTask（1:N）

ModelConfig
 └── ModelCallLog（1:N）
```

MemorySource 负责连接 Message 与 Memory，MemoryRelation 负责连接不同 Memory。

------

# 三、Identity 模块：用户与陪伴实例

## 3.1 设计目标

Identity 模块负责管理用户和 AI Companion 实例。

这里采用 User 与 Companion 分离的设计。

一个 User 可以拥有多个 Companion，每个 Companion 都具有独立的人格、记忆、状态和对话历史。

例如：

```
User A
 ├── Companion A：INFJ
 ├── Companion B：ENFP
 └── Companion C：INTJ
```

不同 Companion 之间不共享运行状态和记忆。

## 3.2 users 表

表名：`users`

建议字段：

| 字段         | 类型        | 约束 / 默认值         | 说明         |
| ------------ | ----------- | --------------------- | ------------ |
| id           | UUID        | PK                    | 用户 ID      |
| display_name | VARCHAR(64) | NOT NULL              | 用户显示名称 |
| timezone     | VARCHAR(64) | NOT NULL，默认 UTC    | 用户时区     |
| locale       | VARCHAR(16) | NOT NULL，默认 zh-CN  | 用户语言     |
| status       | VARCHAR(16) | NOT NULL，默认 active | 用户状态     |
| created_at   | TIMESTAMPTZ | NOT NULL              | 创建时间     |
| updated_at   | TIMESTAMPTZ | NOT NULL              | 更新时间     |

第一版不实现完整账号认证系统。用户表只承担业务身份和数据归属职责，未来增加云端认证时再扩展。

## 3.3 companions 表

表名：`companions`

建议字段：

| 字段          | 类型        | 约束 / 默认值         | 说明         |
| ------------- | ----------- | --------------------- | ------------ |
| id            | UUID        | PK                    | Companion ID |
| owner_user_id | UUID        | FK，NOT NULL          | 所属用户     |
| name          | VARCHAR(64) | NOT NULL              | 陪伴者名称   |
| description   | TEXT        | NULL                  | 简介         |
| status        | VARCHAR(16) | NOT NULL，默认 active | 实例状态     |
| is_default    | BOOLEAN     | NOT NULL，默认 FALSE  | 是否默认实例 |
| created_at    | TIMESTAMPTZ | NOT NULL              | 创建时间     |
| updated_at    | TIMESTAMPTZ | NOT NULL              | 更新时间     |
| archived_at   | TIMESTAMPTZ | NULL                  | 归档时间     |

状态：

- `active`
- `paused`
- `archived`

约束：

- `owner_user_id` 外键关联 `users.id`。
- 删除用户时不允许无意间级联删除全部业务数据。
- 每个用户最多一个默认 Companion，使用部分唯一索引保证。

```
CREATE UNIQUE INDEX uq_companion_default
ON companions (owner_user_id)
WHERE is_default = TRUE AND status = 'active';
```

------

# 四、Conversation 模块：会话与消息

## 4.1 设计目标

Conversation 负责一次连续交流的主体，Message 保存每一条原始消息。

必须保留原始对话，不因记忆提取、摘要或归纳而删除。

AI 主动发送的消息也使用 Message 保存。

## 4.2 conversations 表

核心字段：

| 字段                 | 类型         | 说明           |
| -------------------- | ------------ | -------------- |
| id                   | UUID         | 主键           |
| user_id              | UUID         | 所属用户       |
| companion_id         | UUID         | 所属 Companion |
| title                | VARCHAR(128) | 会话标题       |
| status               | VARCHAR(16)  | 会话状态       |
| next_sequence_number | BIGINT       | 下一个消息序号 |
| last_message_at      | TIMESTAMPTZ  | 最近消息时间   |
| created_at           | TIMESTAMPTZ  | 创建时间       |
| updated_at           | TIMESTAMPTZ  | 更新时间       |
| archived_at          | TIMESTAMPTZ  | 归档时间       |

关键约束：

- 用户与 Companion 的归属必须匹配。
- `next_sequence_number` 初始值为 1。
- 会话序号通过事务和行锁分配。
- 会话归档不等于删除消息。

建议增加复合唯一约束：

```
UNIQUE (user_id, companion_id, id)
```

并通过复合外键确保 Conversation 的 User 与 Companion 归属一致。

## 4.3 messages 表

核心字段：

| 字段              | 类型        | 说明           |
| ----------------- | ----------- | -------------- |
| id                | UUID        | 主键           |
| conversation_id   | UUID        | 所属会话       |
| sequence_number   | BIGINT      | 会话内消息序号 |
| client_message_id | UUID        | 客户端幂等 ID  |
| sender_type       | VARCHAR(16) | 发送者类型     |
| content_type      | VARCHAR(16) | 内容类型       |
| content           | TEXT        | 消息正文       |
| status            | VARCHAR(16) | 消息状态       |
| metadata          | JSONB       | 扩展元数据     |
| created_at        | TIMESTAMPTZ | 创建时间       |

发送者类型：

- `user`
- `companion`
- `system`

第一版以文本消息为主。虽然预留多模态扩展能力，但暂不开放尚未实现完整处理流程的附件类型。

### 消息顺序

使用：

```
UNIQUE (conversation_id, sequence_number)
```

并通过 Conversation 行锁分配序号。

### 消息幂等

客户端生成 `client_message_id`，后端建立部分唯一索引：

```
CREATE UNIQUE INDEX uq_message_client_id
ON messages (conversation_id, client_message_id)
WHERE client_message_id IS NOT NULL;
```

避免网络重试导致同一消息重复保存。

------

# 五、Persona 模块：人格主体与版本

## 5.1 设计目标

Persona 描述 AI 长期稳定的人格。

人格不能与当前情绪、关系状态混为一谈。

第一版采用 MBTI 作为核心人格底色，精选六种人格：

- INFJ
- INFP
- ENFP
- ENFJ
- INTJ
- INTP

初始等概率选择。

MBTI 是产品人格描述框架，不是严格的心理测量结论。

## 5.2 persona_profiles 表

保存人格主体信息和版本指针。

核心字段：

| 字段               | 类型        | 说明                 |
| ------------------ | ----------- | -------------------- |
| id                 | UUID        | 主键                 |
| companion_id       | UUID        | 所属 Companion，唯一 |
| initial_version_id | UUID        | 初始人格版本         |
| current_version_id | UUID        | 当前人格版本         |
| created_at         | TIMESTAMPTZ | 创建时间             |
| updated_at         | TIMESTAMPTZ | 更新时间             |

一个 Companion 对应一个 PersonaProfile。

## 5.3 persona_versions 表

保存完整人格快照。

核心字段：

| 字段                      | 类型        | 说明         |
| ------------------------- | ----------- | ------------ |
| id                        | UUID        | 主键         |
| persona_profile_id        | UUID        | 所属人格主体 |
| version_number            | INTEGER     | 版本号       |
| mbti_type                 | VARCHAR(4)  | MBTI 类型    |
| core_traits               | JSONB       | 核心人格特征 |
| behavior_traits           | JSONB       | 行为特征     |
| communication_preferences | JSONB       | 交流偏好     |
| change_reason             | TEXT        | 变化原因     |
| created_at                | TIMESTAMPTZ | 创建时间     |

人格版本不能直接覆盖历史。

初始人格保持稳定，细节人格允许在长期交互中逐渐变化。每次变化必须保留版本、时间和依据。

### 版本约束

- `UNIQUE (persona_profile_id, version_number)`
- 主体当前版本必须属于该主体。
- 使用复合唯一约束和复合外键保证版本归属。

------

# 六、Memory 模块：长期记忆系统

## 6.1 设计目标

Memory 是 AI 长期连续性的重要基础。

第一版采用四层记忆结构：

1. Conversation Log：原始对话记录。
2. Working Memory：短期工作记忆。
3. Semantic Memory：语义记忆与长期认知。
4. Episodic Memory：情景经历记忆。

原始对话由 Message 保存，其余记忆由 Memory 系统管理。

## 6.2 memories 表

保存记忆主体、分类、状态和质量评估。

| 字段               | 类型         | 约束 / 默认值  | 说明            |
| ------------------ | ------------ | -------------- | --------------- |
| id                 | UUID         | PK             | 记忆 ID         |
| companion_id       | UUID         | NOT NULL，FK   | 所属 Companion  |
| current_version_id | UUID         | FK             | 当前有效版本    |
| memory_type        | VARCHAR(16)  | NOT NULL       | 记忆层级        |
| memory_category    | VARCHAR(32)  | NOT NULL       | 记忆分类        |
| subject            | VARCHAR(128) | NULL           | 主题或对象      |
| status             | VARCHAR(16)  | 默认 candidate | 记忆状态        |
| importance         | SMALLINT     | 默认 50        | 重要性，0–100   |
| confidence         | NUMERIC(4,3) | 默认 0.500     | 可信度，0–1     |
| stability          | NUMERIC(4,3) | 默认 0.500     | 稳定性，0–1     |
| relevance          | NUMERIC(4,3) | 默认 0.500     | 当前相关性，0–1 |
| memory_origin      | VARCHAR(16)  | NOT NULL       | 形成来源        |
| is_inference       | BOOLEAN      | 默认 FALSE     | 是否推断        |
| valid_from         | TIMESTAMPTZ  | NULL           | 有效开始时间    |
| valid_until        | TIMESTAMPTZ  | NULL           | 有效结束时间    |
| last_accessed_at   | TIMESTAMPTZ  | NULL           | 最近访问时间    |
| access_count       | INTEGER      | 默认 0         | 访问次数        |
| created_at         | TIMESTAMPTZ  | NOT NULL       | 创建时间        |
| updated_at         | TIMESTAMPTZ  | NOT NULL       | 更新时间        |
| archived_at        | TIMESTAMPTZ  | NULL           | 归档时间        |

### memory_type

- `working`
- `semantic`
- `episodic`

### status

- `candidate`
- `pending`
- `active`
- `archived`
- `rejected`

### memory_origin

| 值               | 含义               |
| ---------------- | ------------------ |
| user_explicit    | 用户明确表达       |
| user_behavior    | 从用户长期行为观察 |
| ai_inference     | AI 归纳认知        |
| ai_interest      | AI 自主形成的兴趣  |
| system_generated | 系统整理产生       |

`memory_origin` 表示形成来源，`is_inference` 表示是否为推断，二者不是同一个概念。

AI 归纳认知必须保留形成依据，不能只保存结论。

### 质量评分

记忆重要性、时效性、重复程度、可信度、使用频率共同辅助记忆保留和检索。

初始评分公式：

```
S = 0.30I + 0.25T + 0.15R + 0.20C + 0.10F
```

各项归一化至 0–1。

评分不作为唯一删除标准。单次出现但极其重要的记忆不能因为重复次数低而被淘汰。

### 约束与索引

- importance 范围 0–100。
- confidence、stability、relevance 范围 0–1。
- access_count >= 0。
- valid_until 不早于 valid_from。
- `(companion_id, status)`
- `(companion_id, memory_type, status)`
- `(companion_id, memory_category)`
- `(companion_id, importance)`
- `(companion_id, updated_at)`

## 6.3 memory_versions 表

保存记忆正文和历史版本。

| 字段                | 类型         | 说明           |
| ------------------- | ------------ | -------------- |
| id                  | UUID         | 主键           |
| memory_id           | UUID         | 所属记忆       |
| version_number      | INTEGER      | 版本号         |
| content             | TEXT         | 记忆正文       |
| structured_content  | JSONB        | 结构化内容     |
| summary             | TEXT         | 简短摘要       |
| change_type         | VARCHAR(16)  | 变化类型       |
| change_reason       | TEXT         | 变化原因       |
| confidence_snapshot | NUMERIC(4,3) | 版本可信度快照 |
| created_at          | TIMESTAMPTZ  | 创建时间       |

`change_type`：

- `create`
- `supplement`
- `correct`
- `update`
- `merge`

新内容创建新版本，不直接覆盖历史。

使用复合唯一约束：

```
UNIQUE (memory_id, version_number)
```

并通过复合外键保证 Memory 当前版本属于自身。

## 6.4 memory_sources 表

保存记忆形成依据。

| 字段             | 类型         | 说明           |
| ---------------- | ------------ | -------------- |
| id               | UUID         | 主键           |
| memory_id        | UUID         | 当前记忆       |
| message_id       | UUID         | 来源消息，可空 |
| source_memory_id | UUID         | 来源记忆，可空 |
| source_type      | VARCHAR(16)  | 来源类型       |
| source_role      | VARCHAR(16)  | 来源作用       |
| relevance_score  | NUMERIC(4,3) | 相关程度       |
| created_at       | TIMESTAMPTZ  | 创建时间       |

`source_type`：

- `message`
- `memory`
- `system`

`source_role`：

- `evidence`
- `context`
- `correction`

来源规则：

- message 类型必须填写 message_id。
- memory 类型必须填写 source_memory_id。
- system 类型两个来源字段都为空。
- message_id 与 source_memory_id 必须且只能有一个非空，system 除外。

支持一条消息形成多条记忆，也支持多条消息共同形成一条记忆。

必须检查来源归属与 Companion 一致，并避免记忆来源形成循环依赖。

## 6.5 memory_relations 表

保存记忆之间的有向关系。

| 字段             | 类型         | 说明       |
| ---------------- | ------------ | ---------- |
| id               | UUID         | 主键       |
| source_memory_id | UUID         | 关系发起方 |
| target_memory_id | UUID         | 关系指向方 |
| relation_type    | VARCHAR(24)  | 关系类型   |
| strength         | NUMERIC(4,3) | 关联强度   |
| description      | TEXT         | 关系说明   |
| created_at       | TIMESTAMPTZ  | 创建时间   |
| updated_at       | TIMESTAMPTZ  | 更新时间   |

关系类型：

- `related_to`
- `supports`
- `contradicts`
- `supersedes`
- `caused_by`
- `part_of`

约束：

- 两端不能是同一条记忆。
- 两端必须属于同一 Companion。
- `UNIQUE (source_memory_id, target_memory_id, relation_type)`。
- strength 范围 0–1。

关系具有方向性。新记忆取代旧记忆时，新记忆指向旧记忆，使用 `supersedes`。

冲突关系不能直接导致记忆删除，应触发重新评估。

## 6.6 memory_embeddings 表

向量关联 MemoryVersion，而不是直接关联 Memory。

| 字段              | 类型        | 说明         |
| ----------------- | ----------- | ------------ |
| id                | UUID        | 主键         |
| memory_version_id | UUID        | 对应记忆版本 |
| embedding_model   | VARCHAR(64) | 向量模型     |
| embedding         | VECTOR(D)   | 向量数据     |
| content_hash      | VARCHAR(64) | 内容哈希     |
| status            | VARCHAR(16) | 生成状态     |
| created_at        | TIMESTAMPTZ | 创建时间     |

状态：

- `pending`
- `completed`
- `failed`

约束：

```
UNIQUE (memory_version_id, embedding_model)
```

向量维度 D 需要根据实际 Embedding 模型确定，不能在 DeepSeek 接口能力尚未核实前提前锁定。

向量生成失败不影响记忆保存，后台任务可以补齐。

第一版采用 PostgreSQL + pgvector，优先考虑 HNSW 索引，使用余弦距离作为初始检索方案。

------

# 七、State 模块：当前状态与变化历史

## 7.1 设计目标

State 管理 AI 当前的内部状态。

必须与 Persona 和 Memory 分离：

- Persona：AI 长期是什么性格。
- Memory：AI 记住了什么。
- State：AI 现在处于什么状态。

第一版分为四个维度：

1. Emotion：情绪。
2. Relationship：关系感受。
3. Interaction：交流状态。
4. Motivation：当前行为动机。

## 7.2 companion_states 表

每个 Companion 对应一条当前状态记录。

| 字段         | 类型        | 说明                 |
| ------------ | ----------- | -------------------- |
| id           | UUID        | 主键                 |
| companion_id | UUID        | 所属 Companion，唯一 |
| emotion      | JSONB       | 当前情绪             |
| relationship | JSONB       | 当前关系状态         |
| interaction  | JSONB       | 当前交流状态         |
| motivation   | JSONB       | 当前行为动机         |
| updated_at   | TIMESTAMPTZ | 更新时间             |
| version      | INTEGER     | 状态版本             |

### emotion 示例

```
{
  "primary": "calm",
  "secondary": [],
  "intensity": 0.5,
  "valence": 0.2,
  "arousal": 0.3,
  "cause_summary": "当前没有明显情绪波动",
  "updated_at": "2026-11-05T19:00:00+08:00"
}
```

### relationship 示例

```
{
  "closeness": 0.7,
  "trust": 0.8,
  "attachment": 0.6,
  "care": 0.9,
  "current_tension": 0.1,
  "summary": "彼此熟悉，交流较为自然"
}
```

这些数值属于 AI 内部状态变量，不作为用户可见的好感度等级。

### interaction 示例

```
{
  "mode": "available",
  "proactive_allowed": true,
  "waiting_for_user": false,
  "last_user_response_at": null,
  "last_companion_message_at": null,
  "consecutive_unanswered_messages": 0,
  "quiet_until": null
}
```

mode：

- `available`
- `waiting`
- `quiet`
- `paused`

主动交流权限是约束，不代表 AI 的情绪或意愿。

### motivation 示例

```
{
  "primary": "share",
  "secondary": ["connect"],
  "intensity": 0.6,
  "target": "user",
  "reason": "想分享一个最近关注的话题"
}
```

第一版动机：

- `connect`
- `share`
- `listen`
- `comfort`
- `understand`
- `play`
- `resolve_conflict`
- `rest`

State 保存持续性动机，Dialogue 保存本次行为的决策动机。

## 7.3 state_events 表

记录每次状态变化。

| 字段                 | 类型        | 说明           |
| -------------------- | ----------- | -------------- |
| id                   | UUID        | 主键           |
| companion_id         | UUID        | 所属 Companion |
| event_type           | VARCHAR(32) | 状态变化类型   |
| source_type          | VARCHAR(16) | 变化来源       |
| conversation_id      | UUID        | 关联会话，可空 |
| message_id           | UUID        | 触发消息，可空 |
| dialogue_decision_id | UUID        | 关联决策，可空 |
| version_before       | INTEGER     | 变化前版本     |
| version_after        | INTEGER     | 变化后版本     |
| changes              | JSONB       | 变化内容       |
| reason               | TEXT        | 变化原因       |
| created_at           | TIMESTAMPTZ | 变化时间       |

事件类型：

- `emotion_changed`
- `relationship_changed`
- `interaction_changed`
- `motivation_changed`
- `multiple_changed`
- `state_initialized`
- `state_recovered`

来源类型：

- `user_message`
- `companion_action`
- `dialogue_decision`
- `background_task`
- `system`

### 状态更新原则

- State 快照和 StateEvent 必须在同一事务中更新。
- StateEvent 采用追加写入。
- `version` 实现乐观锁。
- 同一 Companion 的状态更新由 State Service 统一协调。
- 状态 JSONB 通过 Pydantic Schema 校验。
- 临时情绪可以自然衰减，重要经历则进入 Memory。

建议唯一索引：

```
CREATE UNIQUE INDEX uq_state_event_version
ON state_events (companion_id, version_after)
WHERE version_after IS NOT NULL;
```

------

# 八、Dialogue 模块：交流决策

## 8.1 设计目标

Dialogue 是 AI 的行为决策中枢。

Persona 提供人格，Memory 提供认知和经历，State 提供当前状态，Dialogue 综合这些信息决定 AI 接下来做什么。

第一版采用 Python + LLM 混合决策。

LLM 负责理解、权衡和提出决策；Python 负责校验、约束和最终执行。

## 8.2 dialogue_decisions 表

| 字段               | 类型         | 说明            |
| ------------------ | ------------ | --------------- |
| id                 | UUID         | 主键            |
| companion_id       | UUID         | 所属 Companion  |
| conversation_id    | UUID         | 所属会话，可空  |
| trigger_message_id | UUID         | 触发消息，可空  |
| result_message_id  | UUID         | 结果消息，可空  |
| trigger_type       | VARCHAR(16)  | 决策触发类型    |
| primary_action     | VARCHAR(32)  | 主要行为        |
| secondary_actions  | JSONB        | 辅助行为        |
| motivation         | JSONB        | 本次行为动机    |
| topic              | JSONB        | 交流话题        |
| model_proposal     | JSONB        | LLM 原始建议    |
| validation_result  | JSONB        | Python 校验结果 |
| confidence         | NUMERIC(4,3) | 决策置信度      |
| reasoning_summary  | TEXT         | 决策依据摘要    |
| status             | VARCHAR(16)  | 决策执行状态    |
| created_at         | TIMESTAMPTZ  | 决策时间        |
| completed_at       | TIMESTAMPTZ  | 完成时间        |

### trigger_type

- `user_message`
- `proactive`
- `system_event`
- `background`

### primary_action

- `respond`
- `ask`
- `share`
- `comfort`
- `analyze`
- `challenge`
- `express_emotion`
- `change_topic`
- `end_conversation`
- `quiet`

Quiet 是合法决策，即使没有生成消息，也必须保留决策记录。

### status

- `pending`
- `approved`
- `executing`
- `completed`
- `rejected`
- `failed`
- `cancelled`

### Decision / Realization 分离

```
接收消息或主动触发
       ↓
加载 Persona / Memory / State
       ↓
LLM 结构化决策建议
       ↓
Pydantic 校验
       ↓
Python 行为约束校验
       ↓
确定最终行为
       ↓
保存 DialogueDecision
       ↓
判断是否需要生成消息
       ↓
LLM 自然语言实现
       ↓
SSE 输出
       ↓
保存 Message
```

自然语言生成阶段不能擅自改变已经确定的行为决策。

索引：

- `(companion_id, created_at)`
- `(conversation_id, created_at)`
- `(status, created_at)`
- `(trigger_message_id)`
- `UNIQUE (result_message_id)`，允许 NULL。

------

# 九、Infrastructure 模块：模型、日志与任务

## 9.1 model_configs 表

动态管理不同任务使用的模型配置。

| 字段       | 类型         | 说明     |
| ---------- | ------------ | -------- |
| id         | UUID         | 主键     |
| config_key | VARCHAR(64)  | 配置标识 |
| provider   | VARCHAR(32)  | 供应商   |
| model_name | VARCHAR(128) | 模型名称 |
| task_type  | VARCHAR(32)  | 任务类型 |
| parameters | JSONB        | 模型参数 |
| is_enabled | BOOLEAN      | 是否启用 |
| is_default | BOOLEAN      | 是否默认 |
| version    | INTEGER      | 配置版本 |
| created_at | TIMESTAMPTZ  | 创建时间 |
| updated_at | TIMESTAMPTZ  | 更新时间 |

第一版唯一模型供应商为 DeepSeek。

任务类型：

- `conversation`
- `decision`
- `memory`
- `embedding`

每个任务类型最多有一个启用的默认配置：

```
CREATE UNIQUE INDEX uq_model_config_default
ON model_configs (task_type)
WHERE is_enabled = TRUE AND is_default = TRUE;
```

API Key 和数据库密码不保存于该表，统一通过环境变量或密钥管理方式配置。

## 9.2 model_call_logs 表

记录所有模型调用。

| 字段                 | 类型         | 说明                 |
| -------------------- | ------------ | -------------------- |
| id                   | UUID         | 主键                 |
| companion_id         | UUID         | 所属 Companion，可空 |
| conversation_id      | UUID         | 所属会话，可空       |
| dialogue_decision_id | UUID         | 关联决策，可空       |
| background_task_id   | UUID         | 关联任务，可空       |
| config_id            | UUID         | 模型配置，可空       |
| trace_id             | UUID         | 全链路追踪 ID        |
| task_type            | VARCHAR(32)  | 调用任务             |
| provider             | VARCHAR(32)  | 供应商               |
| model_name           | VARCHAR(128) | 实际模型             |
| status               | VARCHAR(16)  | 调用状态             |
| latency_ms           | INTEGER      | 耗时                 |
| input_tokens         | INTEGER      | 输入 Token           |
| output_tokens        | INTEGER      | 输出 Token           |
| error_code           | VARCHAR(64)  | 错误代码             |
| error_message        | TEXT         | 错误信息             |
| created_at           | TIMESTAMPTZ  | 调用时间             |
| completed_at         | TIMESTAMPTZ  | 完成时间             |

调用状态：

- `success`
- `failed`
- `timeout`
- `cancelled`

默认不保存完整 Prompt 和完整模型输出。

支持脱敏、保留期限和详细日志开关。

索引：

- `(trace_id)`
- `(companion_id, created_at)`
- `(task_type, created_at)`
- `(status, created_at)`
- `(dialogue_decision_id)`

## 9.3 background_tasks 表

Redis + ARQ 负责后台任务执行，PostgreSQL 保存正式任务记录。

| 字段          | 类型         | 说明                 |
| ------------- | ------------ | -------------------- |
| id            | UUID         | 主键                 |
| companion_id  | UUID         | 所属 Companion，可空 |
| task_type     | VARCHAR(32)  | 任务类型             |
| task_key      | VARCHAR(128) | 幂等标识             |
| queue_name    | VARCHAR(32)  | 队列名称             |
| status        | VARCHAR(16)  | 任务状态             |
| payload       | JSONB        | 输入参数             |
| result        | JSONB        | 结果摘要             |
| error_message | TEXT         | 最后一次错误         |
| retry_count   | INTEGER      | 已重试次数           |
| max_retries   | INTEGER      | 最大重试次数         |
| scheduled_at  | TIMESTAMPTZ  | 计划执行时间         |
| dispatched_at | TIMESTAMPTZ  | 成功投递时间         |
| locked_at     | TIMESTAMPTZ  | 锁定时间             |
| worker_id     | VARCHAR(128) | Worker 标识          |
| started_at    | TIMESTAMPTZ  | 开始执行时间         |
| completed_at  | TIMESTAMPTZ  | 完成时间             |
| created_at    | TIMESTAMPTZ  | 创建时间             |
| updated_at    | TIMESTAMPTZ  | 更新时间             |

任务类型：

- `memory_extract`
- `memory_evaluate`
- `memory_embedding`
- `memory_relation`
- `memory_summarize`
- `state_maintenance`
- `proactive_check`

状态：

- `pending`
- `queued`
- `running`
- `retrying`
- `completed`
- `failed`
- `cancelled`

约束：

```
UNIQUE (task_key)
```

索引：

- `(status, scheduled_at)`
- `(companion_id, created_at)`
- `(task_type, status)`

任务必须具备失败重试、幂等、失败追踪和最终状态管理。

------

# 十、数据库一致性与可靠性设计

## 10.1 版本归属一致性

PersonaProfile 与 PersonaVersion、Memory 与 MemoryVersion 均采用双向关联。

不能只使用普通外键，否则可能出现主体引用其他主体版本的问题。

使用复合唯一约束：

```
UNIQUE (persona_profile_id, id)
UNIQUE (memory_id, id)
```

当前版本使用复合外键确保版本归属正确。

循环引用的外键使用：

```
DEFERRABLE INITIALLY DEFERRED
```

在同一事务中创建主体和首个版本。

## 10.2 多用户数据隔离

所有 Companion 关联数据必须保证属于正确的用户和 Companion。

Conversation 必须同时关联 User 与 Companion，并验证两者归属关系。

Memory、Message、State、Decision、Task 等数据的跨表关联也需要校验 Companion 归属。

应用层统一实施访问范围校验。未来云端部署时可以增加 PostgreSQL RLS。

## 10.3 消息并发与幂等

- Conversation 行锁分配消息序号。
- 使用 `next_sequence_number`，避免每次查询最大序号。
- 使用 `client_message_id` 防止客户端重复提交。
- 同一会话序号唯一。

## 10.4 状态并发控制

- State 使用版本号乐观锁。
- 同一状态版本只能对应一条状态变化事件。
- 快照与事件同事务更新。
- 并发冲突时重新读取和计算，不允许直接覆盖。

## 10.5 PostgreSQL 与 Redis 任务一致性

BackgroundTask 同时承担持久化任务记录和 Outbox 职责，不额外增加 Outbox 表。

消息保存与任务创建必须处于同一 PostgreSQL 事务。

流程：

```
接收消息
  ↓
开启 PostgreSQL 事务
  ↓
保存 Message
  ↓
创建 BackgroundTask
  ↓
提交事务
  ↓
任务分发器扫描待投递记录
  ↓
投递 Redis / ARQ
  ↓
更新任务状态
  ↓
Worker 执行任务
  ↓
更新最终状态
```

Redis 投递与 PostgreSQL 状态更新之间仍可能发生重复投递，因此必须保证业务任务幂等。

采用至少一次投递，不追求跨两个系统的原子提交。

## 10.6 删除与归档策略

| 操作              | 处理方式                             |
| ----------------- | ------------------------------------ |
| 暂停 Companion    | 更新状态，保留数据                   |
| 归档 Companion    | 设置归档时间，保留数据               |
| 归档 Conversation | 设置会话归档状态                     |
| 删除 Memory       | 清理版本、来源、关系、向量           |
| 删除 Message      | 清理来源关联，重新评估受影响记忆     |
| 删除 User         | 通过统一数据清理流程处理全部关联数据 |

不依赖无差别的数据库级联删除。

删除一条 Message 时，如果某条 Memory 还有其他有效来源，不能直接删除整条 Memory。

------

# 十一、SQLAlchemy 2.x 实现规范

## 11.1 公共目录

```
apps/server/app/shared/database/
├── base.py
├── session.py
├── mixins.py
├── types.py
└── naming.py
```

## 11.2 ORM 规范

- 使用 SQLAlchemy 2.x Declarative Mapping。
- 使用 `Mapped[T]` 和 `mapped_column()`。
- UUID 统一使用 Python `uuid4`。
- 时间统一使用 timezone-aware datetime。
- PostgreSQL 使用 TIMESTAMPTZ。
- JSONB 必须配合 Pydantic Schema。
- 向量使用 pgvector 对应类型。
- 统一命名约定。

## 11.3 Enum 规范

固定状态和分类在 Python 中使用 Enum。

数据库采用 VARCHAR + CHECK，而不是第一版大量使用 PostgreSQL 原生 ENUM。

## 11.4 Session 与事务

使用 SQLAlchemy Async Engine 和 AsyncSession。

每个 HTTP 请求、每个后台任务独立 Session。

Repository：

- 只负责查询和持久化。
- 不自行 commit。
- 不自行开启跨业务事务。

Service：

- 负责业务规则。
- 负责事务边界。
- 协调多个 Repository。
- 统一提交和回滚。

## 11.5 模块访问规范

业务模块只能通过其他模块提供的 Service 接口协作，不直接访问其他模块 Repository。

例如：

```
Dialogue Service
 ├── Persona Service
 ├── Memory Service
 ├── State Service
 └── Model Adapter
```

------

# 十二、Alembic 迁移与初始化

## 12.1 数据库迁移

Alembic 负责数据库结构创建和变更。

建议顺序：

1. 创建 pgvector 扩展。
2. Identity。
3. Conversation。
4. Persona。
5. Memory。
6. State。
7. Dialogue。
8. Infrastructure。
9. 补充复合外键、索引和 CHECK 约束。
10. 执行数据库完整性测试。

对于双向版本引用，先创建主体表和版本表，再单独添加复合外键。

## 12.2 初始化数据

独立初始化脚本负责：

- 六种人格模板。
- 默认模型路由。
- 默认系统配置。
- 初始 Companion 所需的默认状态。

初始化脚本必须幂等，重复执行不能重复创建数据。

Alembic 只负责结构迁移，不负责运行时自动改表。

------

# 十三、最终数据库目录与开发顺序

## 13.1 后端工程目录

```
apps/server/
├── app/
│   ├── modules/
│   │   ├── persona/
│   │   ├── memory/
│   │   ├── dialogue/
│   │   ├── state/
│   │   └── model_adapter/
│   │
│   ├── shared/
│   │   ├── database/
│   │   ├── redis/
│   │   ├── events/
│   │   ├── exceptions/
│   │   └── utils/
│   │
│   ├── config/
│   └── main.py
│
├── workers/
├── tests/
├── alembic/
├── alembic.ini
├── pyproject.toml
└── .env.example
```

## 13.2 数据库开发顺序

建议按以下顺序实现：

1. 公共数据库基础设施。
2. Identity ORM。
3. Conversation ORM。
4. Persona ORM。
5. Memory ORM。
6. State ORM。
7. Dialogue ORM。
8. Infrastructure ORM。
9. Alembic 初始迁移。
10. PostgreSQL 实际迁移与完整性测试。

## 13.3 第一阶段验收标准

数据库开发不能只以 ORM 文件创建完成为标准。

必须通过以下测试：

- 能够创建 User 和多个 Companion。
- Companion 的人格和状态能够独立初始化。
- 能够创建 Conversation 并按顺序保存 Message。
- 重复提交消息不会生成重复记录。
- 能够创建人格版本并正确切换当前版本。
- 能够创建四层记忆中的正式记忆类型。
- 能够关联多个记忆来源和记忆关系。
- 能够保存 MemoryVersion 和对应 Embedding。
- 能够更新 State 并完整记录 StateEvent。
- 能够保存 DialogueDecision，包括 Quiet 决策。
- 能够按任务类型选择默认模型配置。
- 能够记录模型调用日志。
- 后台任务在 Redis 暂时不可用时不会丢失。
- 重复投递后台任务不会造成重复业务结果。
- 不同用户的数据无法通过跨 Companion 查询访问。
- Alembic 能够从空数据库完整创建结构。

------

# 十四、当前已确定与待实施核实事项

## 14.1 已确定的架构决策

| 项目       | 决策                            |
| ---------- | ------------------------------- |
| 数据库     | PostgreSQL + pgvector           |
| ORM        | SQLAlchemy 2.x                  |
| 数据校验   | Pydantic v2                     |
| 迁移       | Alembic                         |
| Session    | AsyncSession                    |
| 后台任务   | Redis + ARQ                     |
| 数据访问   | Repository + Service            |
| 业务架构   | 模块化单体                      |
| 记忆结构   | 四层记忆                        |
| 人格结构   | PersonaProfile + PersonaVersion |
| 状态结构   | 当前快照 + 历史事件             |
| 决策结构   | Decision / Realization 分离     |
| 任务可靠性 | BackgroundTask + Outbox 机制    |
| 核心实体   | 17 张表                         |

## 14.2 实施前需要核实的事项

以下内容不是数据库架构悬而未决，而是实施时必须根据实际技术条件确认：

1. DeepSeek 官方 Embedding 接口是否满足需求。
2. 最终 Embedding 模型及向量维度。
3. DeepSeek 实际模型名称、结构化输出和流式接口能力。
4. pgvector 与 PostgreSQL 目标版本的兼容性。
5. HNSW 索引的具体参数和实际检索效果。

如果实际接口能力不符合预期，再调整对应实现，不提前假设模型具备尚未核实的能力。

------

# 十五、最终结论

AI Companion 第一版数据库采用 **PostgreSQL + pgvector，17 张核心业务表，模块化组织，统一由 SQLAlchemy 2.x 和 Alembic 管理**。

这套结构覆盖了第一版产品需要的完整数据生命周期：

```
用户身份
   ↓
陪伴实例
   ├── 人格及人格演变
   ├── 对话与消息
   ├── 长期记忆及认知关系
   ├── 情绪与关系状态
   ├── 交流行为决策
   └── 模型调用与后台任务
```

设计的核心不是单纯存储聊天记录，而是让 AI 能够：

- 保留过去的经历。
- 形成并修正自己的认知。
- 维持相对稳定的人格。
- 记录自身状态的变化。
- 根据人格、记忆和状态决定如何交流。
- 追溯每次重要行为的决策依据。
- 在长期运行中保持数据可靠性。

**数据库逻辑设计第一轮完成。下一阶段进入公共数据库基础设施和 ORM 实现，先从 Identity 与 Conversation 开始。**