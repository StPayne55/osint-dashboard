FROM node:22-alpine AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm install
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/backend \
    PORT=8742 \
    SPIDERFOOT_HOME=/opt/spiderfoot
ARG INSTALL_SPIDERFOOT=1
RUN apt-get update \
    && apt-get install -y --no-install-recommends gcc libffi-dev \
    && rm -rf /var/lib/apt/lists/*
COPY backend/requirements.txt /app/backend/requirements.txt
RUN pip install --no-cache-dir -r /app/backend/requirements.txt
# Optional local SpiderFoot OSS (not HX) lives in its own venv so
# Flask/CherryPy pins cannot collide with FastAPI. Costs ~200–400MB; pass
# --build-arg INSTALL_SPIDERFOOT=0 to skip. On Render, prefer the separate
# spiderfoot-runner service instead of invoking sf.py in this web process.
COPY docker/spiderfoot-requirements.txt docker/patch_spiderfoot.py docker/accounts_tune.py docker/wmn-priority.json docker/install_spiderfoot.sh /tmp/sf-install/
RUN if [ "$INSTALL_SPIDERFOOT" = "1" ]; then \
      apt-get update \
      && apt-get install -y --no-install-recommends \
        wget ca-certificates gcc g++ \
        libxml2 libxslt1.1 libxml2-dev libxslt1-dev zlib1g-dev \
      && chmod +x /tmp/sf-install/install_spiderfoot.sh \
      && /tmp/sf-install/install_spiderfoot.sh \
           /tmp/sf-install/spiderfoot-requirements.txt \
           /tmp/sf-install/patch_spiderfoot.py \
      && apt-get purge -y gcc g++ wget libxml2-dev libxslt1-dev zlib1g-dev \
      && apt-get autoremove -y \
      && rm -rf /var/lib/apt/lists/* /tmp/sf-install /root/.cache /root/.spiderfoot; \
    else \
      echo "Skipping SpiderFoot OSS install"; \
      rm -rf /tmp/sf-install; \
    fi
COPY backend/ /app/backend/
COPY --from=web /web/dist /app/frontend/dist
EXPOSE 8742
WORKDIR /app/backend
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8742}"]
