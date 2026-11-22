# Python estimator

[Back to the workbench README](../README.md#documentation)

[`python/multiscale_worker.py`](multiscale_worker.py) is the entry point for local CPU training and prediction. [`multiscale_training.py`](multiscale_training.py) handles snapshot sampling and fitting; [`multiscale_inference_v1.py`](multiscale_inference_v1.py) defines the versioned features and cleanup. See the [Python worker diagram](../docs/architecture.md#python-worker-flow). The first-run target is the same fitted, mask-only Run #3 baseline, subject to [starter clearance](../starter/README.md); fitting another model produces a new run, not Run #3.

## What the worker does

1. Go exports a fingerprinted snapshot of eligible, included training cases with approved revisions. The worker uses confirmed present and absent mask labels; unknown or indeterminate labels are not negatives. Arrows are not training targets. A tiny positive mask that disappears on the bounded fitting grid is skipped and recorded, not relabeled absent.
2. The baseline extracts position, intensity, and local texture features on a reduced grayscale grid. It uses [Pillow resampling](https://pillow.readthedocs.io/en/stable/handbook/concepts.html#filters), [NumPy gradients](https://numpy.org/doc/stable/reference/generated/numpy.gradient.html), and [SciPy Gaussian filtering](https://docs.scipy.org/doc/scipy/reference/generated/scipy.ndimage.gaussian_filter.html) at several scales. The fitting code trains one [scikit-learn histogram gradient-boosted classifier](https://scikit-learn.org/stable/modules/generated/sklearn.ensemble.HistGradientBoostingClassifier.html) per learnable region, with a spatial prior derived from the training masks.
3. Prediction smooths per-region probabilities, adjusts the threshold using the learned prior, and removes small components using [SciPy connected-component labeling](https://docs.scipy.org/doc/scipy/reference/generated/scipy.ndimage.label.html). It resizes binary layers back to native scan dimensions and writes them with a proposal JSON. A missing mask is not a verified absence; applying a prediction leaves any unpredicted target alone, including the arrow.

That is the workbench's own multiscale baseline built with library APIs, not a port of a published cartridge-case segmentation model. Thin marks can be missed or drift on new source groups. The presence of a mask layer in the editor does not imply that the starter checkpoint can estimate it reliably. Estimates are suggestions for review, not forensic findings.

GPT helped draft annotations during data preparation. Run #3 was fitted locally on approved revisions containing both local annotations and retained or adapted Dundee masks. Neither training nor prediction in the app calls GPT. The [starter guide](../starter/README.md#how-the-training-masks-were-made) distinguishes those sources from the model's predictions.

## Go-to-worker interface

The container uses pinned Python 3.14 and pinned numerical and imaging dependencies. The UI normally calls the worker through Go. For inspection of the interface, the commands below use placeholders for a trusted workbench snapshot and run metadata, not bundled example files:

```sh
python python/multiscale_worker.py train --manifest "$SNAPSHOT" --out "$CHECKPOINT"
python python/multiscale_worker.py predict --model "$CHECKPOINT" --image "$SCAN_PNG" --out "$PROPOSAL_DIR" --expected-model-sha256 "$TRUSTED_MODEL_SHA256"
```

`train` writes a versioned checkpoint from the snapshot manifest and its referenced assets. `predict` writes `proposal.json` and any resulting mask PNGs under the output directory. Go supplies the expected digest in `REVIEWAPP_MODEL_SHA256`; an offline caller should use a digest from trusted run metadata. The checkpoint contains [joblib](https://joblib.readthedocs.io/en/stable/generated/joblib.load.html)-serialized models: **never load an untrusted checkpoint**. A digest checks identity against a trusted record; computing a digest from an unknown file does not make it safe.

## Prior work consulted, not incorporated

- [Mookiah et al. (2025)](https://doi.org/10.1016/j.forsciint.2025.112554) and the [LRCFS segmentation repository](https://github.com/LRCFS/Cartridge-Case-Segmentation) were consulted for breech-face and firing-pin segmentation. The baseline does not incorporate their neural-network code, weights, or benchmark predictions. The separately licensed Dundee **reference masks** are credited where they are used in the [starter data guide](../starter/README.md).
- [Tai and Eddy's `cartridges`](https://github.com/xhtai/cartridges) was consulted for its primer-region preprocessing; its R implementation is not used. [Duong et al.](https://espace2.etsmtl.ca/id/eprint/27282/) was consulted for learned region detection, not for training data or a model. [Chan's SegFormer work](https://github.com/issacchan26/CartridgeCaseSegmentation) and the [associated label dataset](https://huggingface.co/datasets/issacchan26/gray_bullet) were reviewed for label coverage, not incorporated. The drag pixels in that dataset are not ordered endpoints.

These citations credit previous work. The original workbench code is [MIT-licensed](../LICENSE); the Dundee data keeps its separate [CC BY 4.0 attribution](../starter/README.md#dundee-mask-attribution).
