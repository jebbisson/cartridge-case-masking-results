# Deployment

## Host setup

| Target host | Requirements |
| --- | --- |
| Windows x86-64 | [Docker Desktop for Windows](https://docs.docker.com/desktop/setup/install/windows-install/) with WSL 2, hardware virtualization, and **Linux containers** selected. Follow Docker's current Windows and WSL requirements. |
| Linux x86-64 | [Docker Engine](https://docs.docker.com/engine/install/) and the [Compose plugin](https://docs.docker.com/compose/install/linux/). |

The intended deployment uses one Linux x86-64 app container, a pinned Python 3.14 runtime, and CPU inference. No GPU runtime, CUDA, API keys, host Python, Go, or Node are needed for Compose. The first build needs access to base images and package downloads. Do not treat these target hosts as a compatibility claim until the final candidate has passed on both.

## Start and stop

Once the Compose setup and starter bundle are cleared and available, run from the repository root:

```sh
docker compose up --build -d
```

Open [http://localhost:8787/](http://localhost:8787/) (or `http://127.0.0.1:8787/`). The port is intended to be published on host loopback only. This single-user app has no login; do not expose it to a LAN or the internet. The [system diagram](architecture.md#system-overview) shows the storage and process boundaries.

A fresh seeded workspace should show real starter cases and offer **Run new estimate** with Run #3 before any fitting. Compose mounts `starter/` read-only. On a fresh volume, startup expects the verified bundle under `starter/bundle/` and stops if it is missing or fails its checksum checks. An existing workspace is not reseeded. If startup fails or the starter model is unavailable, check the logs and release status. Do not substitute a local research database or refit a checkpoint and call it Run #3.

```sh
docker compose ps
docker compose logs --tail=100
```

Check that Docker is running and that port 8787 is not already occupied if the app does not open. On Windows, verify Docker Desktop is using the WSL 2 backend and Linux containers.

## Workspace and backups

A Docker-managed named volume mounted at `/data` holds workspace files, including SQLite and its sidecars and the run directories with snapshots and checkpoints. Do not put the SQLite workspace on a Windows host bind mount. Use `docker compose down` to stop; the named volume survives ordinary shutdown and container rebuilds. **`docker compose down -v` deletes the workspace volume.**

Stop the app before backing up the full `/data` volume. Restore into a separate volume with the app stopped, then check that cases, revisions, and a compatible model reopen together. Do not copy just the SQLite file from a running workspace: recent changes may still be in its write-ahead log, and checkpoints are separate files. Keep backups private; they contain the scans and review history.

## Native development

This is a separate dev launch, not the seeded install. Use Linux, Go 1.24.4 or compatible newer, a C compiler for CGO SQLite, Node 20.19.2 or newer, and Python 3.14 in a virtual environment. From the repository root:

```sh
python3.14 -m venv .venv
.venv/bin/python -m pip install -r python/requirements.txt
npm --prefix web ci
npm --prefix web run build
CGO_ENABLED=1 go run ./cmd/reviewapp \
  -db .local-dev/review.sqlite \
  -python "$PWD/.venv/bin/python" \
  -worker python/multiscale_worker.py
```

Use a disposable development database rather than your Compose workspace or a live review database. The command does not install the starter. For Vite hot reload, see the [frontend development instructions](../web/README.md#frontend-development).
