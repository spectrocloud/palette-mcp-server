# Copyright (c) Spectro Cloud
# SPDX-License-Identifier: Apache-2.0

# Build stage - download binaries and build dependencies
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS builder

ARG VERSION=0.0.1

# Make VERSION available as environment variable
ENV VERSION=${VERSION}

# Install build tools and download binaries
RUN apt-get update -y && apt-get upgrade -y && \
    apt-get install -y ca-certificates curl unzip

# Copy source and install Python dependencies
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


# Copy VERSION from builder stage
ARG VERSION=0.0.1
ENV VERSION=${VERSION}

RUN apt-get update -y && \
    apt-get install -y ca-certificates && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*


COPY --from=builder /app /app

WORKDIR /app

CMD ["uv", "run", "python", "src/server.py"]
