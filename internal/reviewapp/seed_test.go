package reviewapp

import (
	"bytes"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"testing"
)

// The original research corpus is not a dependency of the public checkout.
var pilot = os.Getenv("REVIEW_TEST_PILOT_MANIFEST")

func requirePilot(t *testing.T) {
	t.Helper()
	if pilot == "" {
		t.Skip("optional research corpus not configured; set REVIEW_TEST_PILOT_MANIFEST to run")
	}
}

func request(t *testing.T, h http.Handler, method, path string, body any, want int) *httptest.ResponseRecorder {
	t.Helper()
	var b bytes.Buffer
	if body != nil {
		if err := json.NewEncoder(&b).Encode(body); err != nil {
			t.Fatal(err)
		}
	}
	req := httptest.NewRequest(method, path, &b)
	if body != nil {
		req.Header.Set("Content-Type", "application/json")
	}
	w := httptest.NewRecorder()
	h.ServeHTTP(w, req)
	if w.Code != want {
		t.Fatalf("%s %s got HTTP %d, want %d: %.800s", method, path, w.Code, want, w.Body.String())
	}
	return w
}

func parse[T any](t *testing.T, w *httptest.ResponseRecorder) T {
	t.Helper()
	var value T
	if err := json.Unmarshal(w.Body.Bytes(), &value); err != nil {
		t.Fatal(err)
	}
	return value
}

const firstCase = "3a23bc0c-4da6-4d8a-88fb-e3c359514673"
const firstURL = "/api/cases/" + firstCase

func TestRealPilotSeedAndReopen(t *testing.T) {
	requirePilot(t)
	db := filepath.Join(t.TempDir(), "review.sqlite")
	a, err := Open(db, Options{})
	if err != nil {
		t.Fatal(err)
	}
	if err := a.Seed(pilot); err != nil {
		t.Fatal(err)
	}
	if err := a.Close(); err != nil {
		t.Fatal(err)
	}
	a, err = Open(db, Options{})
	if err != nil {
		t.Fatal(err)
	}
	defer a.Close()
	h := a.Handler()
	before := parse[Detail](t, request(t, h, "GET", firstURL, nil, 200))
	if err := a.Seed(pilot); err != nil {
		t.Fatal(err)
	}
	cases := parse[[]Case](t, request(t, h, "GET", "/api/cases", nil, 200))
	counts := map[string]int{}
	for _, c := range cases {
		counts[c.Split]++
		if c.Split != "train" && (c.Included || c.Approved != 0) {
			t.Fatalf("holdout seeded eligible: %+v", c)
		}
	}
	if len(cases) != 48 || counts["train"] != 30 || counts["validation"] != 6 || counts["test"] != 12 {
		t.Fatalf("v1 split changed: %v", counts)
	}
	d := parse[Detail](t, request(t, h, "GET", firstURL, nil, 200))
	if d.ID != firstCase || d.Latest != before.Latest || len(d.Revisions) != 1 || d.Approved != d.Latest || d.Width != 2592 || d.Height != 1944 {
		t.Fatalf("incorrect seeded detail: %+v", d)
	}
	path := filepath.Join(filepath.Dir(pilot), "assets", "originals", firstCase+".png")
	want, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	if got := request(t, h, "GET", d.ImageURL, nil, 200).Body.Bytes(); !bytes.Equal(got, want) {
		t.Fatal("original was not preserved byte for byte")
	}
	label := d.Selected.Targets["breech_face"]
	if label.Origin != "reference" || label.Rank != "coarse_baseline_only" {
		t.Fatalf("lost provenance: %+v", label)
	}
	want, err = os.ReadFile(filepath.Join(filepath.Dir(pilot), "assets", "dundee-aligned", firstCase, "breech_face.png"))
	if err != nil {
		t.Fatal(err)
	}
	if got := request(t, h, "GET", label.MaskURL, nil, 200).Body.Bytes(); !bytes.Equal(got, want) {
		t.Fatal("source mask was not preserved byte for byte")
	}
}
