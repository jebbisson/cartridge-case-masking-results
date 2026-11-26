# Starter cases and data credits

[Back to the workbench README](../README.md#documentation)

See the [starter workflow diagram](../docs/architecture.md#starter-workflow).

The workbench seeds a fresh workspace with **48 real 9×19 mm cohort scans: 30 approved training cases, 6 validation cases, and 12 test cases** and the **same fitted Run #3 mask-only checkpoint**. The [Docker build](../docs/deployment.md#start-and-stop) embeds the verified seed so an estimate works without retraining. Scans use NIST's published reuse terms; mask adaptations and project annotations/checkpoint retain separate CC BY 4.0 terms and credits. See [Data, annotation, and model terms](../docs/data-licenses.md).

`starter/full-bundle/` contains three deterministic SQLite transport parts (each at most 64 MiB), their `PARTS.sha256`, the matching checkpoint, and full-file `SHA256SUMS`. The build assembles the seed and verifies both part and complete-file checksums before switching to the runtime user. The build and loader verify the files against independent pins. An existing workspace is never reseeded. The UI displays the imported model as Run #1; “Run #3” refers to the original fitted artifact.

## Data and model sources

| Material | Source and role | Changes and limits |
| --- | --- | --- |
| Microscopy PNGs | Xiaoyu Alan Zheng (2019), [*NIST Ballistics Toolmark Research Database*](https://doi.org/10.18434/M32021), National Institute of Standards and Technology. The 2D reflectance scans were obtained separately from the masks. | The local starter preserves scan pixels and sampling metadata, but strips PNG text and timestamp chunks. The files are not byte-for-byte originals. Check the rights and required credits for the exact scans; [NIST licensing guidance](https://www.nist.gov/open/license) does not automatically clear third-party material. |
| Source masks | University of Dundee breech-face and firing-pin masks; see the [attribution below](#dundee-mask-attribution). | Some were retained after resizing; others were edited or replaced. Dundee did not provide separate aperture, exterior scrape, or directional arrow annotations for this workbench. |
| Local annotations | GPT-assisted drafts and subsequent review and edits in the workbench. | These include targets that Dundee did not provide. Only approved versions of the training cases were used for fitting. |
| Run #3 checkpoint | Fitted locally on the 30 approved development cases using the [Python estimator](../python/README.md). | This is not a Dundee checkpoint or a GPT model. The model is distributed under CC BY 4.0 with source-mask provenance, including its training-derived spatial priors. |

## How the training masks were made

We used Dundee's coarse masks as starting points where they matched a scan and view. GPT generated initial annotation proposals from the real scans, including for targets that lacked a reference mask. We then reviewed and edited the combined drafts in the workbench. The frozen Run #3 training set contains both local labels and retained or adapted Dundee labels. Two approved center-pocket masks still match the resized Dundee masks pixel for pixel. A changed boundary does not make a mask independently authored. See the [cohort attribution](../training/ATTRIBUTION.md) for details.

The saved starter annotations are not fresh estimates. **Run new estimate** invokes the locally fitted CPU mask model and best-effort arrow estimator, not GPT. The original mask checkpoint is unchanged; a companion prior learned from the 17 annotated training arrows supplies direction/length when predicted pocket/scrape support is weak. New estimates include an arrow without changing saved labels until explicitly saved or approved.

## Dundee mask attribution

**Source:** Muthu Rama Krishnan Mookiah, Roberto Puch-Solis, Farhan Tanvir Santo, and Busayo Ajala (creators); Niamh Nic Daeid (supervisor). (2024). [*Segmentation masks for breech and firing-pin areas for a NIST dataset of firearm cartridge case Images*](https://doi.org/10.15132/10000262). University of Dundee. **[Creative Commons Attribution 4.0 International (CC BY 4.0)](https://creativecommons.org/licenses/by/4.0/).**

**Changes we made:** Matched the source masks by scan and view, then resized them from 512 × 512 to 2592 × 1944 using full-frame nearest-neighbor resampling. We mapped Dundee's firing-pin region to our center-pocket class, refined some mask boundaries during review, and added local annotations as separate layers. Color overlays are workbench renderings, not source files.

Keep the source credit, dataset and license links, and change notice with any distributed Dundee masks or adaptations, including figures that reproduce them. The [MIT license](../LICENSE) is for the original workbench software, not the masks, scans, or fitted checkpoint. Dundee's CC BY 4.0 grant covers its masks, not the underlying NIST images or the complete starter bundle.

## What is out of scope

- The 18 project validation/test cases retain unapproved source/reference and proposal labels; they are excluded from fitting. These are not official benchmark splits or independently blind reference labels. No synthetic fixtures, exercise scan, or assignment assets are included.
- No assignment PDF or scans extracted from it, and no private databases, manifests, research history, or experimental model candidates.
- No forensic validation or accuracy claim. A seeded development case shows how the editor works; it does not measure performance on unseen source groups.

Preserve the applicable notices when redistributing this package; additional scans or screenshots need their own provenance and rights review. Native Linux workspace checks passed, and Windows Docker Desktop execution was confirmed by the user. On either host, the cases should open, **Run new estimate** should reproduce the baseline masks and propose an arrow without refitting, and saved revisions should remain unchanged until saved or approved. A restart should retain the workspace.
