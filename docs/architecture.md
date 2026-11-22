# Architecture

These diagrams describe the intended seeded Compose setup. The starter assets and their redistribution terms are still under review.

> **VS Code preview:** VS Code 1.121 and later [render Mermaid in the built-in Markdown preview](https://code.visualstudio.com/updates/v1_121/#_mermaid-diagrams-in-markdown-preview-and-notebooks). If diagrams flash and disappear, disable the older **Markdown Preview Mermaid Support** extension (`bierner.markdown-mermaid`) for this workspace, keep **Mermaid Markdown Features** enabled, and reload the window.

## System overview

```mermaid
flowchart LR
    Browser["Local browser<br/>React editor"]
    subgraph App["One Linux x86-64 Compose app"]
        Go["Go server<br/>Static UI, HTTP API, and workspace owner"]
        Worker["Python 3.14 subprocess<br/>CPU mask estimator"]
        Go -->|"invoke train or predict"| Worker
        Worker -->|"checkpoint or mask proposal"| Go
    end
    subgraph Volume["Named volume at /data"]
        DB[("SQLite: scans, mask assets, revisions, run records")]
        Runs["Run directories: exported snapshots and checkpoints"]
    end
    Browser <-->|"loopback HTTP, port 8787"| Go
    Go <-->|"reads and writes"| DB
    Go <-->|"manages files"| Runs
    Runs -.->|"snapshot or trusted checkpoint input"| Worker
```

The browser does not train or generate labels. Go owns the database and run records. Python reads the files Go supplies and writes its requested output files; it does not edit SQLite. The app is intended for one local user, not network hosting. See [Deployment](deployment.md).

## Browser editor flow

```mermaid
flowchart TD
    Queue["Select case"] --> Latest["Open latest saved revision"]
    Latest --> Edit["Unsaved mask or manual arrow edits"]
    Latest -->|"Run new estimate"| Preview["Unsaved mask preview<br/>Existing arrow unchanged"]
    Preview --> Edit
    Edit <-->|"compare history / return to edits"| History["Saved revision, read-only"]
    Edit -->|"Cancel edits"| Latest
    Edit -->|"Save draft"| Draft["New saved draft"]
    Edit -->|"Approve"| Approved["New approved revision"]
    Approved -->|"only if eligible and included"| Snapshot["Candidate for next training snapshot"]
```

Inference does not create a saved revision or replace training approval. The [browser editor guide](../web/README.md) describes these controls.

## Python worker flow

```mermaid
flowchart TD
    Snapshot["Go: pin approved, included train snapshot"] --> Train["Worker: fit per-region mask models"]
    Train --> New["Versioned checkpoint for a new run"]
    New --> Select["Go: select compatible trusted checkpoint"]
    Starter["Cleared Run #3 checkpoint, when available"] --> Select
    Select --> Verify["Worker: check expected digest and compatibility"]
    PNG["Original case PNG"] --> Infer["Extract features, predict and clean masks"]
    Verify --> Infer
    Infer --> Result["Native-resolution binary PNGs and proposal JSON"]
    Result --> Preview["Go validates; browser previews as unsaved edits"]
```

A refit is a separate run, not a way to recreate the original fitted Run #3 checkpoint. See the [Python estimator guide](../python/README.md) for the method and CLI.

## Starter workflow

```mermaid
flowchart TD
    Candidate["Proposed real cases, label records, and Run #3 checkpoint"] --> Gate{"Exact assets cleared for redistribution?"}
    Gate -->|No| Local["Keep local; do not distribute"]
    Gate -->|Yes| Fresh["Initialize a fresh workspace from the cleared bundle"]
    Fresh --> Case["Open a seeded case"]
    Case --> Estimate["Preview Run #3 masks without retraining"]
    Estimate --> Review["Compare with the original; save only if intended"]
```

The starter is a sanitized full 48-case inventory, not a copy of a private workspace. Only the frozen 30 train cases are approved and included; 6 validation and 12 test cases have unapproved source revisions and are not an independently blind evaluation set. See [Starter cases and credits](../starter/README.md).
