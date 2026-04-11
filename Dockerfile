FROM python:3.12-slim

# gosu: lightweight sudo-equivalent for privilege drop in entrypoint scripts
# (same pattern used by official postgres/redis/mysql images)
RUN apt-get update && apt-get install -y --no-install-recommends gosu \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user with home dir at /root (matches ~/.kore mount target)
RUN groupadd --gid 1000 kore && \
    useradd --uid 1000 --gid kore --shell /bin/bash --home /root kore && \
    mkdir -p /root && chown kore:kore /root

WORKDIR /app

# Install deps (non-editable; editable install is for local dev only)
COPY pyproject.toml .
COPY src/ src/
RUN pip install uv && \
    uv pip install --no-cache --system .

# Bake prompts and built-in skills into image — not user-editable, no runtime mount needed
COPY prompts/ prompts/
COPY skills/ skills/
ENV KORE_PROMPTS_DIR=/app/prompts

# Entrypoint runs as root, fixes ~/.kore ownership, then drops to kore (uid 1000)
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
CMD ["gateway"]
