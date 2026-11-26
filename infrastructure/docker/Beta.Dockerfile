FROM node:22-bookworm-slim AS mobile
WORKDIR /project/apps/mobile
RUN npm install --global pnpm@10.10.0
COPY apps/mobile/package.json apps/mobile/pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile
COPY apps/mobile/ ./
COPY static/slices/ /project/static/slices/
RUN pnpm build

FROM python:3.13-slim-bookworm
COPY --from=ghcr.io/astral-sh/uv:0.8.22 /uv /usr/local/bin/uv
WORKDIR /project/apps/server
COPY apps/server/pyproject.toml apps/server/uv.lock ./
RUN uv sync --locked --no-dev && useradd --system --uid 10001 --create-home app \
    && mkdir -p /data/audio /data/embedding && chown -R app:app /data
COPY apps/server/app/ ./app/
COPY apps/server/alembic/ ./alembic/
COPY apps/server/alembic.ini ./
COPY apps/server/scripts/init_model_configs.py ./scripts/
COPY --from=mobile /project/apps/mobile/dist /project/apps/mobile/dist
ENV PATH="/project/apps/server/.venv/bin:$PATH" PYTHONUNBUFFERED=1
USER app
