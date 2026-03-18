# Copyright (c) Spectro Cloud
# SPDX-License-Identifier: Apache-2.0


FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS builder

ARG VERSION=0.0.1


ENV VERSION=${VERSION}


RUN apt-get update -y && apt-get upgrade -y && \
    apt-get install -y ca-certificates curl unzip


COPY . /app
WORKDIR /app
RUN uv sync --frozen


FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

LABEL org.opencontainers.image.title="Palette MCP Server"
LABEL org.opencontainers.image.description="An MCP server for Palette"
LABEL org.opencontainers.image.licenses="Apache-2.0"
LABEL org.opencontainers.image.source=https://github.com/palette-ai/palette-mcp-server
LABEL org.opencontainers.image.version=${VERSION}
LABEL org.opencontainers.image.vendor="Spectro Cloud"



ARG VERSION=0.0.1
ENV VERSION=${VERSION}

RUN apt-get update -y && \
    apt-get install -y ca-certificates && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*


COPY --from=builder /app /app

WORKDIR /app

CMD ["uv", "run", "python", "src/server.py"]
