# AiPartner 邀请制内测部署

该部署覆盖移动 Web、FastAPI、ARQ、PostgreSQL + pgvector、Redis 和 HTTPS 网关。内测入口使用网关邀请凭据，注册和聊天继续使用各自的应用账号。默认关闭主动评估，便于控制小规模验收的模型调用。

## 启动

1. 复制 `infrastructure/docker/beta.env.example` 为仓库根目录的 `.env.beta`。填入正式 `DEEPSEEK_API_KEY`、仅含字母和数字的随机 `BETA_DB_PASSWORD`，以及 `BETA_INVITE_HASH`。用 `docker run --rm -it caddy:2-alpine caddy hash-password` 交互生成邀请密码哈希，保留配置示例中的单引号。
2. 本地使用示例的回环地址和端口。对外邀请时，将 `BETA_SITE_ADDRESS` 设为已解析到部署机的域名，将 `BETA_BIND_HOST` 及 HTTP/HTTPS 端口设为服务器实际入口，确保 Caddy 能签发证书。只对外暴露网关端口。
3. 从仓库根目录执行以下命令。首次启动会构建移动端和后端镜像、迁移数据库，并初始化决策、对话、记忆和本地向量模型的默认配置。重复启动保留数据库中的现有默认模型。

```sh
docker compose --env-file .env.beta -f infrastructure/docker/compose.beta.yml up -d --build --wait
docker compose --env-file .env.beta -f infrastructure/docker/compose.beta.yml ps
```

本地访问 `https://localhost:8443/mobile/`。Caddy 为 localhost 生成测试证书，验证时使用它的根证书。可用 `docker compose --env-file .env.beta -f infrastructure/docker/compose.beta.yml cp gateway:/data/caddy/pki/authorities/local/root.crt ./beta-local-root.crt` 导出，再用 `curl --cacert beta-local-root.crt --user tester https://localhost:8443/health` 检查。公开域名使用正式证书。初次向量生成需要下载 Qwen3 Embedding 0.6B 的量化权重，应用与 Worker 共用持久化缓存。内测初始化会将旧的 BGE-M3 默认配置升级为当前支持的模型。已有记忆文本保留，检索仅比较同模型的向量。

## 发布和恢复

- 发布前保留当前 `BETA_APP_IMAGE` 的镜像标签，对 PostgreSQL 做自定义格式备份。用 `pg_dump -Fc` 生成备份，例如通过 `docker compose exec -T postgres pg_dump -U companion -Fc -f /tmp/companion.dump companion` 和 `docker compose cp postgres:/tmp/companion.dump ./companion.dump`。两条命令都需要使用上述 Compose 文件和环境参数。
- 将备份恢复到独立的空数据库后校验 Alembic 版本和用户、会话、消息、记忆的行数。若涉及音频，另备份 `audio` 卷。发布后的向后不兼容迁移通过备份恢复并切回旧镜像处理。
- `ps` 检查 API 与 Worker 健康状态，`logs --tail 100 api worker gateway` 排查异常。外部用户访问只分发邀请凭据和 HTTPS 地址。账号注销后还应按内测约定处理备份副本的保留周期。

## 内测验收

使用两个测试账号及独立浏览器会话。验证邀请入口、注册与伴侣配置、实际模型回复、同账号换设备恢复和跨账号隔离。停止 Worker 后提交消息并确认返回已接受，再启动 Worker 验证同一回合得到处理。发送一个明确的测试事实，确认记忆提取、摘要和召回，最后注销测试账户并检查其会话撤销及后台清理。正式环境启用语音时，需单独部署 Audio Worker 并验证 TTS。
