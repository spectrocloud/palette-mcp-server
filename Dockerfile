FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

LABEL org.opencontainers.image.description="Palette MCP Server"
ENV PALETTE_AI_SERVER_PORT=9000

ENV K8SGPT_BACKEND=openai
ENV K8SGPT_AI_PROVIDER=openai
ENV K8SGPT_MODEL=gpt-4
ARG K8SGPT_VERSION=0.4.16
ARG KUBELOGIN_VERSION=1.32.4

RUN apt-get update -y && apt-get upgrade -y && \
    apt-get install -y ca-certificates curl bash gnupg unzip dnsutils vim && \
    uv tool install flask && \
    curl -LO https://github.com/k8sgpt-ai/k8sgpt/releases/download/v${K8SGPT_VERSION}/k8sgpt_Linux_x86_64.tar.gz && \
    tar -xzf k8sgpt_Linux_x86_64.tar.gz && \
    mv k8sgpt /usr/local/bin/ && \
    rm k8sgpt_Linux_x86_64.tar.gz && \
    curl -LO https://github.com/int128/kubelogin/releases/download/v${KUBELOGIN_VERSION}/kubelogin_linux_amd64.zip && \
    unzip -o kubelogin_linux_amd64.zip && \
    mv kubelogin /usr/local/bin/ && \
    rm kubelogin_linux_amd64.zip && \
    chmod +x /usr/local/bin/kubelogin && \
    curl -LO "https://dl.k8s.io/release/$(curl -L -s https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl" && \
    install -o root -g root -m 0755 kubectl /usr/local/bin/kubectl && \
    chmod +x kubectl && \
    mv kubectl /usr/local/bin/ && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

 
COPY . /app
WORKDIR /app

RUN uv sync --frozen
EXPOSE 9000


# The -- is used to pass the arguments to the uv command so that Python interpreter managed by uv is used
CMD ["bash", "-c", "uv run -- uvicorn server:app --host 0.0.0.0 --port ${PALETTE_AI_SERVER_PORT}"]
