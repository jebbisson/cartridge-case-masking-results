# Grouped development evaluation

[Back to training data and evaluation](../README.md)

## Run locally

From the repository root, use the workbench's pinned Python 3.14 environment with [`python/requirements.txt`](../../python/requirements.txt) installed. The runner calls the production [`multiscale_worker.py`](../../python/multiscale_worker.py) CLI for both fitting and prediction. It does not need the Go app, a pre-trained checkpoint, or a network connection.

```sh
mkdir -p .local/evaluation
python -B training/evaluation/grouped_cv.py \
  --manifest training/dataset/train.jsonl --folds 3 --seed 413 \
  > .local/evaluation/grouped-cv.json
```

The train-only manifest, fold count, and seed above are the defaults. The full `training/dataset/manifest.jsonl` is an inventory of all 48 cases and is deliberately rejected as mixed input; do not use it for fitting or grouped development evaluation. Use `--manifest` to supply another approved train-only export. The runner prints progress to stderr and emits one aggregate JSON report to stdout on success. It keeps fold manifests, staged fitting assets, freshly trained checkpoints, and predictions in temporary directories that it removes on exit. It does not write back to the dataset or emit per-case scores or fold assignments. Keep saved reports local unless cleared for sharing.

For asset-free bookkeeping and metric tests:

```sh
python -B -m unittest discover -s training/evaluation -v
```

## Manifest contract

Use UTF-8 JSONL, one object per approved train scan. Keep the manifest and the assets it names frozen for the duration of the run.

| Field | Meaning |
| --- | --- |
| `id` | A unique, nonempty opaque scan ID. |
| `group_id` | A nonempty opaque ID for the known source group. Use the same ID for related specimens or alternate scans when they share a source; do not infer groups from filenames. Keep this identifier stable to reproduce folds. |
| `split` | Must be `train` on every row. A mixed manifest is rejected before any asset is opened. |
| `image` | Path to the native single-frame PNG, relative to the manifest directory. |
| `width`, `height` | Native pixel dimensions as positive integers. The worker's `width_px` and `height_px` aliases are also accepted. |
| `labels` | Object keyed by target. A reviewed `present` mask supplies `status: "present"` and `mask` (a relative path to a nonempty native-size binary grayscale PNG, with foreground 255 and background 0). A reviewed `absent` entry supplies `status: "absent"` and no `mask`. Missing targets, `indeterminate`, `not_annotated`, and labels marked with `origin: "proposal"` or `"prediction"` are unscored. An optional arrow entry is ignored. |

Paths use forward slashes; absolute paths, parent traversal, and symlinks escaping the manifest directory are rejected. Use sanitized relative names and opaque IDs, not internal paths, source identifiers, or review database records. The runner checks for identical decoded grayscale inputs across different groups. That catches exact duplicates even when their PNG encodings differ; it does not detect near-duplicates or verify source provenance. Resolve those before running.

## How the folds work

The protocol preserves the three-fold grouped development design without reusing the historical fold membership. Whole groups are sorted by decreasing scan count, then by decreasing number of reviewed exterior-scrape positives. Ties are ordered by the SHA-256 of `seed:group_id`. The runner assigns each group to the fold with the fewest scans, breaking ties by the fewest such positives and then by fold number. Manifest row order does not affect this assignment, but changing IDs, labels used for balancing, seed, or group membership can change the run. Reproduce a run with the same frozen manifest and assets, code revision, Python environment, seed, and fold count. The report records the manifest digest, software versions, and fold counts.

For each fold the worker receives only the fitting complement and that fold's model sees each reserved scan only at prediction. The evaluator checks that the checkpoint names only fitting cases as contributors, and scores the production proposal against the reserved reference at native resolution. Every input scan contributes to exactly one scoring fold. Reviewed support can vary by target; a target lacking usable fitting pixels in a fold may be unlearned and abstain. If the worker cannot fit any mask on a complement, the run fails rather than silently dropping the fold.

## Read the report

Scores are calculated per mask and scan, then pooled across the reserved predictions. Each reviewed-present scan has equal weight; large pixel regions and larger scans are not given more weight. Groups with more scans can still carry more weight. The report includes the reviewed-present, reviewed-absent, and unscored counts for each target.

- **IoU (intersection over union):** pixels in both masks divided by pixels in either mask. Median IoU is the middle score. **p10 IoU** is the linearly interpolated 10th percentile and describes the low end of the overlap distribution. It can be unstable on small cohorts.
- **Pixel precision** is the share of predicted mask pixels inside the reference; **pixel recall** is the share of reference pixels recovered. The report averages each across reviewed-present scans, not across pixels.
- **Abstention** means the worker emitted no mask, not that it verified absence. A missing prediction on a reviewed-present mask is a miss: IoU and recall are zero, and the report assigns zero precision by convention rather than dropping the scan. Emissions on reviewed-absent scans count separately as false positives. Emissions on unknown references are counted but not treated as false positives. Overlap scores are `null` if there are no reviewed-present scans for that target.

Use these numbers to compare development runs with the same cohort, folds, and scoring rules. A high median can coexist with a poor p10 or frequent abstention. None of these measures scores drag-direction arrows, establishes performance on an official test set, or replaces independent forensic review.
