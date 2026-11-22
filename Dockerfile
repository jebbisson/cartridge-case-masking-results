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
COPY python/*.py /app/python/
COPY deployment/bootstrap.py /app/deployment/bootstrap.py
COPY deployment/starter.sha256 /app/deployment/starter.sha256
USER 10001:10001
EXPOSE 8787
ENTRYPOINT ["python", "/app/deployment/bootstrap.py"]
CMD ["/usr/local/bin/reviewapp", "-addr", "0.0.0.0:8787", "-db", "/data/review.sqlite", "-web", "/app/web/dist", "-python", "/usr/local/bin/python", "-worker", "/app/python/multiscale_worker.py"]
