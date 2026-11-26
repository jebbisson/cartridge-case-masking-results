# syntax=docker/dockerfile:1
FROM node:20.19.2-bookworm-slim AS web-build
WORKDIR /src/web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/index.html web/vite.config.js ./
COPY web/src ./src
RUN npm run build

FROM golang:1.24.4-bookworm AS go-build
WORKDIR /src
COPY go.mod go.sum ./
RUN go mod download
COPY cmd ./cmd
COPY internal ./internal
RUN CGO_ENABLED=1 go build -trimpath -o /out/reviewapp ./cmd/reviewapp

FROM python:3.14.9-slim-bookworm AS runtime
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 \
    REVIEWAPP_CONTAINER_BIND=1 REVIEWAPP_DATA_DIR=/data REVIEWAPP_STARTER_DIR=/opt/starter/bundle
WORKDIR /app
COPY python/requirements.txt /app/python/requirements.txt
RUN pip install --no-cache-dir --only-binary=:all: -r python/requirements.txt \
    && groupadd --gid 10001 workbench && useradd --uid 10001 --gid workbench workbench \
    && install -d -m 0750 -o workbench -g workbench /data \
    && install -m 0640 -o workbench -g workbench /dev/null /data/.workbench-volume
COPY --from=go-build /out/reviewapp /usr/local/bin/reviewapp
COPY --from=web-build /src/web/dist /app/web/dist
COPY LICENSE /app/LICENSE
COPY docs/data-licenses.md /opt/starter/DATA-LICENSES.md
COPY python/*.py /app/python/
COPY python/arrow_head_v1.json /app/python/arrow_head_v1.json
COPY deployment/bootstrap.py /app/deployment/bootstrap.py
COPY deployment/assemble_seed.py /app/deployment/assemble_seed.py
COPY deployment/starter.parts.sha256 /app/deployment/starter.parts.sha256

# The release image has one starter. Copy only fixed, independently pinned
# files from the dedicated build context, never the dataset or a working DB.
COPY deployment/starter.full.sha256 /app/deployment/starter.sha256
COPY training/ATTRIBUTION.md /opt/starter/ATTRIBUTION.md
COPY --from=starter_bundle /SHA256SUMS /opt/starter/parts/SHA256SUMS
COPY --from=starter_bundle /PARTS.sha256 /opt/starter/parts/PARTS.sha256
COPY --from=starter_bundle /review.sqlite.part-* /opt/starter/parts/
COPY --from=starter_bundle /review.sqlite.runs/1/checkpoint.json /opt/starter/parts/review.sqlite.runs/1/checkpoint.json
# Assemble as build-time root; the runtime UID still checks the full seed below.
RUN python /app/deployment/assemble_seed.py --bundle /opt/starter/parts \
      --output /opt/starter/bundle --pins /app/deployment/starter.sha256 \
      --parts-pins /app/deployment/starter.parts.sha256 \
    && rm -r /opt/starter/parts
# Set file and directory modes separately: COPY --chmod can also affect parent directories.
RUN chmod 0755 /opt/starter /opt/starter/bundle \
        /opt/starter/bundle/review.sqlite.runs /opt/starter/bundle/review.sqlite.runs/1 \
    && chmod 0444 /opt/starter/bundle/SHA256SUMS /opt/starter/bundle/review.sqlite \
        /opt/starter/bundle/review.sqlite.runs/1/checkpoint.json
USER 10001:10001
RUN cd /opt/starter/bundle && cmp SHA256SUMS /app/deployment/starter.sha256 && sha256sum -c /app/deployment/starter.sha256

EXPOSE 8787
ENTRYPOINT ["python", "/app/deployment/bootstrap.py"]
CMD ["/usr/local/bin/reviewapp", "-addr", "0.0.0.0:8787", "-db", "/data/review.sqlite", "-web", "/app/web/dist", "-python", "/usr/local/bin/python", "-worker", "/app/python/multiscale_worker.py"]
