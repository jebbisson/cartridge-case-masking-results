# Deployment

## Host setup

| Target host | Requirements |
| --- | --- |
| Windows x86-64 | [Docker Desktop for Windows](https://docs.docker.com/desktop/setup/install/windows-install/) with WSL 2, hardware virtualization, and **Linux containers** selected. Follow Docker's current Windows and WSL requirements. |
| Linux x86-64 | [Docker Engine](https://docs.docker.com/engine/install/) and the [Compose plugin](https://docs.docker.com/compose/install/linux/). |

Use Docker Compose 2.17 or later with a local builder that supports named build contexts. The app uses one Linux x86-64 container, a pinned Python 3.14 runtime, and CPU inference. No GPU runtime, CUDA, API keys, host Python, Go, or Node are needed to run it. The first build needs access to base images and package downloads. The intended platforms are not a compatibility claim until the build has passed on both.

## Start and stop

Put the verified starter bundle at `starter/full-bundle/`. Its database, fitted checkpoint, and `SHA256SUMS` are checked against the repository's independent pins at build time. The image includes those files and their attribution; it does not include the separate training export. The current bundle and image are for local use only while redistribution rights are reviewed. Run from the repository root:

```sh
docker compose up --build -d
```

Open [http://localhost:8787/](http://localhost:8787/) (or `http://127.0.0.1:8787/`). The port is intended to be published on host loopback only. This single-user app has no login; do not expose it to a LAN or the internet. The [system diagram](architecture.md#system-overview) shows the storage and process boundaries.

A fresh volume is seeded once with 30 approved cases and the fitted Run #3 mask model, displayed as Run #1 in a fresh workspace. Open a case and select **Run new estimate**; no host data mount or retraining is needed. If a build or startup fails, check the logs and verify the bundle. Do not substitute a research database or refit a checkpoint and call it Run #3.

```sh
docker compose ps
docker compose logs --tail=100
```

Check that Docker is running and that port 8787 is not already occupied if the app does not open. On Windows, verify Docker Desktop is using the WSL 2 backend and Linux containers.

## Workspace and backups

A Docker-managed named volume mounted at `/data` holds workspace files, including SQLite and its sidecars and the run directories with snapshots and checkpoints. Do not put the SQLite workspace on a Windows host bind mount. Use `docker compose down` to stop; the named volume survives ordinary shutdown and container rebuilds. **`docker compose down -v` deletes the workspace volume.**

An image upgrade does not replace an existing workspace, its cases, or its trained models. To load the new starter on the same port without deleting the original volume, use the [README reload command](../README.md#reload-docker-with-the-new-starter-data). The first launch with a new volume name copies the current starter into it; subsequent launches with that name preserve its edits. Use a name that does not already exist if you need to load a newer seed from scratch.

In PowerShell, set the volume name before starting:

```powershell
$env:REVIEWAPP_WORKSPACE_VOLUME = 'cartridge-case-workbench-run3'
docker compose up --build --force-recreate --wait
```

To switch back to the original workspace, omit `REVIEWAPP_WORKSPACE_VOLUME` and run `docker compose up -d`. If the variable is set for your shell, clear it first (`unset REVIEWAPP_WORKSPACE_VOLUME` in a POSIX shell, or `Remove-Item Env:REVIEWAPP_WORKSPACE_VOLUME` in PowerShell). Switching volumes does not merge case histories; neither volume is deleted.

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
