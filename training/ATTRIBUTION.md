# Run #3 data attribution and rights review

**Local review only. Not cleared for redistribution.** These files are prepared for local review in the public repository checkout, not for upload. Do not publish the dataset, full seed, fitted checkpoint, overlays, screenshots, or a container containing them. Approval in the workbench is approval for the training snapshot, not legal clearance or forensic validation. The repository's software license does not license these assets.

## Scans: NIST Ballistics Toolmark Research Database

Database citation: Xiaoyu Alan Zheng (2019), *NIST Ballistics Toolmark Research Database*, National Institute of Standards and Technology, [DOI 10.18434/M32021](https://doi.org/10.18434/M32021), version 1.0, accessed 2026-11-22 UTC. The database holds both NIST-acquired and externally submitted material; the database citation is not the credit for each measurement.[1]

The candidate contains only the 30 approved 9×19 mm reflectance scans in the fitted Run #3 snapshot, across 15 source groups. The exact original filename, catalog study, and catalog **measurement creator** are attached to each sanitized case in `manifest.jsonl` (`source.image`) and the seed's approved revision (`source.attribution.image`). All 30 individual public measurement records were rechecked against the source inventory on 2026-11-22 UTC: the names, filenames, imaging fields and `NIST Meas. = True` flags matched. Asset-level receipts and the mapping to original measurement and group IDs are kept outside the candidate.

| Source study | Catalog study creator | Catalog measurement creator | Scans |
| --- | --- | --- | ---: |
| Fadul (2011)[5] | Thomas Fadul | Mingsi Tong | 10 |
| PopStat Glock[6] | Xiaoyu Zheng | Nicole Silver | 10 |
| PopStat Sig Sauer[7] | Xiaoyu Zheng | Nicole Silver | 10 |

**Change notice (2026-11-22 UTC):** Removed PNG timestamps from 30 scans and text chunks from 20 where present. The source PNG `Author`, `Copyright`, `Disclaimer`, `Warning`, and `Source` fields were empty or absent. Lossless scan pixels, dimensions, and stored physical sampling were preserved; the packaged scans are not byte-identical to the source files. There was no scan resampling or cropping.

**Rights disposition: pending for all 30 scans.** The Data.gov record links this dataset to NIST's licensing policy, and NIST defines the measurement flag as whether the data was obtained at NIST.[2][8][9] That identifies where the scans were made, not who holds redistribution rights. The paper about the Fadul optical images identifies the credited measurement creator Mingsi Tong as a guest researcher.[10] No file-specific restriction was found, but neither federal-employee authorship nor a rights assignment covering downstream distribution was established for the full cohort. Confirm the applicable grant and carry forward its notice, disclaimer, and acknowledgments before any upload. Separately review the local annotations, fitted checkpoint, and any screenshots or overlays.

## Annotations: Dundee references and local workbench review

Muthu Rama Krishnan Mookiah, Roberto Puch-Solis, Farhan Tanvir Santo, and Busayo Ajala (creators); Niamh Nic Daeid (supervisor). (2024). [*Segmentation masks for breech and firing-pin areas for a NIST dataset of firearm cartridge case Images*](https://doi.org/10.15132/10000262). University of Dundee. [Creative Commons Attribution 4.0 International (CC BY 4.0)](https://creativecommons.org/licenses/by/4.0/).[3][4]

**Changes to Dundee material:** Matched the reference masks by scan and view, resized full-frame from 512 × 512 to 2592 × 1944 using nearest-neighbor sampling, mapped Dundee's firing-pin region to this workbench's center-pocket target (`firing_pin_shear`), and edited boundaries where appropriate. Among the 30 frozen approved cases, all 30 breech-face masks differ from their aligned Dundee counterparts. Two center-pocket masks match pixel for pixel after alignment; 28 differ. A difference is not proof of independent authorship. Keep the Dundee credit, source and license links, and change notice with retained or adapted masks and figures reproducing them. The CC BY 4.0 grant is for Dundee material, not the NIST scans or the candidate as a whole.[3][4]

The frozen approvals incorporate GPT-assisted annotation drafts and subsequent workbench review and edits. Dundee did not supply separate aperture-shear, exterior-scrape, or drag-direction labels for this workbench. `origin: review` records the workflow, not independent authorship. The shipped labels are saved approvals, not new predictions. The fitted checkpoint is the existing local CPU mask estimator, not GPT or a Dundee-trained model. It can propose masks for four learned targets and does not estimate drag direction. Approval counts: 30 breech-face, 30 aperture-shear, 30 center-pocket, 16 exterior-scrape masks, and 17 ordered arrows. The seed retains 14 indeterminate exterior scrapes and 13 indeterminate arrows; the worker export represents those as `not_annotated`, just as the frozen training export did. Neither state is a negative label.

## Local verification

`training/dataset/` has relative paths in a worker-format `manifest.jsonl`, 30 images, 106 binary PNG masks, and recorded source attribution. Image filenames and starter case names match the NIST originals; the internal case IDs are unchanged. `decoded_pixel_sha256` hashes packed row-major RGB bytes; width and height are separate fields. `starter/full-bundle/` is the immutable source for the workspace seed embedded in the workbench image. Its `SHA256SUMS` lists exactly two files: `review.sqlite` and `review.sqlite.runs/1/checkpoint.json`. The installed model is shown as Run #1 in a fresh workspace, but the fitted payload is byte-identical to Run #3. No project-held-out scans or assignment material are included. An estimate on these cases is a software check, not an accuracy test.

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
