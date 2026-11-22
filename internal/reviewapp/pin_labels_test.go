package reviewapp

import (
	"encoding/json"
	"reflect"
	"strings"
	"testing"
)

func TestCorrectTrainingPinLabelsRealManifest(t *testing.T) {
	a, _ := realApp(t, Options{})
	h := a.Handler()
	// Leave a model proposal selected on one affected case. Its mask must not
	// become approved, and the proposal should still be selected after migration.
	tx, err := a.db.Begin()
	if err != nil {
		t.Fatal(err)
	}
	defer tx.Rollback()
	c, err := findCase(tx, firstCase)
	if err != nil {
		t.Fatal(err)
	}
	draft, err := readLabels(tx, c.Approved)
	if err != nil {
		t.Fatal(err)
	}
	draft["firing_pin_shear"] = Target{Status: "present", Origin: "proposal", mask: draft["breech_face"].mask}
	if _, err := appendRevision(tx, c, "proposal", json.RawMessage(`{"method":"external_proposal"}`), draft, false); err != nil {
		t.Fatal(err)
	}
	if err := tx.Commit(); err != nil {
		t.Fatal(err)
	}

	cases, err := listCases(a.db)
	if err != nil {
		t.Fatal(err)
	}
	before := map[string]Detail{}
	for _, c := range cases {
		d, err := detail(a.db, c.ID, 0)
		if err != nil {
			t.Fatal(err)
		}
		before[c.ID] = d
	}
	oldPreview := preview(t, h)
	if n, err := a.CorrectTrainingPinLabels(); err != nil || n != 15 {
		t.Fatalf("corrected %d cases, want 15: %v", n, err)
	}
	if n, err := a.CorrectTrainingPinLabels(); err != nil || n != 0 {
		t.Fatalf("rerun corrected %d cases, want 0: %v", n, err)
	}

	var moved, breech int
	for _, c := range cases {
		prior := before[c.ID]
		now, err := detail(a.db, c.ID, 0)
		if err != nil {
			t.Fatal(err)
		}
		source := prior.Revisions[len(prior.Revisions)-1]
		old := source.Targets["firing_pin_impression"]
		if c.Split != "train" || old.Status != "present" || old.Origin != "reference" || old.Rank != "coarse_baseline_only" {
			if !reflect.DeepEqual(now, prior) {
				t.Fatalf("unaffected case %s changed", c.ID)
			}
			continue
		}
		moved++
		rev := now.Revisions[0]
		want := c
		want.Approved = rev.ID
		if c.Latest == c.Approved {
			want.Latest = rev.ID
		}
		if now.Case != want || rev.Kind != "source" || rev.Parent != source.ID || !reflect.DeepEqual(now.Revisions[1:], prior.Revisions) {
			t.Fatalf("%s: migration did not preserve history and selected draft", c.ID)
		}
		var provenance struct {
			Revision int64           `json:"source_revision"`
			From     string          `json:"from_target"`
			To       string          `json:"to_target"`
			Source   json.RawMessage `json:"original_source"`
		}
		if err := json.Unmarshal(rev.Source, &provenance); err != nil || provenance.Revision != source.ID || provenance.From != "firing_pin_impression" || provenance.To != "firing_pin_shear" || string(provenance.Source) != string(source.Source) {
			t.Fatalf("%s: lost original source provenance: %v", c.ID, err)
		}
		if rev.Targets["firing_pin_shear"] != old || rev.Targets["firing_pin_impression"] != (Target{Status: "not_annotated"}) {
			t.Fatalf("%s: exact source mask was not moved, or old target not cleared", c.ID)
		}
		data, err := assetBytes(a.db, old.mask)
		if err != nil || digest(data) != old.mask {
			t.Fatalf("%s: moved source bytes don't match the original digest: %v", c.ID, err)
		}
		for _, name := range []string{"breech_face", "aperture_shear", drag} {
			want := Target{Status: "not_annotated"}
			if l := source.Targets[name]; l.Origin == "reference" && l.Rank == "coarse_baseline_only" && (l.Status == "present" || l.Status == "absent") {
				want = l
			}
			if rev.Targets[name] != want {
				t.Fatalf("%s: incorrect carry-forward of %s: %+v", c.ID, name, rev.Targets[name])
			}
		}
	}
	read, err := a.db.Begin()
	if err != nil {
		t.Fatal(err)
	}
	defer read.Rollback()
	ms, _, fp, err := snapshot(read)
	if err != nil {
		t.Fatal(err)
	}
	for _, m := range ms {
		if m.Labels["breech_face"].Status == "present" {
			breech++
		}
		if m.Labels["firing_pin_impression"].Status != "not_annotated" {
			t.Fatalf("%s: old schema still in training snapshot", m.ID)
		}
	}
	if moved != 15 || breech != 25 || len(ms) != 27 || fp == oldPreview.Fingerprint {
		t.Fatalf("wrong snapshot: moved=%d breech=%d eligible=%d same fingerprint=%t", moved, breech, len(ms), fp == oldPreview.Fingerprint)
	}
}

func TestCorrectTrainingPinLabelsRejectsUnexpectedSourceState(t *testing.T) {
	for _, tc := range []struct {
		name, want string
		change     func(*testing.T, *App, string, int64)
	}{
		{"human approval", "refusing to replace an intervening approval", func(t *testing.T, a *App, id string, _ int64) {
			h := a.Handler()
			d := caseDetail(t, h, id)
			body, labels := bodyFor(d, true)
			for name := range labels {
				labels[name] = wireLabel{Status: "not_annotated"}
			}
			labels["firing_pin_impression"] = wireLabel{Status: "absent"}
			request(t, h, "POST", "/api/cases/"+id+"/review", body, 200)
		}},
		{"known shear", "already has a known firing_pin_shear", func(t *testing.T, a *App, _ string, revision int64) {
			if _, err := a.db.Exec(`UPDATE labels SET status='absent' WHERE revision=? AND target='firing_pin_shear'`, revision); err != nil {
				t.Fatal(err)
			}
		}},
		{"wrong rank", "expected 15 pilot-v1 TRAIN coarse pin references", func(t *testing.T, a *App, _ string, revision int64) {
			if _, err := a.db.Exec(`UPDATE labels SET rank='needs_boundary_review' WHERE revision=? AND target='firing_pin_impression'`, revision); err != nil {
				t.Fatal(err)
			}
		}},
	} {
		t.Run(tc.name, func(t *testing.T) {
			a, _ := realApp(t, Options{})
			// Tamper with the last candidate so the human/shear guard tests
			// rollback of all the prior inserts in the migration transaction.
			var id string
			var revision int64
			if err := a.db.QueryRow(`SELECT c.id,c.approved FROM cases c JOIN labels l ON l.revision=c.approved WHERE c.split='train' AND l.target='firing_pin_impression' AND l.status='present' AND l.rank='coarse_baseline_only' ORDER BY c.id DESC LIMIT 1`).Scan(&id, &revision); err != nil {
				t.Fatal(err)
			}
			tc.change(t, a, id, revision)
			before, err := listCases(a.db)
			if err != nil {
				t.Fatal(err)
			}
			var revisions int
			if err := a.db.QueryRow(`SELECT count(*) FROM revisions`).Scan(&revisions); err != nil {
				t.Fatal(err)
			}
			if n, err := a.CorrectTrainingPinLabels(); n != 0 || err == nil || !strings.Contains(err.Error(), tc.want) {
				t.Fatalf("expected fail-closed result, got %d, %v", n, err)
			}
			after, err := listCases(a.db)
			if err != nil || !reflect.DeepEqual(before, after) {
				t.Fatalf("failed migration changed case pointers: %v", err)
			}
			var afterRevisions, imports int
			if err := a.db.QueryRow(`SELECT (SELECT count(*) FROM revisions),(SELECT count(*) FROM imports)`).Scan(&afterRevisions, &imports); err != nil || afterRevisions != revisions || imports != 1 {
				t.Fatalf("failed migration left rows behind: revisions=%d/%d imports=%d err=%v", afterRevisions, revisions, imports, err)
			}
		})
	}
}
