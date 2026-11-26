package reviewapp

import (
	"bytes"
	"encoding/json"
	"mime/multipart"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"testing"
)

func uploadResponse(t *testing.T, h http.Handler, field, group string, png []byte, want int) *httptest.ResponseRecorder {
	t.Helper()
	var b bytes.Buffer
	m := multipart.NewWriter(&b)
	for k, v := range map[string]string{"name": "Weller test intake", "group_id": group} {
		if err := m.WriteField(k, v); err != nil {
			t.Fatal(err)
		}
	}
	f, err := m.CreateFormFile(field, "scan.png")
	if err != nil {
		t.Fatal(err)
	}
	if _, err := f.Write(png); err != nil {
		t.Fatal(err)
	}
	if err := m.Close(); err != nil {
		t.Fatal(err)
	}
	r := httptest.NewRequest("POST", "/api/cases", &b)
	r.Header.Set("Content-Type", m.FormDataContentType())
	w := httptest.NewRecorder()
	h.ServeHTTP(w, r)
	if w.Code != want {
		t.Fatalf("upload %q got %d, expected %d: %.500s", group, w.Code, want, w.Body.String())
	}
	return w
}
func TestUploadRejectsDuplicateAndHeldOutGroup(t *testing.T) {
	a, _ := realApp(t, Options{})
	h := a.Handler()
	source := caseDetail(t, h, firstCase)
	b := request(t, h, "GET", source.ImageURL, nil, 200).Body.Bytes()
	var group string
	if err := a.db.QueryRow(`SELECT group_id FROM cases WHERE split='test' LIMIT 1`).Scan(&group); err != nil {
		t.Fatal(err)
	}
	uploadResponse(t, h, "file", group, b, 409)
	d := uploadResponse(t, h, "file", "independent-source", b, 409)
	if !bytes.Contains(d.Body.Bytes(), []byte("already exists")) {
		t.Fatal("duplicate not identified")
	}
	w := uploadResponse(t, h, "file", group, b, 409)
	if !bytes.Contains(w.Body.Bytes(), []byte("held out")) {
		t.Fatal("held-out group not identified")
	}
	uploadResponse(t, h, "file", "", b, 400)
}

func TestUploadNewRealScanStartsUnreviewed(t *testing.T) {
	b, err := os.ReadFile(filepath.Join("..", "..", "data", "staging", "weller", "TWRBF01-01.png"))
	if os.IsNotExist(err) {
		t.Skip("additional real Weller scan is not staged")
	}
	if err != nil {
		t.Fatal(err)
	}
	a, _ := realApp(t, Options{})
	h := a.Handler()
	before := preview(t, h)
	d := parse[Detail](t, uploadResponse(t, h, "image", "weller-TW01", b, 201))
	if d.Split != "train" || !d.Included || d.Approved != 0 || len(d.Selected.Targets) != 5 {
		t.Fatalf("new scan not unreviewed: %+v", d.Case)
	}
	if after := preview(t, h); after.Fingerprint != before.Fingerprint {
		t.Fatal("unreviewed upload entered training")
	}
	if !bytes.Equal(request(t, h, "GET", d.ImageURL, nil, 200).Body.Bytes(), b) {
		t.Fatal("upload changed original bytes")
	}
	uploadResponse(t, h, "file", "weller-TW01", b, 409)
}

func TestImportRealExternalProposalIsHashBoundAndIdempotent(t *testing.T) {
	path := filepath.Join("..", "..", "data", "staging", "vision-calibration-v1", "astra-3a23bc0c", "proposal.json")
	raw, err := os.ReadFile(path)
	if os.IsNotExist(err) {
		t.Skip("real Astra proposals not staged")
	}
	if err != nil {
		t.Fatal(err)
	}
	a, _ := realApp(t, Options{})
	h := a.Handler()
	before := caseDetail(t, h, firstCase)
	p := preview(t, h)
	dir := t.TempDir()
	index := filepath.Join(dir, "index.jsonl")
	if err := os.WriteFile(index, []byte(`{"case_id":"`+firstCase+`","path":"proposal.json"}`+"\n"), 0600); err != nil {
		t.Fatal(err)
	}
	var doc map[string]any
	if err := json.Unmarshal(raw, &doc); err != nil {
		t.Fatal(err)
	}
	doc["image_sha256"] = string(bytes.Repeat([]byte{'0'}, 64))
	badRaw, err := json.Marshal(doc)
	if err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(dir, "proposal.json"), badRaw, 0600); err != nil {
		t.Fatal(err)
	}
	if err := a.ImportProposals(index); err == nil {
		t.Fatal("accepted mismatched source scan digest")
	}
	if d := caseDetail(t, h, firstCase); d.Latest != before.Latest {
		t.Fatal("rejected proposal mutated history")
	}
	if err := os.WriteFile(filepath.Join(dir, "proposal.json"), raw, 0600); err != nil {
		t.Fatal(err)
	}
	entries, err := os.ReadDir(filepath.Dir(path))
	if err != nil {
		t.Fatal(err)
	}
	for _, e := range entries {
		if filepath.Ext(e.Name()) != ".png" {
			continue
		}
		b, err := os.ReadFile(filepath.Join(filepath.Dir(path), e.Name()))
		if err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(filepath.Join(dir, e.Name()), b, 0600); err != nil {
			t.Fatal(err)
		}
	}
	for range 2 {
		if err := a.ImportProposals(index); err != nil {
			t.Fatal(err)
		}
	}
	d := caseDetail(t, h, firstCase)
	if d.Approved != before.Approved || len(d.Revisions) != 2 || d.Selected.Kind != "proposal" || d.Selected.Targets["breech_face"].Origin != "proposal" {
		t.Fatalf("incorrect imported history: %+v", d.Case)
	}
	if !bytes.Contains(d.Selected.Source, []byte("gpt-6.2-astra")) || preview(t, h).Fingerprint != p.Fingerprint {
		t.Fatal("lost provider metadata or included external proposal in training")
	}
}
