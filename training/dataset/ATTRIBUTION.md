# Run #3 data attribution and rights review

**Research/development release.** The full 48-scan cohort is distributed under the asset-specific terms described here and in `docs/data-licenses.md` at the repository root: NIST published reuse terms for scan images, CC BY 4.0 for Dundee material and project annotation/checkpoint contributions, and MIT for original software. Preserve attribution, applicable disclaimers, and change notices. Workbench approval is a training-workflow decision, not forensic validation or a copyright warranty.

## Scans: NIST Ballistics Toolmark Research Database

Database citation: Xiaoyu Alan Zheng (2019), *NIST Ballistics Toolmark Research Database*, National Institute of Standards and Technology, [DOI 10.18434/M32021](https://doi.org/10.18434/M32021), version 1.0, accessed 2026-11-22 UTC. The database holds both NIST-acquired and externally submitted material; the database citation is not the credit for each measurement.[1]

The candidate contains all 48 real 9×19 mm reflectance scans across 24 source groups: the unchanged 30 approved training cases (15 groups), 6 validation cases (3 groups), and 12 test cases (6 groups). Original filenames, studies and measurement creators appear in each sanitized manifest row and starter revision attribution. The new non-training cases retain matched native-resolution source/reference and proposal labels, each in a single nonapproved source revision with included=false; no private review history or identifier crosswalk is shipped. The original 30 frozen approvals are not refreshed from the live private workspace. Asset-level receipts remain outside the candidate.

| Source study | Catalog study creator | Catalog measurement creator | Scans |
| --- | --- | --- | ---: |
| Fadul (2011)[5] | Thomas Fadul | Mingsi Tong | 12 |
| PopStat Glock[6] | Xiaoyu Zheng | Nicole Silver | 12 |
| PopStat Sig Sauer[7] | Xiaoyu Zheng | Nicole Silver | 12 |
| PopStat S&W[13] | Xiaoyu Zheng | Nicole Silver | 12 |

**Change notice (2026-11-22 UTC):** The original frozen 30 packaged scans are unchanged from the earlier packaging, which removed PNG timestamps from 30 and text chunks from 20 where present. The 18 added scans have PNG text and timestamp chunks removed where present, without re-encoding pixel data. Lossless decoded RGB pixels, native dimensions, geometry, palette, and physical sampling chunks were preserved. There was no scan resampling or cropping.

**Rights disposition (reviewed 2026-11-22 UTC): attribution-bearing redistribution under NIST published reuse terms.** The dataset-specific catalog license field and DOI rights metadata identify NIST Licensing; the linked policy expressly permits copying and distribution of modified data, while the database-linked copyright notice permits distribution except for material marked copyrighted.[2][8][11][12] The review inspected the four source-study pages, the additional 18 held-out measurement pages, and rights-related PNG metadata across all 48 originals; no contrary scan-specific reservation was found. Earlier receipts cover the original 30 measurement records. This is a bounded, practical reliance on published permission, not a claim that every creator was a federal employee or a guarantee against all third-party claims. The NIST measurement flag records where measurement occurred, and the Tong paper describes a guest researcher; neither is treated as proof of federal authorship.[9][10] Retain the NIST warranty/nonendorsement notices reproduced in `docs/data-licenses.md`. Frozen training provenance may retain historical pending markers; this release notice supersedes that earlier local publication hold without rewriting annotations, training inputs, or the checkpoint.

## Annotations: Dundee references and local workbench review

Muthu Rama Krishnan Mookiah, Roberto Puch-Solis, Farhan Tanvir Santo, and Busayo Ajala (creators); Niamh Nic Daeid (supervisor). (2024). [*Segmentation masks for breech and firing-pin areas for a NIST dataset of firearm cartridge case Images*](https://doi.org/10.15132/10000262). University of Dundee. [Creative Commons Attribution 4.0 International (CC BY 4.0)](https://creativecommons.org/licenses/by/4.0/).[3][4]

**Changes to Dundee material:** Matched the reference masks by scan and view, resized full-frame from 512 × 512 to 2592 × 1944 using nearest-neighbor sampling, mapped Dundee's firing-pin region to this workbench's center-pocket target (`firing_pin_shear`), and edited boundaries where appropriate. Among the 30 frozen approved cases, all 30 breech-face masks differ from their aligned Dundee counterparts. Two center-pocket masks match pixel for pixel after alignment; 28 differ. A difference is not proof of independent authorship. Keep the Dundee credit, source and license links, and change notice with retained or adapted masks and figures reproducing them. The CC BY 4.0 grant is for Dundee material, not the NIST scans or the candidate as a whole.[3][4]

The frozen approvals incorporate GPT-assisted annotation drafts and subsequent workbench review and edits. Dundee did not supply separate aperture-shear, exterior-scrape, or drag-direction labels for this workbench. `origin: review` records the workflow, not independent authorship. The 30 training labels are frozen saved approvals, not new predictions. The 18 holdouts retain unapproved matched source/reference and proposal statuses; some source target mappings are coarse, not adjudicated workbench ground truth. Their unknown statuses are not negative supervision. The fitted checkpoint is the existing local CPU mask estimator, not GPT or a Dundee-trained model. It can propose masks for four learned targets and does not estimate drag direction. Approval counts: 30 breech-face, 30 aperture-shear, 30 center-pocket, 16 exterior-scrape masks, and 17 ordered arrows. The seed retains 14 indeterminate exterior scrapes and 13 indeterminate arrows; the worker export represents those as `not_annotated`, just as the frozen training export did. Neither state is a negative label.

## Local verification

`training/dataset/manifest.jsonl` inventories all 48 native scans with 141 binary PNG masks (106 frozen training masks plus 35 unapproved source masks). `train.jsonl` is byte-identical to the former 30-row manifest and is the explicit fitting and grouped-evaluation input. Original scan filenames are preserved; all referenced assets use safe relative paths. `decoded_pixel_sha256` hashes packed row-major RGB bytes. The 30 training case IDs, group IDs, masks and ordered arrows remain frozen. New cases/groups use separate opaque IDs, with no private crosswalk. The full starter SQLite is 159,313,920 bytes and is transported as three deterministic parts of 67,108,864, 67,108,864 and 25,096,192 bytes. `PARTS.sha256` pins each part; `SHA256SUMS` pins the assembled database and unchanged checkpoint. The build assembles and checks the complete seed as root, then independently rechecks it under the runtime UID. The installed model is shown as Run #1 but its wrapper and fitted payload are byte-identical to Run #3. The exercise scan, assignment assets, and private histories are absent. The project validation/test splits are not official Dundee splits or an independently blind benchmark; source references and prior inspection prevent that interpretation. Estimates are software checks, not accuracy claims.

From the repository root, verify both local artifacts with `python3 training/verify_local_candidate.py`. Its independent pins cover the seed, the model wrapper, and the dataset checksum catalogue; it does not deserialize the checkpoint. To run the workbench, follow the [deployment instructions](../docs/deployment.md#start-and-stop).

## Sources

[1] https://tsapps.nist.gov/NRBTD — NIST Ballistics Toolmark Research Database
[2] https://www.nist.gov/open/license — NIST Copyright, Fair Use, and Licensing Statements
[3] https://discovery.dundee.ac.uk/en/datasets/segmentation-masks-for-breech-and-firing-pin-areas-for-a-nist-dat — University of Dundee mask dataset
[4] https://creativecommons.org/licenses/by/4.0/legalcode.en — CC BY 4.0 International: license text
[5] https://tsapps.nist.gov/NRBTD/Studies/Studies/Details/e7a8aab8-8d5a-44ac-b2be-f0de7c2ca505?nm=True&mt=7&m=1&sp=1 — NIST NBTRD study: Fadul (2011)
[6] https://tsapps.nist.gov/NRBTD/Studies/Studies/Details/8757505a-9075-4e6b-9a9f-acddf6cec951?nm=True&mt=7&m=1&sp=1 — NIST NBTRD study: PopStat Glock
[7] https://tsapps.nist.gov/NRBTD/Studies/Studies/Details/ae1f263b-8df8-4808-95dc-6459d3616ccc?nm=True&mt=7&m=1&sp=1 — NIST NBTRD study: PopStat Sig Sauer
[8] https://catalog.data.gov/dataset/nist-ballistics-toolmark-research-database — federal dataset catalog license field
[9] https://tsapps.nist.gov/NRBTD/Content/Documents/NIST-Ballistics-Toolmark-Database-Meta-Data-Glossary-2.pdf#page=16 — NBTRD metadata glossary, Table 7
[10] https://nvlpubs.nist.gov/nistpubs/jres/119/jres.119.023.pdf — Tong et al. optical-image study, pp. 578 and 582
[11] https://api.datacite.org/dois/10.18434/M32021 — publisher-deposited DOI rights metadata
[12] https://www.nist.gov/disclaimer — NIST copyright and express redistribution notice
[13] https://tsapps.nist.gov/NRBTD/Studies/Studies/Details/46169efb-47f8-46b9-82ec-8d2551ba9863?nm=True&mt=7&m=1&sp=1 — NIST NBTRD study: PopStat S&W
