# Training data and evaluation

[Workbench README](../README.md) · [Python estimator](../python/README.md) · [Grouped evaluation protocol](evaluation/README.md)

This section documents how to fit and evaluate the workbench's mask estimator on approved training data. It is separate from the [starter cases](../starter/README.md), which are for trying the editor and the fitted baseline. The curated package provides the full real cohort inventory and a separate frozen train-only export; the project validation/test labels are unapproved source references or proposals, not official benchmark ground truth.

## Local training data

Use a frozen export of real scans and approved revisions. The evaluator defaults to `training/dataset/train.jsonl`, the exact unchanged 30-row frozen approved fitting export. `training/dataset/manifest.jsonl` is the full 48-row inventory (30 train / 6 validation / 12 test) and is intentionally rejected as mixed input. The evaluator can read a train-only manifest elsewhere. The [manifest contract](evaluation/README.md#manifest-contract) describes the required fields. The approval decision comes from the export process, not from the evaluator. Do not relabel a draft or a held-out case as `train` to make it pass.

The [local Run #3 candidate](ATTRIBUTION.md#local-verification) contains all 48 scans across 24 source groups, including the same 30 approved training scans across 15 source groups. The 18 non-training cases remain excluded and unapproved; no indeterminate or missing label is converted to a negative. Its per-scan attribution, package verification, and redistribution status are in [ATTRIBUTION.md](ATTRIBUTION.md). The curated release includes asset-specific reuse terms and notices; see [Data, annotation, and model terms](../docs/data-licenses.md). The [workbench build](../docs/deployment.md#start-and-stop) includes the fitted Run #3 model without refitting it.

The reference labels combine reviewed local annotations (including GPT-assisted drafts) and retained or adapted Dundee masks. See [data credits and reuse terms](../starter/README.md#dundee-mask-attribution). Training and prediction run locally and do not call GPT. Keep working exports and generated reports out of the curated dataset and starter directories. Retain the separate data/model terms and review any newly added assets before redistribution; the software license does not replace asset-specific terms.

## What is trained and evaluated

The production Python worker fits separate CPU classifiers for the four mask regions: breech face, aperture shear, firing-pin shear (the center pocket), and firing-pin impression (the exterior scrape in this annotation scheme). It trains on reviewed positives and explicit negatives, and skips unknown labels. A positive too small to survive resampling to the fitting grid is skipped, not converted to a negative. The editor supports ordered drag-direction arrows, but the estimator neither fits nor predicts them. Any offline arrow experiment is separate from the workbench model.

For a local development estimate, run [grouped cross-validation](evaluation/README.md#run-locally). Each fold fits the production worker from scratch on the other approved training groups and scores its native-resolution masks on the reserved training groups. These are new fits, not a rerun of the original fitted Run #3 checkpoint. The development folds are not an official split.

Software parity asks whether the same fitted checkpoint on the same inputs produces the same masks and abstentions. Grouped evaluation asks how newly fitted models perform on groups excluded from their own fitting data. Neither software parity nor reuse of the training cohort for development establishes performance on independent acquisition sources or validates forensic use. A generalization claim would need a separately frozen, independently reviewed test cohort that was never used for fitting or tuning.
