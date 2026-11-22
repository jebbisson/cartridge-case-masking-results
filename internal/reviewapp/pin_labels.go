package reviewapp

import (
	"database/sql"
	"encoding/json"
	"errors"
	"fmt"
)

const (
	pinLabelMigration = "correct-training-pin-labels-v1"
	// This correction was verified for this immutable pilot-v1 manifest, not
	// for arbitrary references that happen to use the same target names.
	pinLabelManifest = "4e9ca26b82edbfc8f9beb1c29e0599dc0b63ff11707917ceec99ba03ccf28063"
	oldPinTarget     = "firing_pin_impression"
	newPinTarget     = "firing_pin_shear"
)

// CorrectTrainingPinLabels corrects the pilot-v1 TRAIN source approvals only.
// It returns zero on a repeat invocation and does not import or approve drafts.
func (a *App) CorrectTrainingPinLabels() (int, error) {
	tx, err := a.db.Begin()
	if err != nil {
		return 0, err
	}
	defer tx.Rollback()

	var hash string
	err = tx.QueryRow(`SELECT digest FROM imports WHERE name=?`, pinLabelMigration).Scan(&hash)
	if err == nil {
		if hash != pinLabelManifest {
			return 0, errors.New("unexpected training pin correction marker")
		}
		return 0, nil
	}
	if !errors.Is(err, sql.ErrNoRows) {
		return 0, err
	}
	err = tx.QueryRow(`SELECT digest FROM imports WHERE name='manifest'`).Scan(&hash)
	if err != nil && !errors.Is(err, sql.ErrNoRows) {
		return 0, err
	}
	if err != nil || hash != pinLabelManifest {
		return 0, errors.New("training pin correction requires the verified pilot-v1 seed manifest")
	}

	// Start from the original reference, not cases.latest or the current
	// approved pointer, so intervening human approvals cannot hide a candidate.
	rows, err := tx.Query(`SELECT c.id,r.id,r.source FROM cases c
		JOIN revisions r ON r.case_id=c.id AND r.kind='source' AND r.parent IS NULL
		JOIN labels l ON l.revision=r.id
		WHERE c.split='train' AND l.target=? AND l.status='present' AND l.origin='reference' AND l.rank=?
		ORDER BY c.id`, oldPinTarget, coarse)
	if err != nil {
		return 0, err
	}
	defer rows.Close()
	type candidate struct {
		caseID string
		id     int64
		source string
	}
	var candidates []candidate
	for rows.Next() {
		var v candidate
		if err := rows.Scan(&v.caseID, &v.id, &v.source); err != nil {
			return 0, err
		}
		candidates = append(candidates, v)
	}
	if err := rows.Err(); err != nil {
		return 0, err
	}
	if len(candidates) != 15 {
		return 0, fmt.Errorf("expected 15 pilot-v1 TRAIN coarse pin references, found %d", len(candidates))
	}
	for _, v := range candidates {
		c, err := findCase(tx, v.caseID)
		if err != nil {
			return 0, err
		}
		if err := appendCorrectedPinSource(tx, c, v.id, json.RawMessage(v.source)); err != nil {
			return 0, fmt.Errorf("case %s: %w", c.ID, err)
		}
	}
	if _, err := tx.Exec(`INSERT INTO imports(name,digest) VALUES(?,?)`, pinLabelMigration, pinLabelManifest); err != nil {
		return 0, err
	}
	// All earlier runs froze their training membership before this correction,
	// regardless of their status. Leave their rows and artifacts untouched.
	if _, err := tx.Exec(`INSERT INTO import_run_cutoffs(import_name,last_run) SELECT ?,coalesce(max(id),0) FROM runs`, pinLabelMigration); err != nil {
		return 0, err
	}
	if err := tx.Commit(); err != nil {
		return 0, err
	}
	return len(candidates), nil
}

func appendCorrectedPinSource(tx *sql.Tx, c Case, original int64, raw json.RawMessage) error {
	if c.Approved != original {
		return fmt.Errorf("current approval %d is not original source revision %d; refusing to replace an intervening approval", c.Approved, original)
	}
	var source struct {
		Type string       `json:"type"`
		Hash string       `json:"manifest_sha256"`
		Row  manifestCase `json:"manifest_row"`
	}
	if err := json.Unmarshal(raw, &source); err != nil {
		return fmt.Errorf("invalid source provenance: %w", err)
	}
	m := source.Row
	if source.Type != "manifest" || source.Hash != pinLabelManifest || m.ID != c.ID || m.Split != "train" || m.SHA != c.image || m.Width != c.Width || m.Height != c.Height {
		return errors.New("source revision does not match the seeded TRAIN case")
	}
	labels, err := readLabels(tx, original)
	if err != nil {
		return err
	}
	if labels[newPinTarget].Status == "present" || labels[newPinTarget].Status == "absent" {
		return fmt.Errorf("original source already has a known %s", newPinTarget)
	}
	corrected := make(map[string]Target, len(targets))
	for _, name := range targets {
		t, ok := labels[name]
		b, seeded := m.Labels[name]
		if !ok || !seeded || t.Status != b.Status || t.Origin != b.Origin || t.Rank != b.Rank || t.mask != b.MaskSHA || !samePoint(t.Start, b.Start) || !samePoint(t.End, b.End) {
			return fmt.Errorf("source label %s does not match its manifest provenance", name)
		}
		if err := verifyGeometry(name, t, c.Width, c.Height); err != nil {
			return fmt.Errorf("invalid source label %s: %w", name, err)
		}
		corrected[name] = Target{Status: "not_annotated"}
		if seedLabel(t) {
			corrected[name] = t
		}
	}
	old := labels[oldPinTarget]
	if old.Status != "present" || !seedLabel(old) || !shaID.MatchString(old.mask) {
		return errors.New("missing verified coarse reference pin mask")
	}
	data, err := assetBytes(tx, old.mask)
	if err != nil {
		return fmt.Errorf("read original pin mask: %w", err)
	}
	if digest(data) != old.mask {
		return errors.New("original pin mask bytes do not match the source digest")
	}
	corrected[oldPinTarget] = Target{Status: "not_annotated"}
	corrected[newPinTarget] = old

	provenance, err := json.Marshal(struct {
		Type           string          `json:"type"`
		SourceRevision int64           `json:"source_revision"`
		From           string          `json:"from_target"`
		To             string          `json:"to_target"`
		OriginalSource json.RawMessage `json:"original_source"`
	}{pinLabelMigration, original, oldPinTarget, newPinTarget, raw})
	if err != nil {
		return err
	}
	branch := c
	branch.Latest = original
	if _, err := appendRevision(tx, branch, "source", provenance, corrected, true); err != nil {
		return err
	}
	if c.Latest != original {
		// A source correction is not an edit to the old selected draft.
		_, err = tx.Exec(`UPDATE cases SET latest=? WHERE id=?`, c.Latest, c.ID)
	}
	return err
}
