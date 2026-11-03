FROM python:3.11-alpine3.23 AS builder

RUN apk add --no-cache \
    build-base cargo libffi-dev libxml2-dev libxslt-dev openssl-dev

WORKDIR /app
COPY pyproject.toml uv.lock ./
COPY jmcp.py jmcp_token_manager.py ./
COPY utils/ ./utils/
COPY block.cmd block.cfg ./

RUN python -m venv /opt/uv \
 && /opt/uv/bin/pip install --no-cache-dir uv==0.12.1 \
 && /opt/uv/bin/uv sync --frozen --no-dev --no-install-project \
 && /app/.venv/bin/python -c \
      "import jnpr.junos, jxmlease, lxml, mcp, ncclient, paramiko, psutil, serial, starlette, uvicorn"

FROM python:3.11-alpine3.23

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV MCP_SERVER_HOST=0.0.0.0
ENV MCP_SERVER_PORT=30030
ENV MCP_TRANSPORT=stdio
ENV DEVICE_CONFIG=/app/config/devices.json
ENV LOG_LEVEL=INFO
ENV FASTMCP_HOST=0.0.0.0
ENV PATH="/app/.venv/bin:$PATH"

RUN apk add --no-cache libffi libgcc libstdc++ libxml2 libxslt openssh-client openssl \
 && addgroup -S jmcp \
 && adduser -S -G jmcp -s /bin/sh jmcp

WORKDIR /app
COPY --from=builder /app/.venv /app/.venv
COPY --from=builder /app/jmcp.py /app/jmcp_token_manager.py ./
COPY --from=builder /app/utils/ ./utils/
COPY --from=builder /app/block.cmd /app/block.cfg ./

RUN mkdir -p /app/config /app/logs /app/backups \
 && chown -R jmcp:jmcp /app \
 && chmod 755 /app/jmcp.py

USER jmcp

LABEL maintainer="Nilesh Simaria"
LABEL description="Junos MCP Server"
LABEL version="1.1.0"
LABEL org.opencontainers.image.source="https://github.com/Juniper/junos-mcp-server"

EXPOSE 30030

HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import psutil; raise SystemExit(0 if psutil.Process().is_running() else 1)"

CMD ["python", "jmcp.py", "-f", "/app/config/devices.json", "-t", "stdio"]
