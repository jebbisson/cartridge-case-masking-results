# Multi-caliber pilot: findings and recommended approach

**Status:** Exploratory development experiment, 25 November 2026 (US Eastern). New scans, source masks, predictions and experimental scripts remain private. This report does not expand the bundled dataset or replace its fitted model. It is not forensic validation.

## Decision

**Keep one segmentation workflow. Record verified caliber as metadata and, when useful, a queue filter—not a required manual model selector. Prefer a shared mixed-caliber model as the next training experiment, once compatible labels and sufficiently independent source groups exist.**

Do **not** add automatic caliber identification or split the small dataset into caliber specialists yet. The existing image-based model can execute on the additional caliber without a caliber input, but execution is not proof of acceptable four-region segmentation. Keep the released checkpoint's established scope at 9×19 mm until independent review supports a broader claim.

This is a probable-best engineering direction, **not a measured win by a newly trained pooled model**. No pooled, metadata-conditioned or caliber-specialist model was fitted in this pilot.

## 1. Data actually gathered

NIST provides reflectance images and surface-topography data; only compatible reflectance PNGs were accepted here.[1] The additional cohort came from the Lightstone S&W Sigma study.[5]

| Cohort | Scans | Provenance groups | Role |
|---|---:|---:|---|
| Existing 9×19 mm controls | 6 | 3, from Fadul, PopStat Glock and PopStat Sig Sauer | Training-only pipeline controls; already exposed to the checkpoint, not independent performance evidence |
| Additional .40 S&W pilot | 6 | 3 distinct slides, two different cartridge specimens each | New-caliber exploratory inference; no training or adaptation |

All six additional originals are grayscale **2592 × 1944 PNGs**, with catalog metadata for **ring-light reflectance microscopy, Leica FS M, 2× objective and 2.53 µm nominal sampling**. Encoded-file and dimension-bound decoded-RGB comparisons found no exact overlap or shared source-group IDs with the existing 48-scan 9 mm inventory. These are integrity checks, not proof against every possible near-duplicate.

**Exact caliber was checked rather than guessed.** The raw firearm and specimen fields say `40/10 mm`. Those fields were preserved. The exact `.40 S&W` designation was resolved separately using the catalog-linked Lightstone publication's explicit Sigma Series 40 S&W and ammunition descriptions.[4][5]

**The groups are not three independently sampled complete firearms.** The source study used consecutively manufactured slides with one shared frame. This pilot is a subset of that single study, so caliber, weapon family, manufacturing history and acquisition are entangled.[4] The paper/catalog primer-material discrepancy—nickel versus `Brass`—was retained rather than silently reconciled.

A second additional exact caliber was not accepted: the inspected `45 Auto` searches returned no catalog studies, inspected Colt records had firearm/specimen caliber contradictions, and a Kong candidate remained only `38/357`. These are bounded search/metadata observations, not claims that usable .45 or .38 scans do not exist elsewhere. Contradictory or unresolved candidates were excluded.

## 2. What was run

The frozen public checkpoint was used unchanged with the production feature extraction and native-resolution mask export. The model did not receive a caliber label. The original 9 mm training snapshot, held-out memberships, live revision heads, approvals and model runs were preserved.

Three output variants were examined on the same real images:

| Variant | Actual operation | What it is not |
|---|---|---|
| Frozen production model | Existing classifiers, probability smoothing, spatial-prior-adjusted thresholds and component cleanup | Not mixed-caliber retraining |
| Unguided classifier ablation | Same fitted classifiers and feature grids, raw probability threshold of 0.5, without production guidance/cleanup | **Not position-free:** the classifier still receives position features |
| Image-free prior control | Existing training-mask spatial priors, resized to the feature grid and thresholded at 0.5 | Not a new fitted segmenter or a tuned caliber-specific template |

The ablations are diagnostic controls. Their thresholds were not optimized on the new cohort. See the existing [inference implementation](../../python/multiscale_inference_v1.py) and [worker](../../python/multiscale_worker.py).

### Observed output behavior

| Target | 9 mm controls: masks emitted | .40 S&W pilot: masks emitted |
|---|---:|---:|
| Breech-face impression | 6/6 | 6/6 |
| Center pocket (`firing_pin_shear`) | 6/6 | 6/6 |
| Aperture shear | 5/6 | 1/6 |
| Exterior scrape (`firing_pin_impression`) | 5/6 | 5/6 |
| Automatically predicted drag arrow | 0/6 | 0/6 |

**Emission is neither accuracy nor recall.** Without compatible references, neither a proposed mask nor an abstention establishes presence, absence or correct localization. The arrow predictor is not implemented; arrows remained indeterminate. In particular, the aperture-shear emission difference cannot establish a caliber-caused performance loss.

The .40 S&W production calls completed with a median **0.472 seconds per image**, range **0.439–0.493 seconds**, in the already-running CPU Python process. This excludes interpreter startup, a Docker build and browser/API overhead; it is not a hardware-independent performance promise. Direct production-CLI checks on one real scan from each caliber matched the probe's proposal fields and all native mask pixels.

## 3. Reference coverage and interpretation

Dundee describes breech-face, firing-pin and combined masks, not separate references for all four project regions or directed arrows.[2] The local archive audit decoded **5,086 binary masks covering 1,703 filename keys**; not every key has every source-mask type. All six new scans had exact filename/view matches to the three source types, giving **18 candidate masks**.

A filename match alone does not establish geometric alignment or label semantics. The source firing-pin mask describes the central pocket candidate; it must **not** be scored against this project's exterior-scrape target merely because an old manifest calls it `firing_pin_impression`. Source references, current project conventions and predictions remain separate.

### Coarse reference agreement: actual measurements

Before overlap scoring, one fixed mapping was declared: full-frame nearest-neighbor resize from 512 × 512 source masks to 2592 × 1944, with no fitted crop, translation or rotation. Visual review of all six originals and source contours found frame-compatible coarse annulus/pocket regions. That supports this limited comparison, not exact forensic boundary truth. Source contours simplify irregular pocket boundaries; their breech-face annulus also includes collar-transition areas excluded by production.

**Each cell is IoU / Dice against the coarse Dundee reference, not five-target accuracy.** Compute each metric on native binary pixels, average within each slide, then equally over the three slides. Each variant/target has six scans in three related slide groups.

| Coarse region | Frozen production | Unguided classifier | Image-free prior at 0.5 |
|---|---:|---:|---:|
| Breech face | 0.694 / 0.819 | 0.695 / 0.820 | 0.511 / 0.676 |
| Center pocket | 0.839 / 0.912 | 0.827 / 0.905 | 0.625 / 0.763 |

Both classifier variants exceeded this fixed image-free prior's IoU on both scored regions in **every slide**. This supports investigating a shared learned segmenter rather than assuming the measured overlaps come entirely from the thresholded prior. It does **not** isolate image-only performance: the classifiers retain position features, and this one control does not exhaust geometry baselines.

Production versus unguided is mixed: slightly lower breech-face agreement and slightly higher pocket agreement. There is no across-target guidance/cleanup winner and no basis here for replacing the released checkpoint. Central-pocket transfer is promising under the coarse-source definition; collar disagreement is not automatically forensic undersegmentation.

**Aperture shear, exterior scrape and directed arrows remain unscored.** Per-input counts, all 36 target/variant comparisons, and per-slide results are in the [machine-readable summary](multi-caliber-pilot-results.json). No confident population interval or causal caliber-effect claim is supported by three related slides from one study.

## 4. Options and probable best direction

| Approach | Evidence/readiness here | Decision |
|---|---|---|
| One frozen image-based model | Actually ran on both cohorts without a caliber input; broad masks were emitted, fine-target correctness remains unestablished | Retain as the unchanged baseline and review aid, not a validated multi-caliber release |
| One shared mixed-caliber model | Not trained; needs compatible reviewed labels and independent groups | **Preferred next training candidate:** pools scarce supervision and preserves one workflow |
| Shared model conditioned on caliber/acquisition metadata | Not trained or compared | Add only if grouped comparisons show a repeatable benefit; metadata entry alone does not create a conditional model |
| Separate caliber specialists | Not trained or compared; the additional cohort has only three related slides from one frame/study | Defer: fragmentation and a required routing decision are not justified by these data |
| Automatic caliber classifier before segmentation | Not trained; exact caliber was obtained from provenance instead | Unnecessary for the original masking task; do not introduce an unvalidated extra failure point |

**Practical UI recommendation:** keep the existing estimate action. A future caliber field should describe source provenance and support filtering, including an explicit unknown/unresolved state. Do not make a caliber dropdown a prerequisite for image-based segmentation. This is a recommendation; no UI or database migration was made.

## 5. What would change this recommendation

First review and harmonize actual boundaries, particularly aperture shear, exterior scrape and directed endpoints. Preserve unknown versus absent. Gather broader independent sources rather than just more near-related slides from this study.

Then compare pooled, metadata-conditioned and specialist fits on identical reserved source groups, with comparable preprocessing, tuning budgets and explicit training-data-size controls. Keep repeated specimens, views and crops from a group together. Group-aware validation matters when observations share sources, and repeatedly choosing methods using a final test set leaks information into the evaluation.[3] Use later independent data for confirmation after this exploratory cohort has informed development.

Report each caliber and target separately, with whole-group paired results and coverage/abstentions. Do not manufacture a five-target accuracy score from coarse references or convert a large number of pixels into a large number of independent firearm samples. None of the current evidence establishes a superior pooled/conditional/specialist fit or forensic reliability.

## 6. Reviewable results and preservation boundary

The accompanying [machine-readable summary](multi-caliber-pilot-results.json) records per-input behavior and diagnostic measurements without redistributing source images, masks, models, private workspace history or local paths. The method and source cohort are described above; this is a reviewable research summary, not a standalone downloadable benchmark.

The frozen checkpoint SHA-256 is `a4056cde70e06dc75314ca295f9dafa58e479c5b4b220176e708559a5e225a21`; the unchanged 30-row training-manifest SHA-256 is `c563e60a47479831139ea0c0ef4b9bb88e2019e1ff6be481bd741d13e456ff07`. No additional-caliber scans were imported into the live workbench, approved, fitted or added to the public starter. Existing [asset terms](../data-licenses.md) still apply; publishing this report does not relicense or redistribute the private pilot assets.

## Sources

[1] https://doi.org/10.18434/M32021 — NIST Ballistics Toolmark Research Database
[2] https://doi.org/10.15132/10000262 — Dundee coarse segmentation reference masks
[3] https://scikit-learn.org/stable/modules/cross_validation.html — Grouped validation and test leakage
[4] https://afte.org/wp-content/uploads/2024/09/2010_42_4_308_Lightstone.pdf — Lightstone (2010), SW40VE slides and ammunition
[5] https://tsapps.nist.gov/NRBTD/Studies/Studies/Details/afac9d5c-8dab-411e-b282-aa0187f80da2?nm=True&mt=7&m=1&sp=1 — NIST Lightstone S&W Sigma study catalog
