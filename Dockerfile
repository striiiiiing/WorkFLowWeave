# syntax=docker/dockerfile:1
ARG PYTHON_IMAGE=python:3.12-slim-bookworm
FROM node:24.15.0-bookworm-slim AS node
FROM ghcr.io/astral-sh/uv:0.11.2 AS uv

FROM ${PYTHON_IMAGE} AS python-base
RUN sed -i 's|http://deb.debian.org|https://deb.debian.org|g' /etc/apt/sources.list.d/debian.sources

FROM node AS frontend-build
WORKDIR /frontend
COPY frontend/package*.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM python-base AS backend-build
RUN apt-get update \
    && apt-get install -y --no-install-recommends git ca-certificates \
    && rm -rf /var/lib/apt/lists/*
COPY --from=uv /uv /usr/local/bin/uv
WORKDIR /build
ENV UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/opt/workflowweave/venv
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --extra channels --no-install-project
COPY README.md LICENSE ./
COPY src/ ./src/
COPY hatch_build.py ./
COPY frontend/ ./frontend/
COPY --from=node /usr/local/bin/node /usr/local/bin/node
COPY --from=node /usr/local/lib/node_modules/ /usr/local/lib/node_modules/
RUN ln -s /usr/local/lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --extra channels --no-editable

FROM python-base AS runtime
# Node is required by the bundled WeChat channel.
COPY --from=node /usr/local/bin/node /usr/local/bin/node
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates libstdc++6 libatomic1 \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --uid 10001 --create-home --home-dir /var/lib/workflowweave workflowweave \
    && mkdir -p /var/lib/workflowweave/user-plugins \
    && chown -R workflowweave:workflowweave /var/lib/workflowweave
LABEL org.opencontainers.image.source="https://github.com/striiiiiing/WorkFLowWeave"
ENV PATH="/opt/workflowweave/venv/bin:${PATH}" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    HOME=/var/lib/workflowweave \
    WORKFLOWWEAVE_API_URL=http://127.0.0.1:4333

FROM runtime AS backend
# Only installed artifacts cross the build boundary; source and caches stay behind.
COPY --from=backend-build /opt/workflowweave/venv/ /opt/workflowweave/venv/
COPY deploy/docker/bootstrap.py /opt/workflowweave/bootstrap.py
USER workflowweave
WORKDIR /var/lib/workflowweave
VOLUME ["/var/lib/workflowweave"]
EXPOSE 4333
HEALTHCHECK --interval=10s --timeout=5s --start-period=60s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:4333/api/health', timeout=4).read()"
ENTRYPOINT ["python", "/opt/workflowweave/bootstrap.py"]

FROM backend AS all-in-one
USER root
RUN apt-get update \
    && apt-get install -y --no-install-recommends nginx \
    && rm -rf /var/lib/apt/lists/* /etc/nginx/sites-enabled/default
COPY --from=frontend-build /frontend/dist/ /usr/share/nginx/html/
COPY deploy/docker/nginx.all-in-one.conf /etc/nginx/conf.d/default.conf
COPY deploy/docker/all-in-one.py /opt/workflowweave/all-in-one.py
EXPOSE 80
HEALTHCHECK --interval=10s --timeout=5s --start-period=60s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1/api/health', timeout=4).read()"
ENTRYPOINT ["python", "/opt/workflowweave/all-in-one.py"]

FROM nginx:1.28-alpine AS frontend
COPY deploy/docker/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=frontend-build /frontend/dist/ /usr/share/nginx/html/
LABEL org.opencontainers.image.source="https://github.com/striiiiiing/WorkFLowWeave"
EXPOSE 80
