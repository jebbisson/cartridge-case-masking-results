# Cartridge Case Masking Workbench

A local browser workbench for reviewing pixel masks on fired cartridge-case microscopy PNGs. Compare an estimate with the original scan, correct masks at native resolution, and save revisions without changing the original. The CPU estimator uses the Run #3 mask-only baseline. Drag-direction arrows can be edited by hand; the estimator does not create or change them.

**Release status:** Local working-tree review only. The starter bundle is not cleared for redistribution. This is a review aid, not a validated forensic tool or a published benchmark.

## Start with Docker

The intended hosts are **Windows x86-64** with [Docker Desktop in Linux-container mode using WSL 2](https://docs.docker.com/desktop/features/wsl/) and **Linux x86-64** with [Docker Engine](https://docs.docker.com/engine/install/) and the Compose plugin. No GPU or host Python is required; the container uses a pinned Python 3.14 runtime.

With the verified starter bundle at `starter/full-bundle/`, run this from the repository root using a local Docker builder:

```sh
docker compose up --build -d
```

Open [localhost:8787](http://localhost:8787/). A fresh workspace has 30 approved cases and the fitted Run #3 model, so **Run new estimate** works without retraining. The estimate is an unsaved preview until you save or approve it. An existing workspace is preserved on upgrade.

Stop with `docker compose down`. The named volume mounted at `/data` keeps your work; do not add `-v` unless you intend to delete it.

### Data reset

**A data reset permanently deletes the selected workspace volume**, including imported cases, saved edits, revision history, and training runs. Back up anything you want to keep. A normal restart or rebuild is not a reset.

From the repository root, using the same Compose project and volume settings you use to start the app, stop the app and remove its volume:

```sh
docker compose down --volumes
```

Once that succeeds, rebuild and start the app:

```sh
docker compose up --build --wait
```

Prefix both commands with `sudo` if your Linux Docker setup requires it. On startup, the app creates a fresh workspace from the bundled starter data. Open [localhost:8787](http://localhost:8787/). See [Workspace and backups](docs/deployment.md#workspace-and-backups) for how to keep the existing volume instead.

## Screenshot slots

- **Original and estimated masks:** Same real scan, crop, and zoom. Suggested alt text: “Original cartridge-case scan beside the same view with estimated mask overlays.”
- **Revision review:** Editor with a saved revision selected for comparison and the unsaved edit controls visible. Suggested alt text: “Revision comparison in the mask editor, with Cancel edits and Save draft controls.”

No screenshots are bundled. Use only cleared real scans and overlays for these slots.

## Documentation

| Component README | What it covers |
| --- | --- |
| [Browser editor](web/README.md) | How to preview estimates, edit masks and arrows, compare revisions, and save or approve changes. Also covers local React development and testing. |
| [Python estimator](python/README.md) | How the CPU model trains and predicts masks, how Go calls the Python worker, and which prior work informed the method. |
| [Training data and evaluation](training/README.md) | The approved training snapshot, data sources, and how to reproduce the grouped model tests. |
| [Starter cases and data credits](starter/README.md) | Which scans, annotations, and model are used for a fresh workspace, where they came from, and what can be redistributed. |

- [System architecture](docs/architecture.md#system-overview) — Mermaid diagrams showing how the browser, Go API, Python worker, and workspace fit together.
- [Deployment](docs/deployment.md) — Docker setup, upgrades, troubleshooting, and managing the persistent workspace.

## License and data credits

The original workbench software is licensed under [MIT](LICENSE). Third-party dependencies keep their own licenses. MIT does not cover the starter scans, annotations, or fitted checkpoint.

The training annotations combine locally reviewed GPT-assisted drafts with retained or edited University of Dundee masks. Dundee's masks are credited under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/), including where we resized or edited them. See the [starter data guide](starter/README.md#dundee-mask-attribution) for the full citation, changes, and separate terms for the other assets.
