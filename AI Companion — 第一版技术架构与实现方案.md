# AI Companion — 第一版技术架构与实现方案

**文档版本：V1.0**
**确定日期：2026-11-05**
**项目阶段：技术选型与架构设计**
**适用范围：第一版本地桌面端 AI 陪伴系统**

------

# 一、项目技术目标

AI Companion 的最终产品形态是一个具有独立人格、长期记忆、主动交流和持续关系演进能力的实体 AI 陪伴设备。

第一版不直接开发硬件，而是优先完成 AI 核心系统，通过桌面端进行使用、调试和验证。

第一版技术目标：

1. 建立完整的 AI Companion 核心运行架构。
2. 实现 Persona、Memory、Dialogue、State 四个核心业务模块。
3. 实现统一的 LLM 模型接入层。
4. 实现长期记忆的提取、归纳、存储和检索。
5. 实现基于人格、记忆和状态的动态交流决策。
6. 实现 AI 主动交流及自然语言生成。
7. 提供桌面端调试客户端，能够观察和管理 AI 内部状态。
8. 为未来接入实体硬件和云端部署保留扩展能力。

核心设计原则：

- Python 业务逻辑与 LLM 认知能力相结合。
- 业务模块保持独立，通过明确接口协作。
- PostgreSQL 作为正式业务数据来源。
- 模型调用统一通过 Model Adapter。
- 在线对话和后台记忆处理解耦。
- 重要决策结构化，最终执行权由 Python 控制。
- 第一版优先验证产品机制，不进行过度工程化。

# 二、整体技术架构

## 2.1 技术架构选型

采用：

**Electron + Vue 3 + TypeScript + Python FastAPI + PostgreSQL + pgvector + Redis + ARQ + DeepSeek**

整体采用前后端分离的 Monorepo 工程结构。

## 2.2 架构组成

### 桌面客户端

- Electron：桌面应用容器。
- Vue 3：界面开发。
- TypeScript：前端类型系统。
- Vite：前端开发与构建。
- pnpm：前端依赖管理。

### Python 后端

- Python：核心业务开发语言。
- FastAPI：HTTP API 服务。
- SQLAlchemy 2.x：ORM 与数据库访问。
- Pydantic v2：数据结构定义和校验。
- Alembic：数据库结构迁移。
- uv：Python 环境及依赖管理。

### 数据与后台任务

- PostgreSQL：关系型数据库。
- pgvector：向量存储与检索。
- Redis：后台任务队列及相关协调能力。
- ARQ：异步后台任务执行框架。
- Docker Compose：本地基础设施启动。

### AI 模型

- DeepSeek：第一版唯一模型供应商。
- Model Adapter：统一模型接入层。
- 按任务配置模型，不将具体模型型号写死在业务代码中。

## 2.3 整体架构示意

```text
┌──────────────────────────────────────────────┐
│              Electron Desktop                │
│                                              │
│   ┌──────────────────────────────────────┐   │
│   │          Vue 3 + TypeScript          │   │
│   │                                      │   │
│   │  Chat / Memory / Persona / Debug     │   │
│   └──────────────────┬───────────────────┘   │
│                      │ HTTP / SSE            │
│   ┌──────────────────▼───────────────────┐   │
│   │           Electron Main              │   │
│   │       Python Service Manager         │   │
│   └──────────────────┬───────────────────┘   │
└──────────────────────┼───────────────────────┘
                       │
                       ▼
┌──────────────────────────────────────────────┐
│                Python Backend                │
│                                              │
│                 FastAPI                      │
│                                              │
│  ┌──────────┐ ┌──────────┐ ┌──────────────┐  │
│  │ Persona  │ │ Memory   │ │ Dialogue     │  │
│  │ Engine   │ │ Engine   │ │ Engine       │  │
│  └──────────┘ └──────────┘ └──────────────┘  │
│                                              │
│  ┌──────────┐ ┌───────────────────────────┐  │
│  │ State    │ │ Model Adapter             │  │
│  │ Engine   │ │                           │  │
│  └──────────┘ └──────────────┬────────────┘  │
│                              │               │
│  ┌───────────────────────────▼───────────┐  │
│  │          Shared Infrastructure        │  │
│  │ Database / Redis / Events / Config    │  │
│  └───────────────────────────┬───────────┘  │
└──────────────────────────────┼───────────────┘
                               │
                ┌──────────────┴──────────────┐
                ▼                             ▼
        ┌───────────────┐             ┌───────────────┐
        │  PostgreSQL   │             │    Redis      │
        │   + pgvector  │             │               │
        └───────────────┘             └───────┬───────┘
                                              │
                                              ▼
                                       ┌───────────────┐
                                       │  ARQ Worker   │
                                       │               │
                                       └───────────────┘

                               DeepSeek API
```

# 三、工程组织方式

## 3.1 Monorepo

采用前后端分离的 Monorepo：

- 一个 Git 仓库。
- 桌面端和后端分别维护自己的工程。
- 前后端依赖独立管理。
- 统一管理项目文档、基础设施和开发脚本。

## 3.2 项目目录结构

```text
ai-companion/
│
├── apps/
│   │
│   ├── desktop/
│   │   ├── electron/
│   │   │   ├── main.ts
│   │   │   ├── preload.ts
│   │   │   └── services/
│   │   │
│   │   ├── src/
│   │   │   ├── components/
│   │   │   ├── views/
│   │   │   ├── stores/
│   │   │   ├── services/
│   │   │   ├── types/
│   │   │   └── App.vue
│   │   │
│   │   ├── package.json
│   │   └── vite.config.ts
│   │
│   └── server/
│       │
│       ├── app/
│       │   │
│       │   ├── modules/
│       │   │   ├── persona/
│       │   │   ├── memory/
│       │   │   ├── dialogue/
│       │   │   ├── state/
│       │   │   └── model_adapter/
│       │   │
│       │   ├── shared/
│       │   │   ├── database/
│       │   │   ├── redis/
│       │   │   ├── events/
│       │   │   ├── exceptions/
│       │   │   └── utils/
│       │   │
│       │   ├── config/
│       │   └── main.py
│       │
│       ├── workers/
│       ├── tests/
│       ├── pyproject.toml
│       └── .env.example
│
├── infrastructure/
│   └── docker/
│       └── docker-compose.yml
│
├── docs/
│   ├── product/
│   ├── architecture/
│   └── technical/
│
├── scripts/
│
├── .gitignore
└── README.md
```

## 3.3 工程管理工具

| 作用            | 工具           |
| --------------- | -------------- |
| 版本管理        | Git            |
| 前端包管理      | pnpm           |
| 前端构建        | Vite           |
| Python 环境管理 | uv             |
| Python 依赖配置 | pyproject.toml |
| 本地基础设施    | Docker Compose |

不强行统一前后端的包管理工具。

# 四、后端架构设计

## 4.1 架构模式

采用：

**模块化单体（Modular Monolith）**

第一版不采用微服务。

所有业务模块运行在统一的 Python 后端服务中，但通过明确的模块边界保持独立。

五个核心模块：

1. Persona Engine
2. Memory Engine
3. Dialogue Engine
4. State Engine
5. Model Adapter

## 4.2 按业务模块垂直组织

采用 Feature-based Modular Architecture。

每个模块独立维护自己的：

- Domain：领域对象和业务规则。
- Services：业务服务。
- Repositories：数据访问。
- API：对外接口。

示意：

```text
modules/
│
├── persona/
│   ├── domain/
│   ├── services/
│   ├── repositories/
│   └── api/
│
├── memory/
│   ├── domain/
│   ├── services/
│   ├── repositories/
│   └── api/
│
├── dialogue/
│   ├── domain/
│   ├── services/
│   ├── repositories/
│   └── api/
│
├── state/
│   ├── domain/
│   ├── services/
│   ├── repositories/
│   └── api/
│
└── model_adapter/
    ├── domain/
    ├── services/
    ├── providers/
    └── api/
```

具体目录可以随着开发逐步细化，不要求第一天就创建所有空文件。

## 4.3 模块边界

模块之间必须通过对外服务接口协作。

例如：

- Dialogue Engine 可以调用 Persona 服务获取人格。
- Dialogue Engine 可以调用 Memory 服务检索记忆。
- Dialogue Engine 可以调用 State 服务获取当前状态。
- 但 Dialogue Engine 不允许直接访问其他模块的 Repository。
- Model Adapter 统一负责模型调用，其他模块不能直接调用 DeepSeek SDK。

这样可以避免模块之间形成隐式依赖。

# 五、模块通信机制

采用：

**同步接口调用 + 异步事件驱动的混合通信方式。**

## 5.1 同步通信

用于当前业务流程必须立即得到结果的操作。

例如：

| 调用方   | 被调用方      | 用途               |
| -------- | ------------- | ------------------ |
| Dialogue | Persona       | 获取人格信息       |
| Dialogue | Memory        | 检索相关记忆       |
| Dialogue | State         | 获取当前状态       |
| Dialogue | Model Adapter | 执行模型决策与生成 |

## 5.2 异步通信

用于不需要阻塞当前对话的操作。

例如：

- 对话结束后触发记忆提取。
- 记忆提取完成后进行归纳和持久化。
- Embedding 生成。
- 记忆关系更新。
- 后台周期性状态检查。

后台任务通过 Redis + ARQ 执行。

## 5.3 事件驱动

按实际需要引入轻量事件机制。

第一版不引入复杂消息总线。

事件用于通知模块发生了某种业务变化，而不是让模块直接操作彼此的数据。

# 六、数据库架构

## 6.1 数据库选型

- PostgreSQL
- pgvector
- SQLAlchemy 2.x
- Alembic

PostgreSQL 统一存储正式业务数据、长期记忆、向量数据及相关状态。

第一版不引入独立向量数据库。

## 6.2 ORM 和 Repository 组织

采用按业务模块划分模型与 Repository 的方式。

例如：

```text
memory/
│
├── domain/
│   └── entities.py
│
├── repositories/
│   ├── models.py
│   └── memory_repository.py
│
└── services/
```

各模块拥有自己的 ORM 模型和 Repository。

公共数据库能力放在：

```text
shared/database/
├── base.py
├── session.py
└── migrations/
```

## 6.3 事务管理

采用：

**Service 层统一管理事务。**

具体规则：

1. Service 层确定事务边界。
2. Repository 只负责数据库读写。
3. Repository 不自行提交事务。
4. 多个 Repository 可以共享同一个 Session。
5. 发生异常时，由事务机制统一回滚。
6. 跨模块操作优先通过模块服务接口完成。

例如：

```python
async with session.begin():
    await memory_repository.update(...)
    await memory_repository.save_version(...)
    await memory_repository.update_relations(...)
```

保证记忆更新、版本保存和关系维护等操作的一致性。

## 6.4 数据库连接与 Session

采用：

**SQLAlchemy Async Engine + AsyncSession。**

规则：

- FastAPI 使用异步数据库连接。
- ARQ Worker 使用独立 AsyncSession。
- 每个 HTTP 请求创建独立 Session。
- 每个后台任务创建独立 Session。
- Session 不跨请求或任务共享。
- 事务仍由 Service 层管理。

异步主要解决 I/O 等待问题，不代表 CPU 密集型任务会自动加速。

## 6.5 数据库迁移和初始化

采用：

**Alembic + 独立初始化脚本。**

职责：

| 机制       | 负责内容                             |
| ---------- | ------------------------------------ |
| Alembic    | 表、字段、索引、外键、扩展等结构迁移 |
| 初始化脚本 | 初始人格、默认系统配置等基础数据     |
| 运行时     | 不自动修改数据库结构                 |

初始化脚本必须具备幂等性：

- 可以重复执行。
- 不重复创建基础数据。
- 不覆盖用户已经修改的配置。

# 七、后台任务系统

## 7.1 技术选型

采用：

- Redis
- ARQ

FastAPI 在线服务和 ARQ Worker 独立运行。

## 7.2 职责划分

FastAPI：

- 接收用户消息。
- 保存对话记录。
- 组织当前交流上下文。
- 执行交流决策。
- 生成回复。
- 返回 SSE 流。

ARQ Worker：

- 记忆提取。
- 记忆分类。
- 记忆评分。
- 记忆归纳。
- Embedding 生成。
- 记忆关系更新。
- 其他不需要阻塞当前对话的任务。

## 7.3 任务可靠性

必须具备：

- 失败重试。
- 幂等处理。
- 失败任务追踪。
- 错误日志。
- 重试次数记录。
- 任务最终状态记录。

Redis 不存储正式业务记忆，PostgreSQL 是数据事实来源。

重要的任务提交需要考虑数据库事务与队列投递之间的一致性。必要时采用 Outbox 等机制，避免对话记录已经保存但后台任务未成功投递。

# 八、模型接入架构

## 8.1 模型供应商

第一版统一使用 DeepSeek。

目前确定的是供应商，而不是具体模型型号。

具体模型型号、接口能力、价格、上下文长度和 Embedding 能力需要在实际接入时根据 DeepSeek 官方资料核实。

## 8.2 Model Adapter

所有模型调用统一经过 Model Adapter。

业务模块不能直接调用供应商 SDK。

Model Adapter 统一提供：

- 普通文本生成。
- 结构化输出。
- 流式生成。
- Embedding。
- 超时处理。
- 重试机制。
- 异常转换。
- 模型配置管理。
- 调用日志。

## 8.3 按任务配置模型

采用 Task-based Model Routing。

任务配置标识：

| 任务           | 配置标识           |
| -------------- | ------------------ |
| 日常对话       | conversation_model |
| 交流行为决策   | decision_model     |
| 记忆提取与归纳 | memory_model       |
| 记忆 Embedding | embedding_model    |

这些是内部任务标识，不代表具体模型型号。

不同任务可以使用相同模型，也可以分别配置不同模型。

第一版暂时全部使用 DeepSeek。

具体型号通过配置调整，不写死在业务代码中。

## 8.4 Embedding 策略

优先核实 DeepSeek 官方是否提供适合项目的独立 Embedding API。

需要确认：

- 是否有官方 Embedding 接口。
- 支持的模型型号。
- 向量维度。
- 输入限制。
- 价格与调用限制。

如果不满足需求，再单独讨论替代方案。

## 8.5 模型调用失败处理

采用分级降级策略。

| 故障场景            | 处理方式                     |
| ------------------- | ---------------------------- |
| 对话模型超时        | 有限次数重试，失败后明确提示 |
| 决策模型失败        | Python 执行安全默认策略      |
| 记忆模型失败        | 后台任务重试                 |
| Embedding 失败      | 保存原始记忆，等待补充向量   |
| DeepSeek 整体不可用 | 保留历史记录，提示服务不可用 |

不得因为模型调用失败而伪造人格状态、记忆或情绪变化。

# 九、配置管理

采用：

**环境变量 + Pydantic Settings + PostgreSQL 动态配置。**

## 9.1 环境变量

存储：

- DeepSeek API Key。
- PostgreSQL 连接信息。
- Redis 连接信息。
- 数据库密码。
- 基础设施相关配置。

## 9.2 Pydantic Settings

统一读取、校验和管理环境变量。

避免在不同模块中重复读取环境配置。

## 9.3 PostgreSQL 动态配置

存储：

- 模型名称。
- 模型温度。
- Token 限制。
- 不同任务的模型路由。
- 记忆评分权重。
- 主动交流频率。
- 人格配置。
- 其他可动态调整的业务参数。

## 9.4 配置版本管理

重要配置保留：

- 当前配置。
- 历史版本。
- 修改时间。
- 修改内容。
- 版本回滚能力。

未来桌面端调试界面可以直接调整动态配置，不必修改代码。

# 十、上下文管理机制

采用：

**分层上下文组装（Layered Context Assembly）。**

模型调用时，不直接将所有历史聊天记录全部传入。

根据当前任务动态组织上下文。

## 10.1 五层上下文

| 层级       | 内容                             |
| ---------- | -------------------------------- |
| 系统层     | 人格定义、系统规则、行为约束     |
| 状态层     | 当前情绪状态、关系状态、交流状态 |
| 记忆层     | 当前检索到的长期记忆及相关经历   |
| 近期对话层 | 最近若干轮原始对话               |
| 任务层     | 本次模型调用的具体目标           |

## 10.2 不同任务使用不同模板

例如：

- 记忆提取：重点使用对话记录和记忆规则。
- 交流决策：重点使用人格、状态、相关记忆和近期对话。
- 回复生成：使用完整决策结果、必要上下文和近期对话。

## 10.3 上下文管理原则

- 不加载全部长期记忆。
- 按任务检索相关信息。
- 控制 Token 使用量。
- 为模型输出预留 Token 空间。
- 上下文组装过程可追踪。
- 正式记忆、人格和状态以数据库数据为准。

# 十一、LLM 输出与决策机制

采用：

**Pydantic 结构化决策 + 自然语言生成。**

这是 Python 业务逻辑与 LLM 认知能力混合架构的重要组成部分。

## 11.1 决策与表达分离

分为两个阶段：

1. Decision：决定 AI 要做什么。
2. Realization：决定 AI 如何表达。

LLM 先输出结构化行为决策，Python 校验并确定最终执行行为，再进入自然语言生成阶段。

## 11.2 结构化决策

使用 Pydantic 定义决策 Schema。

示例：

```json
{
  "primary_action": "share",
  "secondary_actions": [
    "ask"
  ],
  "topic": "recent_user_experience",
  "motivation": "memory_driven",
  "emotion": "curious",
  "reasoning_summary": "发现用户近期提到一个值得继续了解的话题",
  "confidence": 0.87
}
```

`primary_action` 与 `secondary_actions` 只使用 `respond`、`share`、`ask`、`react`、`continue`、`close`、`quiet`。`quiet` 只作为主行为单独出现。

## 11.3 Python 的职责

- 校验模型输出。
- 检查行为约束。
- 检查执行条件。
- 处理非法决策。
- 更新正式状态。
- 执行最终行为。
- 记录决策过程。

LLM 提供决策建议，最终执行权在 Python。

## 11.4 自然语言生成

根据最终确认的决策生成自然语言回复。

要求：

- 不擅自改变已经确定的行为决策。
- 支持 SSE 流式输出。
- Quiet（保持安静）是合法决策。
- 决策失败时允许 Python 采用安全默认行为。
- 结构化输出错误时允许有限次数修复或重试。

# 十二、API 接口与前后端通信

## 12.1 接口契约

采用：

**FastAPI OpenAPI + 自动生成 TypeScript 类型。**

具体规则：

- 后端使用 Pydantic 定义请求和响应。
- FastAPI 自动生成 OpenAPI。
- 前端从 OpenAPI 自动生成 TypeScript API 类型。
- 后端是接口契约的唯一来源。
- 接口变化后重新生成前端类型。

避免前后端分别维护重复的数据结构定义。

## 12.2 通信协议

| 场景               | 协议        |
| ------------------ | ----------- |
| 普通 API 请求      | HTTP / REST |
| 实时对话           | SSE         |
| 前端与后端类型契约 | OpenAPI     |

第一版采用 SSE 流式回复。

SSE 只是桌面端与服务端之间的传输选择，不限制未来实体设备使用其他通信协议。

# 十三、模型调用日志与可观测性

采用统一的模型调用追踪机制。

## 13.1 记录字段

每次模型调用至少记录：

| 字段          | 用途                |
| ------------- | ------------------- |
| task_type     | 任务类型            |
| model_name    | 实际使用的模型      |
| latency       | 调用耗时            |
| input_tokens  | 输入 Token 数       |
| output_tokens | 输出 Token 数       |
| status        | 成功、失败、超时    |
| error         | 错误信息            |
| trace_id      | 完整交流流程关联 ID |

## 13.2 完整交流追踪

一次用户交流应当可以关联：

1. 用户消息接收。
2. 上下文加载。
3. Persona 数据读取。
4. Memory 检索。
5. State 读取。
6. Dialogue 行为决策。
7. Python 决策校验。
8. 自然语言生成。
9. SSE 回复传输。
10. 后台记忆任务提交和执行。

每个阶段记录必要的耗时和执行结果。

## 13.3 隐私和日志保留

- 原始 Prompt 不默认无限期保存。
- 完整模型输出不默认无限期保存。
- 支持敏感信息脱敏。
- 支持日志保留期限配置。
- 支持关闭详细内容记录。
- 调试信息与正式业务记忆分开存储。

## 13.4 桌面调试控制台

未来桌面端提供：

- 单次交流完整执行链路。
- 各阶段耗时。
- 模型调用详情。
- Token 使用量。
- 决策结构化结果。
- 决策失败原因。
- 后台记忆任务状态。
- 当前人格与状态。
- 记忆检索结果。

# 十四、桌面端与本地运行

## 14.1 桌面端技术

Electron + Vue 3 + TypeScript。

Electron 主进程负责：

- 创建和管理桌面窗口。
- 启动 Python FastAPI 服务。
- 监控 Python 服务运行状态。
- 处理应用退出时的服务关闭。
- 管理桌面端与本地服务之间的通信。

Vue Renderer 负责：

- 聊天界面。
- 记忆管理。
- 人格查看。
- 系统状态查看。
- 调试控制台。
- 配置调整。

Electron Preload 层负责提供必要的安全 IPC 能力，不直接向 Renderer 暴露 Node.js 完整权限。

## 14.2 本地开发环境

第一版采用本地部署调试。

运行组成：

| 组件       | 运行方式         |
| ---------- | ---------------- |
| Electron   | 本地启动         |
| Vue 3      | Vite 开发服务器  |
| FastAPI    | 独立 Python 进程 |
| ARQ Worker | 独立 Python 进程 |
| PostgreSQL | Docker Compose   |
| Redis      | Docker Compose   |
| DeepSeek   | 互联网 API       |

## 14.3 未来扩展

未来可以扩展为：

- 云端 AI Core。
- 桌面端远程客户端。
- 实体硬件接入。
- 多种硬件通信协议。

桌面端、云端和实体设备尽量复用同一套 AI Core 业务能力。

# 十五、当前已确定的技术选型汇总

| 分类         | 技术方案                                      | 状态   |
| ------------ | --------------------------------------------- | ------ |
| 整体架构     | 模块化单体                                    | 已确定 |
| 工程组织     | Monorepo                                      | 已确定 |
| 桌面端       | Electron                                      | 已确定 |
| 前端         | Vue 3 + TypeScript                            | 已确定 |
| 前端构建     | Vite                                          | 已确定 |
| 前端包管理   | pnpm                                          | 已确定 |
| 后端         | Python                                        | 已确定 |
| 后端框架     | FastAPI                                       | 已确定 |
| ORM          | SQLAlchemy 2.x                                | 已确定 |
| 数据校验     | Pydantic v2                                   | 已确定 |
| 数据库       | PostgreSQL                                    | 已确定 |
| 向量扩展     | pgvector                                      | 已确定 |
| 数据库迁移   | Alembic                                       | 已确定 |
| 数据库访问   | Async Engine + AsyncSession                   | 已确定 |
| 事务管理     | Service 层管理                                | 已确定 |
| 后台队列     | Redis + ARQ                                   | 已确定 |
| 模型供应商   | DeepSeek                                      | 已确定 |
| 模型接入     | Model Adapter                                 | 已确定 |
| 模型路由     | Task-based Model Routing                      | 已确定 |
| 上下文管理   | 分层上下文组装                                | 已确定 |
| 决策输出     | Pydantic 结构化输出                           | 已确定 |
| 自然语言回复 | LLM 流式生成                                  | 已确定 |
| 前后端契约   | OpenAPI                                       | 已确定 |
| 普通通信     | HTTP / REST                                   | 已确定 |
| 流式通信     | SSE                                           | 已确定 |
| 配置管理     | 环境变量 + Pydantic Settings + 数据库动态配置 | 已确定 |
| 本地基础设施 | Docker Compose                                | 已确定 |
| 日志与追踪   | 统一模型调用可观测性                          | 已确定 |

# 十六、尚待实施阶段核实的事项

虽然整体技术方向已经确定，但以下细节不应该在没有验证的情况下提前写死。

1. DeepSeek 实际使用的对话模型和轻量任务模型型号。
2. DeepSeek 是否提供满足项目需求的官方 Embedding API。
3. Embedding 模型的具体向量维度和 PostgreSQL 索引参数。
4. 不同模型任务的 Token 限制、超时和重试参数。
5. 各业务模块最终的数据库表结构。
6. 具体 API 路由、请求和响应 Schema。
7. SSE 事件类型与错误事件协议。
8. Dialogue Engine 结构化决策 Schema 的完整字段。
9. ARQ 任务的幂等键、重试策略和失败任务处理机制。
10. Electron 打包后 Python 服务及其运行依赖的分发方式。

这些属于实施细节，需要通过官方文档核实、技术验证和实际开发逐步确定，不影响当前整体架构决策。

# 十七、后续开发推进顺序

建议按照以下顺序推进：

**阶段一：工程基础建设**

- 创建 Monorepo。
- 初始化 Electron + Vue 3。
- 初始化 FastAPI。
- 配置 Python 环境。
- 配置 PostgreSQL、pgvector 和 Redis。
- 配置 Alembic。
- 打通桌面端与本地 Python 服务。

**阶段二：基础设施与模型接入**

- 实现数据库连接管理。
- 实现 Redis 和 ARQ。
- 实现 Pydantic Settings。
- 实现 Model Adapter。
- 接入 DeepSeek。
- 实现模型调用日志与追踪。

**阶段三：核心数据模型**

- 用户与会话。
- 对话消息。
- 人格配置。
- 记忆实体。
- 记忆版本与关联。
- AI 状态。
- 模型配置。
- 决策记录。

**阶段四：核心引擎**

- Persona Engine。
- Memory Engine。
- State Engine。
- Dialogue Engine。

**阶段五：桌面调试能力**

- 聊天界面。
- 人格查看。
- 记忆管理。
- 状态查看。
- 决策追踪。
- 模型调用监控。

**阶段六：完整交流流程**

- 用户消息接收。
- 上下文组装。
- 交流行为决策。
- Python 校验和执行。
- 自然语言生成。
- SSE 流式输出。
- 后台记忆处理。

**阶段七：系统验证**

- 连续对话测试。
- 长期记忆测试。
- 人格稳定性测试。
- 主动交流测试。
- 模型故障测试。
- 后台任务可靠性测试。
- 桌面端长时间运行测试。

------

# 十八、技术决策原则

从本次讨论开始，项目后续技术选型和实现方案默认采用推荐方案，不再逐项询问是否确认。

但存在重大架构分歧、明显技术风险、不可逆选择或可能推翻已有决策时，需要先说明原因并征求意见。

整体遵循：

- 优先保证第一版可落地。
- 优先选择成熟、可靠、可维护的技术。
- 避免为了未来可能的需求过度设计。
- 保持业务模块之间的清晰边界。
- 重要数据和状态由 Python 业务逻辑控制。
- LLM 负责认知判断和自然语言表达。
- 所有关键决策都应当可以追踪、验证和调试。
- 通过实际使用验证产品设计，再决定后续迭代方向。

**第一版的核心目标不是建立一个复杂的 AI 技术平台，而是做出一个真正能够长期相处、具备稳定人格和连续记忆的 AI Companion。**