# Starter cases and data credits

[Back to the workbench README](../README.md#documentation)

See the [starter workflow diagram](../docs/architecture.md#starter-workflow).

The intended first run opens a small set of real 9×19 mm development scans and makes the **same fitted Run #3 mask-only checkpoint** available for an estimate without retraining. This directory documents that design; it does not authorize shipping local assets. The exact starter files, including any derived labels, screenshots, and checkpoint, are still under rights review. Local candidates are for working-tree review only and are **not for release**.

The planned bundle contains a SQLite seed prepared for distribution, its matching checkpoint, and a `SHA256SUMS` file. The loader checks the files before installing them into a fresh volume. Checksums detect mismatches; they do not establish provenance or redistribution rights. The imported model's run number in a fresh workspace may differ from the original training run number. “Run #3” refers to the fitted artifact, not the UI counter.

## Data and model sources

| Material | Source and role | Changes and limits |
| --- | --- | --- |
| Microscopy PNGs | Xiaoyu Alan Zheng (2019), [*NIST Ballistics Toolmark Research Database*](https://doi.org/10.18434/M32021), National Institute of Standards and Technology. The 2D reflectance scans were obtained separately from the masks. | The local starter preserves scan pixels and sampling metadata, but strips PNG text and timestamp chunks. The files are not byte-for-byte originals. Check the rights and required credits for the exact scans; [NIST licensing guidance](https://www.nist.gov/open/license) does not automatically clear third-party material. |
| Source masks | University of Dundee breech-face and firing-pin masks; see the [attribution below](#dundee-mask-attribution). | Some were retained after resizing; others were edited or replaced. Dundee did not provide separate aperture, exterior scrape, or directional arrow annotations for this workbench. |
| Local annotations | GPT-assisted drafts and subsequent review and edits in the workbench. | These include targets that Dundee did not provide. Only approved versions of the training cases were used for fitting. |
| Run #3 checkpoint | Fitted locally on 30 approved development cases using the [Python estimator](../python/README.md). | This is not a Dundee checkpoint or a GPT model. The four starter cases are a subset of the training cohort. Checkpoint redistribution is a separate decision. |

## How the training masks were made

We used Dundee's coarse masks as starting points where they matched a scan and view. GPT generated initial annotation proposals from the real scans, including for targets that lacked a reference mask. We then reviewed and edited the combined drafts in the workbench. The frozen Run #3 training set contains both local labels and retained or adapted Dundee labels. Two approved center-pocket masks still match the resized Dundee masks pixel for pixel. None of the four starter cases' breech-face or center-pocket masks matches its resized Dundee counterpart exactly; a changed boundary does not make a mask independently authored.

The saved starter annotations are not fresh estimates. **Run new estimate** invokes the locally fitted CPU model, not GPT. It proposes masks only and does not generate drag-direction arrows.

## Dundee mask attribution

**Source:** Muthu Rama Krishnan Mookiah, Roberto Puch-Solis, Farhan Tanvir Santo, and Busayo Ajala (creators); Niamh Nic Daeid (supervisor). (2024). [*Segmentation masks for breech and firing-pin areas for a NIST dataset of firearm cartridge case Images*](https://doi.org/10.15132/10000262). University of Dundee. **[Creative Commons Attribution 4.0 International (CC BY 4.0)](https://creativecommons.org/licenses/by/4.0/).**

**Changes we made:** Matched the source masks by scan and view, then resized them from 512 × 512 to 2592 × 1944 using full-frame nearest-neighbor resampling. We mapped Dundee's firing-pin region to our center-pocket class, refined some mask boundaries during review, and added local annotations as separate layers. Color overlays are workbench renderings, not source files.

Keep the source credit, dataset and license links, and change notice with any distributed Dundee masks or adaptations, including figures that reproduce them. The [MIT license](../LICENSE) is for the original workbench software, not the masks, scans, or fitted checkpoint. Dundee's CC BY 4.0 grant covers its masks, not the underlying NIST images or the complete starter bundle.

## What is out of scope

- No synthetic fixtures or examples and no official held-out cases or benchmark assets.
- No assignment PDF or scans extracted from it, and no private databases, manifests, research history, or experimental model candidates.
- No forensic validation or accuracy claim. A seeded development case shows how the editor works; it does not measure performance on unseen source groups.

Before distribution, verify the rights for the exact scans, annotations, checkpoint, and screenshots, and preserve the applicable notices. Check the release tree and container contents for excluded material. Then test a clean workspace on both target hosts: the cases should open, **Run new estimate** should reproduce the baseline masks without fitting, and inference should leave saved revisions and arrows unchanged. A restart should retain the workspace.
