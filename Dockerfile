# Build stage - download binaries and build dependencies
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS builder

ARG K8SGPT_VERSION=0.4.16
ARG KUBELOGIN_VERSION=1.32.4
ARG VERSION=0.0.1

# Make VERSION available as environment variable
ENV VERSION=${VERSION}

# Install build tools and download binaries
RUN apt-get update -y && apt-get upgrade -y && \
    apt-get install -y ca-certificates curl unzip
    # curl -LO https://github.com/k8sgpt-ai/k8sgpt/releases/download/v${K8SGPT_VERSION}/k8sgpt_Linux_x86_64.tar.gz && \
    # tar -xzf k8sgpt_Linux_x86_64.tar.gz && \
    # chmod +x k8sgpt && \
    # curl -LO https://github.com/int128/kubelogin/releases/download/v${KUBELOGIN_VERSION}/kubelogin_linux_amd64.zip && \
    # unzip -o kubelogin_linux_amd64.zip && \
    # chmod +x kubelogin && \
    # curl -LO "https://dl.k8s.io/release/$(curl -L -s https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl" && \
    # chmod +x kubectl

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



# ENV K8SGPT_BACKEND=openai
# ENV K8SGPT_AI_PROVIDER=openai
# ENV K8SGPT_MODEL=gpt-4

# Copy VERSION from builder stage
ARG VERSION=0.0.1
ENV VERSION=${VERSION}

RUN apt-get update -y && \
    apt-get install -y ca-certificates && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*


# COPY --from=builder /k8sgpt /usr/local/bin/k8sgpt
# COPY --from=builder /kubelogin /usr/local/bin/kubelogin
# COPY --from=builder /kubectl /usr/local/bin/kubectl


COPY --from=builder /app /app

WORKDIR /app

CMD ["uv", "run", "python", "src/server.py"]
