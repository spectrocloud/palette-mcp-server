# Copyright (c) Spectro Cloud
# SPDX-License-Identifier: Apache-2.0


FROM ghcr.io/astral-sh/uv:python3.14-bookworm-slim AS uv-bin
FROM dhi.io/python:3 AS builder

ARG VERSION=0.0.1


ENV VERSION=${VERSION}
ENV UV_NO_MANAGED_PYTHON=1


COPY --from=uv-bin /usr/local/bin/uv /usr/local/bin/uv
COPY --from=uv-bin /usr/local/bin/uvx /usr/local/bin/uvx


COPY --chown=65532:65532 . /app
WORKDIR /app
RUN ["uv", "sync", "--frozen", "--python", "/opt/python/bin/python"]


FROM dhi.io/python:3

ARG VERSION=0.0.1
ENV UV_NO_MANAGED_PYTHON=1

LABEL org.opencontainers.image.title="Palette MCP Server"
LABEL org.opencontainers.image.description="An MCP server for Palette"
LABEL org.opencontainers.image.licenses="Apache-2.0"
LABEL org.opencontainers.image.source=https://github.com/spectrocloud/palette-mcp-server
LABEL org.opencontainers.image.version=${VERSION}
LABEL org.opencontainers.image.vendor="Spectro Cloud"



ENV VERSION=${VERSION}

COPY --from=uv-bin /usr/local/bin/uv /usr/local/bin/uv
COPY --from=uv-bin /usr/local/bin/uvx /usr/local/bin/uvx
COPY --from=builder /app /app

WORKDIR /app

CMD ["uv", "run", "python", "src/server.py"]
