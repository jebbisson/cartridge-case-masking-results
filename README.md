# Cartridge Case Masking Workbench

A local browser workbench for reviewing pixel masks on fired cartridge-case microscopy PNGs. Compare an estimate with the original scan, correct masks at native resolution, and save revisions without changing the original. The CPU estimator uses the Run #3 mask-only baseline. Drag-direction arrows can be edited by hand; the estimator does not create or change them.

**Release status:** Research/development release with 48 real scans and the fitted baseline. Scan images follow NIST's published data reuse terms; annotations and the checkpoint have separate attribution and licensing in [Data, annotation, and model terms](docs/data-licenses.md). Annotation quality remains under review. This is a review aid, not a validated forensic tool or a published benchmark.

## Methodology

1. **Prepare real scans and annotations.** The current training snapshot contains 30 NIST 9×19 mm (9 mm Luger) reflectance-microscopy scans across 15 source groups. We matched Dundee reference masks to the scan and view, aligned them to native dimensions, and combined retained or adapted masks with GPT-assisted drafts and subsequent workbench review. The original scan pixels are preserved; annotations are separate native-resolution binary layers and ordered arrow endpoints. See [data sources and annotation preparation](starter/README.md#how-the-training-masks-were-made).
2. **Freeze reviewed training inputs.** The Go app stores images, revision history, and explicit approvals in SQLite. Fitting uses a versioned snapshot of included training cases and eligible approved labels, not the latest unsaved edits or held-out cases. Saving a draft, approving it, and retraining are separate actions.
3. **Fit a local CPU baseline.** On a reduced grayscale grid, we extract position, intensity, and multiscale texture features. A histogram gradient-boosted classifier is fitted separately for each learnable mask region, with a spatial prior derived from training masks. Prediction smooths probabilities, thresholds them using that prior, removes small components, and resizes the binary masks to native dimensions. This is our own baseline built with standard Python libraries, not a pretrained cartridge-case neural network. See [estimator details](python/README.md#what-the-worker-does).
4. **Review predictions without overwriting annotations.** The bundled checkpoint is the fitted Run #3 artifact, displayed as Run #1 in a fresh workspace. **Run new estimate** creates an unsaved mask preview; it does not retrain or replace saved revisions. GPT was used during annotation preparation, not during local fitting or inference. Drag-direction arrows are manually editable but are not predicted by this model.

## Assumptions and edge cases

- **Scope:** The present cohort is 9×19 mm reflectance microscopy, not mixed-caliber photographs or 3D surface scans. Other calibers, lighting, orientations, fields of view, and instruments are outside the established scope; position features and spatial priors can fail when framing changes.
- **Target meanings:** Four regions are learned: breech-face impression, aperture shear, the center pocket (`firing_pin_shear`), and the exterior scrape (`firing_pin_impression`). These last two names follow this project's label convention; a pocket-internal rim is not an exterior scrape. Drag direction is a separate ordered tail-to-tip annotation, not a fifth mask.
- **Unknown is not absent:** `absent`, `indeterminate`, and `not_annotated` are distinct. Unknown labels are excluded from fitting rather than used as negatives. If no mask is emitted, that is an abstention, not verified absence; the editor preserves unpredicted targets when applying an estimate.
- **Small and ambiguous marks:** Downsampling and component cleanup can miss thin or tiny marks, and boundaries can overfill or drift. A reviewed positive that disappears on the fitting grid is skipped and recorded, not relabeled absent. Shadows, rims, and unclear scrape or arrow geometry need further review rather than a forced positive label.
- **Data quality remains under review:** The frozen labels include reviewed AI-assisted and adapted reference annotations, not an independently established forensic ground truth. Workbench approval records a workflow decision, not expert certification. Correcting a draft alone does not update the fitted checkpoint; corrected supervision must be approved and a new run fitted before predictions can reflect it.
- **Verification is not accuracy:** Checksum checks, restarts, and matching predictions verify packaging and software behavior. Estimates on the bundled training scans do not establish generalization. The [grouped development evaluator](training/evaluation/README.md) refits on separate source-group complements and scores reserved groups; this is development evaluation, not an independent test-set or forensic-validation claim.

## Start with Docker

The intended hosts are **Windows x86-64** with [Docker Desktop in Linux-container mode using WSL 2](https://docs.docker.com/desktop/features/wsl/) and **Linux x86-64** with [Docker Engine](https://docs.docker.com/engine/install/) and the Compose plugin. No GPU or host Python is required; the container uses a pinned Python 3.14 runtime.

**Windows:** Follow the [Windows setup and acceptance test](docs/windows.md) for the test branch, PowerShell checks, and safe workspace handling. Compose builds the same `linux/amd64` image on both hosts; this is not a native Windows build. Windows Docker Desktop validation is awaiting the user-machine test, and this repository does not yet have automated CI.

With the verified starter bundle at `starter/full-bundle/`, run this from the repository root using a local Docker builder:

```sh
docker compose up --build -d
```

Open [localhost:8787](http://localhost:8787/). A fresh workspace has all 48 real cohort scans (30 train, 6 validation, 12 test), with only the 30 training cases approved and included, and the unchanged fitted Run #3 model, so **Run new estimate** works without retraining. The estimate is an unsaved preview until you save or approve it. An existing workspace is preserved on upgrade.

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

## Sample outputs — deferred

Side-by-side original scans and generated masks are intentionally deferred while annotation quality is improved. No sample-output images are bundled yet, so that deliverable remains outstanding. When added, figures must distinguish model predictions from saved training labels, identify whether the scan was used for fitting, and preserve the same crop and scale with the required source credits. No accuracy claim is inferred from a demonstration image.

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

The original workbench software is licensed under [MIT](LICENSE). Third-party dependencies keep their own licenses. The scan images follow NIST's published reuse terms; local annotation contributions and the fitted checkpoint are distributed under CC BY 4.0 with Dundee source credit. MIT does not replace these asset-specific terms. See [Data, annotation, and model terms](docs/data-licenses.md) for permissions, required notices, and the release-review limits.

The training annotations combine locally reviewed GPT-assisted drafts with retained or edited University of Dundee masks. Dundee's masks are credited under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/), including where we resized or edited them. See the [starter data guide](starter/README.md#dundee-mask-attribution) for the full citation, changes, and separate terms for the other assets.
