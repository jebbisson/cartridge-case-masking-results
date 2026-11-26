# Browser editor

[Back to the workbench README](../README.md#documentation)

**Using the app? Start with the [illustrated user guide](../docs/user-guide.md)**—real screenshots, numbered interface areas, and step-by-step review, save, training, and scan-intake workflows. This README also covers frontend development.

The React UI receives the case queue, originals, saved masks, revisions, and training state from the local Go API. See the [browser editor diagram](../docs/architecture.md#browser-editor-flow). The frontend does not ship its own scans or generate labels.

## Review a case

1. Open a case. **Original** hides the overlays without altering the source PNG. **Run new estimate** previews masks and a best-effort directed arrow as unsaved edits. The proposed arrow replaces any arrow in the edit buffer, but saved annotations stay unchanged until **Save draft** or **Approve**. Use **Cancel edits** to restore the saved revision.
2. Select a mask layer and use **Brush** or **Eraser**. Brush diameter is measured in native pixels; zoom in with a size-1 brush for a one-pixel correction. To edit a defensible drag direction manually, choose **Arrow**, drag tail to tip, and correct with the endpoint handles or **Reverse arrow**. Leave a direction indeterminate when the scan does not support it.
3. In **Revisions**, select a saved revision to compare, then choose **Back to unsaved edits** to return. Historical revisions are read-only. **Cancel edits** discards only the unsaved work. **Save draft** persists a new draft; **Approve** saves a new approved revision. Saving a draft or running an estimate does not replace the approved revision used for training.
4. Use **Training changes** to inspect the next snapshot. **Confirm & retrain** submits the exact fingerprint shown in the preview. Only eligible, included training cases contribute approved labels; unsaved edits and unapproved drafts are not training inputs.

The four mask layers are breech face (red), aperture shear (green), firing-pin shear / center pocket (purple), and firing-pin impression / exterior scrape (light blue). The blue drag arrow is a separate ordered tail/tip pair, not a mask. **Add scan** accepts a PNG, case name, and explicit source group; use the known group rather than inventing a new group for another view of the same source.

## Frontend development

Run from this directory with Node 20.19.2 or newer:

```sh
npm ci
npm test
npm run build
```

Go serves `web/dist`. To work on the UI separately, start the [native Go backend](../docs/deployment.md#native-development), then run `npm run dev` here. Vite binds to `127.0.0.1` and proxies `/api` to `http://127.0.0.1:8787`; set `REVIEW_API_URL` before starting Vite if the backend uses a different local port.

For a browser check, use a disposable workspace with an authorized real scan. Compare the original and estimate at the same zoom, save a one-pixel draft edit, and reopen it. Confirm that switching revisions preserves unsaved edits, that an estimate creates or replaces an arrow in the unsaved buffer, and that cancellation restores the saved state without changing history. Saved revisions and approvals must remain unchanged until an explicit save or approval.
