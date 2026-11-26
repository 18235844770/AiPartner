# AI Companion

当前进度见 [开发进度.md](开发进度.md)。第一到第六阶段已实现，第七阶段已做现场验证；桌面端长时间运行和全量后台调度还没有验收。

第一版本地桌面端。当前包含工程骨架、FastAPI、数据库公共层、Model Adapter，以及 Identity、Conversation、Persona、Memory、State、Dialogue 和 Infrastructure。用户消息和主动交流先做结构化决策，Quiet 不生成回复。后台任务先写入 PostgreSQL，再由 ARQ 投递。用户消息提交后会安排记忆提取，结果只先记为候选；写入后会记录重要性评估。来源可靠且与当前话题相关的候选可以进入本轮决策，但不会因此升为正式记忆。当前这句话会作为即时事实进入同一回合。

## 本地基础设施

```powershell
docker compose -f infrastructure/docker/docker-compose.yml up -d
```

## 后端

```powershell
cd apps/server
copy .env.example .env
uv sync
uv run alembic upgrade head
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000
uv run arq app.modules.infrastructure.worker.WorkerSettings
```

## 桌面端

```powershell
cd apps/desktop
pnpm install
pnpm dev
```

桌面端主进程会启动本地 Python 服务。开发页面也可以单独通过 Vite 访问，并请求 `http://127.0.0.1:8000`。

## 多用户移动 Web

在 `apps/server` 目录运行，确保 PostgreSQL、pgvector 与 Redis 已就绪：

```powershell
uv sync --locked
uv run alembic upgrade head
$env:ACCOUNT_MODE = "true"
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000
```

另开一个终端，在同一目录设置 `ACCOUNT_MODE=true` 并运行 `uv run arq app.modules.infrastructure.worker.WorkerSettings`。使用浏览器打开 `http://127.0.0.1:8000/mobile/`。对外部署由 HTTPS 反向代理在同一域名转发 `/mobile/` 和 `/api/`，并为 SSE 关闭响应缓冲。API 与 Worker 应连接同一 PostgreSQL、Redis 和音频存储。多用户模式只注册账号及聊天 API。本地 Electron 使用默认模式和独立开发数据库。

移动端使用用户名和密码。注册后客户端继续登录，服务端返回初始化状态。可使用 `PROACTIVE_DAILY_BUDGET` 设置每位伴侣每 24 小时的主动评估上限，默认 24。`ACCOUNT_INTEGRATION_TESTS=1` 可启用真实 PostgreSQL 和 Redis 的账号集成用例。
