FROM docker.io/library/node:24-alpine AS console
WORKDIR /src/web
COPY web/package*.json ./
RUN npm ci
COPY web/ ./
RUN npm run build

FROM docker.io/library/python:3.12-slim
WORKDIR /app
COPY pyproject.toml README.md LICENSE NOTICE ./
COPY nuvora/ ./nuvora/
COPY --from=console /src/nuvora/static ./nuvora/static/
# Optional extras (PDF parsing, SSO JWT verification, Postgres, AWS, OCR) ship in the image.
RUN apt-get update && apt-get install -y --no-install-recommends tesseract-ocr && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir '.[all]' && rm -rf /app/*
RUN groupadd --gid 10001 nuvora && useradd --uid 10001 --gid 10001 --no-create-home nuvora && mkdir /data && chown nuvora:nuvora /data
USER 10001:10001
EXPOSE 8789
ENV PYTHONUNBUFFERED=1
VOLUME ["/data"]
HEALTHCHECK --interval=30s --timeout=3s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8789/healthz', timeout=2)"
ENTRYPOINT ["python", "-m", "nuvora.server", "--host", "0.0.0.0", "--port", "8789", "--db", "/data/nuvora.db"]
