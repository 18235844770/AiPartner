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
