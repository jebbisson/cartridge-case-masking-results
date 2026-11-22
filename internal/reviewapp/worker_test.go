package reviewapp

import (
	"encoding/json"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

func preview(t *testing.T, h http.Handler) Preview {
	t.Helper()
	return parse[Preview](t, request(t, h, "GET", "/api/training/preview", nil, 200))
}
func TestInterruptedRunDoesNotBlockNextRun(t *testing.T) {
	a, db := realApp(t, Options{})
	p := preview(t, a.Handler())
	first, _, err := a.freeze(p.Fingerprint)
	if err != nil {
		t.Fatal(err)
	}
	if other, err := Open(db, Options{}); err == nil {
		other.Close()
		t.Fatal("opened a second writer that could interrupt an active run")
	}
	if err := a.Close(); err != nil {
		t.Fatal(err)
	}
	a, err = Open(db, Options{})
	if err != nil {
		t.Fatal(err)
	}
	defer a.Close()
	runs := parse[[]Run](t, request(t, a.Handler(), "GET", "/api/training/runs", nil, 200))
	if len(runs) != 1 || runs[0].ID != first.ID || runs[0].Status != "failed" || runs[0].Error == "" {
		t.Fatalf("restart did not recover interrupted run: %+v", runs)
	}
	if second, _, err := a.freeze(p.Fingerprint); err != nil || second.ID == first.ID {
		t.Fatalf("could not freeze a new run: %+v %v", second, err)
	}
}

func TestRealTrainingSnapshotAndEstimate(t *testing.T) {
	worker := filepath.Join("..", "..", "python", "review_worker.py")
	if _, err := os.Stat(worker); err != nil {
		t.Skip("Python worker not available")
	}
	python := os.Getenv("REVIEW_TEST_PYTHON")
	if python == "" {
		for _, candidate := range []string{"python3", "python"} {
			if exec.Command(candidate, "-E", "-c", "from PIL import Image").Run() == nil {
				python = candidate
				break
			}
		}
	}
	if python == "" {
		t.Skip("Python with Pillow not available; set REVIEW_TEST_PYTHON")
	}
	a, _ := realApp(t, Options{Worker: worker, Python: python})
	h := a.Handler()
	request(t, h, "POST", firstURL+"/estimate", map[string]any{"base_revision": caseDetail(t, h, firstCase).Latest}, 409)
	p := preview(t, h)
	if len(p.Added) != 27 || p.Total != 27 || p.Unchanged != 0 || p.Fingerprint == "" {
		t.Fatalf("unexpected coarse seed preview: %+v", p)
	}
	request(t, h, "POST", firstURL+"/inclusion", map[string]bool{"included": false}, 200)
	request(t, h, "POST", "/api/training/runs", map[string]string{"fingerprint": p.Fingerprint}, 409)
	request(t, h, "POST", firstURL+"/inclusion", map[string]bool{"included": true}, 200)
	r := parse[Run](t, request(t, h, "POST", "/api/training/runs", map[string]string{"fingerprint": p.Fingerprint}, 202))
	if r.Status != "running" {
		t.Fatalf("unexpected initial run: %+v", r)
	}
	source := caseDetail(t, h, firstCase)
	body, labels := bodyFor(source, true)
	labels["aperture_shear"] = wireLabel{Status: "absent"}
	changed := parse[Detail](t, request(t, h, "POST", firstURL+"/review", body, 200))
	excluded := p.Added[0].ID
	if excluded == firstCase {
		excluded = p.Added[1].ID
	}
	request(t, h, "POST", "/api/cases/"+excluded+"/inclusion", map[string]bool{"included": false}, 200)
	deadline := time.Now().Add(90 * time.Second)
	for r.Status == "running" && time.Now().Before(deadline) {
		time.Sleep(200 * time.Millisecond)
		runs := parse[[]Run](t, request(t, h, "GET", "/api/training/runs", nil, 200))
		r = runs[0]
	}
	if r.Status != "succeeded" || r.Model == "" {
		t.Fatalf("real worker did not finish: %+v", r)
	}
	data, err := os.ReadFile(filepath.Join(a.runDir(r.ID), "manifest.jsonl"))
	if err != nil {
		t.Fatal(err)
	}
	lines := strings.Split(strings.TrimSpace(string(data)), "\n")
	if len(lines) != 27 {
		t.Fatalf("expected the exact 27 frozen scans, got %d", len(lines))
	}
	seen := map[string]bool{}
	var last string
	for _, line := range lines {
		var row struct {
			ID, Split, Image string
			Labels           map[string]bundleLabel
		}
		if err := json.Unmarshal([]byte(line), &row); err != nil {
			t.Fatal(err)
		}
		if row.Split != "train" || seen[row.ID] || row.ID <= last || len(row.Labels) != len(targets) || filepath.IsAbs(row.Image) {
			t.Fatalf("bad snapshot row: %+v", row)
		}
		seen[row.ID] = true
		last = row.ID
		if row.ID == firstCase && (row.Labels["aperture_shear"].Status != "not_annotated" || row.Labels["breech_face"].Rank != coarse) {
			t.Fatalf("snapshot did not freeze seed labels: %+v", row.Labels)
		}
		for name, l := range row.Labels {
			if l.Status == "present" && (l.Origin != "reference" || l.Rank != coarse) {
				t.Fatalf("unapproved %s reached worker", name)
			}
		}
	}
	if !seen[firstCase] || !seen[excluded] {
		t.Fatal("snapshot membership changed after freezing")
	}
	p = preview(t, h)
	if len(p.Added) != 0 || len(p.Excluded) != 1 || p.Excluded[0].ID != excluded || len(p.Corrected) != 1 || p.Corrected[0].ID != firstCase || p.Corrected[0].Revision != changed.Approved || p.Corrected[0].PreviousRevision != source.Approved || len(p.Corrected[0].Targets) != 1 || p.Corrected[0].Targets[0] != "aperture_shear" || p.Unchanged != 25 || p.Total != 26 {
		t.Fatalf("wrong change list: %+v", p)
	}
	before := caseDetail(t, h, firstCase)
	var assets int
	if err := a.db.QueryRow(`SELECT count(*) FROM assets`).Scan(&assets); err != nil {
		t.Fatal(err)
	}
	w := request(t, h, "POST", firstURL+"/estimate", map[string]any{"base_revision": before.Latest}, 200)
	d := caseDetail(t, h, firstCase)
	if d.Latest != before.Latest || d.Approved != before.Approved || len(d.Revisions) != len(before.Revisions) {
		t.Fatal("estimate wrote a revision before Save draft or Approve")
	}
	var after int
	if err := a.db.QueryRow(`SELECT count(*) FROM assets`).Scan(&after); err != nil || after != assets {
		t.Fatalf("estimate wrote assets: before %d, after %d: %v", assets, after, err)
	}
	result := parse[struct {
		Base    int64                  `json:"base_revision"`
		Run     int64                  `json:"run_id"`
		Targets map[string]reviewLabel `json:"targets"`
	}](t, w)
	if result.Base != before.Latest || result.Run != r.ID || len(result.Targets) != len(targets) || len(result.Targets["breech_face"].PNG) == 0 {
		t.Fatal("preview is missing its base revision, model run, or masks")
	}
	request(t, h, "POST", firstURL+"/estimate", map[string]any{"base_revision": source.Latest}, 409)
	if q := preview(t, h); q.Fingerprint != p.Fingerprint {
		t.Fatal("prediction entered training membership")
	}
}

func TestPinSchemaCorrectionBlocksStaleCheckpoints(t *testing.T) {
	a, _ := realApp(t, Options{})
	h := a.Handler()
	freeze := func() Run {
		t.Helper()
		r, _, err := a.freeze(preview(t, h).Fingerprint)
		if err != nil {
			t.Fatal(err)
		}
		return r
	}
	succeed := func(r Run) {
		t.Helper()
		// Mark frozen rows successful without launching a training process.
		if _, err := a.db.Exec(`UPDATE runs SET status='succeeded',finished='test',manifest_sha=?,checkpoint_sha=? WHERE id=?`, digest([]byte("manifest")), digest([]byte("checkpoint")), r.ID); err != nil {
			t.Fatal(err)
		}
	}
	old := freeze()
	succeed(old)
	readOldRun := func() (data [8]string) {
		t.Helper()
		if err := a.db.QueryRow(`SELECT status,fingerprint,snapshot,started,finished,manifest_sha,checkpoint_sha,error FROM runs WHERE id=?`, old.ID).Scan(&data[0], &data[1], &data[2], &data[3], &data[4], &data[5], &data[6], &data[7]); err != nil {
			t.Fatal(err)
		}
		return data
	}
	prior := readOldRun()
	if _, err := a.CorrectTrainingPinLabels(); err != nil {
		t.Fatal(err)
	}
	assertBlocked := func() {
		t.Helper()
		w := request(t, h, "POST", firstURL+"/estimate", map[string]any{"base_revision": caseDetail(t, h, firstCase).Latest}, 409)
		if !strings.Contains(w.Body.String(), "retrain") {
			t.Fatalf("stale run was not explicitly rejected: %s", w.Body.String())
		}
	}
	assertBlocked()
	newRun := freeze()
	assertBlocked()
	succeed(newRun)
	if n, err := a.CorrectTrainingPinLabels(); n != 0 || err != nil {
		t.Fatalf("rerun changed migration boundary: %d, %v", n, err)
	}
	if id, _, err := a.latestModel(); err != nil || id != newRun.ID {
		t.Fatalf("new successful run did not unlock prediction: id=%d err=%v", id, err)
	}
	if readOldRun() != prior {
		t.Fatal("migration modified the historical run row")
	}
}
