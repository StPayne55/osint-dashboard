# Dedicated SpiderFoot OSS v4.0 runner (not HX, not the poppopjmp v6 stack).
# Reuses docker/install_spiderfoot.sh + Account Finder patch from the repo root.
FROM python:3.12-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    SPIDERFOOT_HOME=/opt/spiderfoot \
    SPIDERFOOT_MAX_THREADS=8 \
    PORT=10000

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        wget ca-certificates gcc g++ \
        libxml2 libxslt1.1 libxml2-dev libxslt1-dev zlib1g-dev

COPY docker/spiderfoot-requirements.txt docker/patch_spiderfoot.py docker/install_spiderfoot.sh /tmp/sf-install/
RUN chmod +x /tmp/sf-install/install_spiderfoot.sh \
    && /tmp/sf-install/install_spiderfoot.sh \
         /tmp/sf-install/spiderfoot-requirements.txt \
         /tmp/sf-install/patch_spiderfoot.py \
    && apt-get purge -y gcc g++ wget libxml2-dev libxslt1-dev zlib1g-dev \
    && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/* /tmp/sf-install /root/.cache /root/.spiderfoot

COPY spiderfoot-runner/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt
COPY spiderfoot-runner/ /app/

EXPOSE 10000
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-10000}"]
