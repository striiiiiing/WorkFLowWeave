# syntax=docker/dockerfile:1
FROM node:24.15.0-bookworm-slim AS node
FROM ghcr.io/astral-sh/uv:0.11.2 AS uv

FROM node AS frontend-build
WORKDIR /frontend
COPY frontend/package*.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM node AS wechat-deps
WORKDIR /wechat
COPY src/workflowweave/plugins/channel/wechat_openclaw/package*.json ./
RUN npm ci --ignore-scripts --no-audit --no-fund

FROM python:3.12-slim-bookworm AS runtime
COPY --from=node /usr/local/bin/node /usr/local/bin/node
COPY --from=node /usr/local/lib/node_modules/ /usr/local/lib/node_modules/
RUN ln -s /usr/local/lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
    && ln -s /usr/local/lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx
RUN sed -i 's|http://deb.debian.org|https://deb.debian.org|g' /etc/apt/sources.list.d/debian.sources \
    && apt-get -o Acquire::https::Timeout=30 update \
    && apt-get -o Acquire::https::Timeout=30 install -y --no-install-recommends git ca-certificates \
    && rm -rf /var/lib/apt/lists/*
COPY --from=uv /uv /uvx /usr/local/bin/
LABEL org.opencontainers.image.source="https://github.com/striiiiiing/WorkFLowWeave"

FROM runtime AS backend
WORKDIR /app
ENV UV_LINK_MODE=copy
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --extra channels --no-install-project
COPY README.md LICENSE ./
COPY src/ ./src/
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --extra channels --no-editable
COPY --from=wechat-deps /wechat/node_modules/ /app/.venv/lib/python3.12/site-packages/workflowweave/plugins/channel/wechat_openclaw/node_modules/
COPY deploy/docker/bootstrap.py /app/deploy/bootstrap.py
RUN useradd --uid 10001 --create-home workflowweave \
    && mkdir -p /var/lib/workflowweave/user-plugins \
    && chown -R workflowweave:workflowweave /var/lib/workflowweave
LABEL org.opencontainers.image.source="https://github.com/striiiiiing/WorkFLowWeave"
ENV PATH="/app/.venv/bin:${PATH}" \
    PYTHONUNBUFFERED=1 \
    WORKFLOWWEAVE_API_URL=http://127.0.0.1:4300
USER workflowweave
WORKDIR /var/lib/workflowweave
VOLUME ["/var/lib/workflowweave"]
EXPOSE 4300
HEALTHCHECK --interval=10s --timeout=5s --start-period=60s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:4300/api/health', timeout=4).read()"
ENTRYPOINT ["python", "/app/deploy/bootstrap.py"]

FROM nginx:1.28-alpine AS frontend
COPY deploy/docker/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=frontend-build /frontend/dist/ /usr/share/nginx/html/
LABEL org.opencontainers.image.source="https://github.com/striiiiiing/WorkFLowWeave"
EXPOSE 80
