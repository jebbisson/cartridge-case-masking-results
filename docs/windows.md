# Windows setup and acceptance test

[Workbench README](../README.md) · [Deployment and persistent storage](deployment.md)

## What runs where

The supported Windows path is **Windows x86-64 + Docker Desktop + WSL 2 + Linux containers**. Compose explicitly targets `linux/amd64` on either host. PowerShell asks Docker to build the same Linux image as on Linux; Python, Go, SQLite, and file locking run inside that image. Native Windows Python/Go execution is not the supported launch path. No host Python, Node, Go, GPU, or API key is needed.

Install [Docker Desktop for Windows](https://docs.docker.com/desktop/setup/install/windows-install/) and meet its current Windows/virtualization requirements. Use its [WSL 2 backend](https://docs.docker.com/desktop/features/wsl/) and Linux containers. Start Docker Desktop before launching. Windows ARM and Windows Server/Docker Desktop are outside this tested target.

This branch adds Git checkout protections for exact-byte manifests, model files, scan images, and SQLite parts. Do not rewrite checksum files or regenerate pins to make a Windows failure disappear. The image rebuilds locally; no automated Linux or Windows CI currently certifies this path. The final Windows Docker Desktop run is pending the user's machine test.

## Get a clean copy of the test branch

A new folder avoids stale CRLF-converted files in an older checkout and leaves existing work intact. In PowerShell:

```powershell
git clone --branch fix/windows-compatibility https://github.com/jebbisson/cartridge-case-masking-results.git cartridge-case-masking-windows-test
cd cartridge-case-masking-windows-test
docker info --format '{{.OSType}}/{{.Architecture}}'
docker compose version
```

Docker must report a **Linux** daemon. `x86_64` and `amd64` are the expected architecture spellings. If it reports `windows`, switch Docker Desktop to Linux containers. If the daemon cannot be contacted, finish Docker Desktop/WSL setup first. Compose 2.17+ and a builder supporting additional/named contexts are required; use a current Docker Desktop installation.

Use a local, writable folder rather than an online-only/cloud-synchronized directory or network share. The repository contains large binary seed parts. The `starter/full-bundle` directory must contain all three parts and their catalogs; Git LFS is not required.

## Build and open the app

Run the original launch command:

```powershell
docker compose up --build -d
```

Wait until Docker reports the app as healthy:

```powershell
docker compose ps
docker compose logs --tail=100 workbench
```

Open **http://localhost:8787/**. A fresh workspace contains **48 cases: 30 train, 6 validation, 12 test**, and an installed fitted model shown as Run #1. No training is needed. The exercise scan must not appear.

If another app already uses port 8787, do not delete its data. Stop that app from its original Compose folder, or choose a different host port for this test:

```powershell
$env:REVIEWAPP_PORT = '8790'
docker compose up --build -d
```

Then use http://localhost:8790/ and pass `-BaseUrl http://127.0.0.1:8790/` to the checker below.

## Run the acceptance checker

Review [`deployment/Test-Windows.ps1`](../deployment/Test-Windows.ps1), then run it from the repository root. The process-only execution policy below does not alter the machine's saved execution policy. Organization policy may still forbid unsigned scripts; do not bypass your organization's controls.

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\deployment\Test-Windows.ps1
```

PowerShell 7 users can use `pwsh` in place of `powershell`. The checker works against a **fresh, unmodified starter**. It requests the app shell, all 48 case details, the frozen training preview, and unsaved estimates for one train, validation, and test case. It checks native PNG dimensions, 30 unchanged training members, excluded/unapproved holdouts, the installed run, and unchanged saved records. It does not save, approve, retrain, reset, stop, or start anything.

The result is JSON with `cases: 48`, `training_total: 30`, `training_unchanged: 30`, three estimate entries, and `saved_state_unchanged: true`. A thrown error is a failure, not a successful test. A preserved older/custom workspace may legitimately fail the fresh-starter assertions; that alone is not a Windows bug.

### Confirm restart persistence

Before editing the fresh test workspace, save a report, restart, wait for readiness, and run it again:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\deployment\Test-Windows.ps1 | Set-Content -Encoding utf8 windows-before.json
docker compose restart workbench
docker compose up -d --wait
powershell -NoProfile -ExecutionPolicy Bypass -File .\deployment\Test-Windows.ps1 | Set-Content -Encoding utf8 windows-after.json

$before = Get-Content -Raw windows-before.json | ConvertFrom-Json
$after = Get-Content -Raw windows-after.json | ConvertFrom-Json
if (-not $before.saved_state_unchanged -or -not $after.saved_state_unchanged) { throw 'Acceptance report missing or failed.' }
if ($before.saved_state_sha256 -ne $after.saved_state_sha256) { throw 'Saved state changed after restart.' }
if (($before.estimates | ConvertTo-Json -Depth 10 -Compress) -ne ($after.estimates | ConvertTo-Json -Depth 10 -Compress)) { throw 'Predictions changed after restart.' }
```

The report files are local test receipts, not files to commit. In the browser, also check that a scan actually renders, original/overlay switching works, zoom/pan remain usable, and a draft edit can be saved and reopened **in this disposable test workspace**. The automated checker validates the API, not browser rendering. It does not assess annotation accuracy.

## Protect existing work

Docker stores `/data` in a managed Linux named volume, not a Windows SQLite bind mount. Ordinary rebuilds and `docker compose down` preserve it. The default volume name depends on the Compose project/folder name; cloning the renamed repository into a new folder can select a different volume without deleting the old one. Use the same project and `REVIEWAPP_WORKSPACE_VOLUME` settings to reopen an older workspace. Do not assume an apparently empty/new app means your old data was erased.

To choose another unused test volume without deleting the existing one:

```powershell
$env:REVIEWAPP_WORKSPACE_VOLUME = 'workbench-windows-test-fresh'
docker compose up --build -d
```

That name is only fresh the first time it is used. Reusing it preserves its state. To stop this test, use `docker compose down` with the same project/settings. **Do not add `--volumes` or `-v`** unless you explicitly want permanent deletion. Do not use `docker volume prune` for this test.

## If the test fails

Keep the exact error and collect:

```powershell
git rev-parse HEAD
git status --short
docker version
docker compose version
docker info --format '{{.OSType}}/{{.Architecture}}'
docker compose ps
docker compose logs --tail=100 workbench
```

Share the failing build step, checker error, and relevant logs, after reviewing them for private paths or data. Do not send API keys, credentials, the workspace database, or a full Docker diagnostic bundle. A checksum mismatch is useful evidence: retain the original file and error rather than editing the expected hash.
