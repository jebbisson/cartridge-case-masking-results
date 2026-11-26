package reviewapp

import (
	"bytes"
	"fmt"
	"image"
	"image/color"
	"image/png"
	"net/http"
	"path/filepath"
	"testing"
)

func realApp(t *testing.T, opts Options) (*App, string) {
	requirePilot(t)
	t.Helper()
	path := filepath.Join(t.TempDir(), "review.sqlite")
	a, err := Open(path, opts)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { a.Close() })
	if err := a.Seed(pilot); err != nil {
		t.Fatal(err)
	}
	return a, path
}

type wireLabel struct {
	Status string `json:"status"`
	Mask   []byte `json:"mask_png,omitempty"`
	Start  *Point `json:"start,omitempty"`
	End    *Point `json:"end,omitempty"`
}

func bodyFor(d Detail, approve bool) (map[string]any, map[string]wireLabel) {
	labels := map[string]wireLabel{}
	for name, l := range d.Selected.Targets {
		labels[name] = wireLabel{Status: l.Status, Start: l.Start, End: l.End}
	}
	return map[string]any{"base_revision": d.Latest, "approve": approve, "targets": labels}, labels
}
func editPixel(t *testing.T, b []byte, v uint8) []byte {
	t.Helper()
	im, err := png.Decode(bytes.NewReader(b))
	if err != nil {
		t.Fatal(err)
	}
	g := image.NewGray(im.Bounds())
	for y := 0; y < g.Bounds().Dy(); y++ {
		for x := 0; x < g.Bounds().Dx(); x++ {
			g.Set(x, y, im.At(x, y))
		}
	}
	if v == 255 && g.GrayAt(0, 0).Y == 255 {
		v = 0
	}
	g.SetGray(0, 0, color.Gray{Y: v})
	var out bytes.Buffer
	if err := png.Encode(&out, g); err != nil {
		t.Fatal(err)
	}
	return out.Bytes()
}
func caseDetail(t *testing.T, h http.Handler, id string) Detail {
	t.Helper()
	return parse[Detail](t, request(t, h, "GET", "/api/cases/"+id, nil, 200))
}

func TestRealEditApprovalAndStalePersistence(t *testing.T) {
	a, db := realApp(t, Options{})
	h := a.Handler()
	source := caseDetail(t, h, firstCase)
	originalMask := source.Selected.Targets["breech_face"].MaskURL
	originalBytes := request(t, h, "GET", originalMask, nil, 200).Body.Bytes()
	changed := editPixel(t, originalBytes, 255)
	body, labels := bodyFor(source, false)
	labels["breech_face"] = wireLabel{Status: "present", Mask: changed}
	tail, tip := &Point{1001, 989}, &Point{1006, 990}
	labels[drag] = wireLabel{Status: "present", Start: tail, End: tip}
	draft := parse[Detail](t, request(t, h, "POST", firstURL+"/review", body, 200))
	if draft.Approved != source.Approved || draft.Latest == source.Latest || draft.Selected.Kind != "draft" {
		t.Fatalf("draft changed approval: %+v", draft.Case)
	}
	request(t, h, "POST", firstURL+"/review", body, 409)
	body, labels = bodyFor(draft, true)
	labels[drag] = wireLabel{Status: "present", Start: tip, End: tail}
	approved := parse[Detail](t, request(t, h, "POST", firstURL+"/review", body, 200))
	if approved.Latest != approved.Approved || approved.Latest == draft.Latest {
		t.Fatalf("not approved: %+v", approved.Case)
	}
	if err := a.Close(); err != nil {
		t.Fatal(err)
	}
	a, err := Open(db, Options{})
	if err != nil {
		t.Fatal(err)
	}
	defer a.Close()
	h = a.Handler()
	now := caseDetail(t, h, firstCase)
	if now.Latest != approved.Latest || now.Approved != approved.Approved || len(now.Revisions) != 3 || now.ImageURL != source.ImageURL {
		t.Fatalf("reload lost history: %+v", now.Case)
	}
	arrow := now.Selected.Targets[drag]
	if arrow.Start == nil || arrow.End == nil || *arrow.Start != *tip || *arrow.End != *tail {
		t.Fatalf("arrow order lost: %+v", arrow)
	}
	if got := request(t, h, "GET", now.Selected.Targets["breech_face"].MaskURL, nil, 200).Body.Bytes(); !bytes.Equal(got, changed) {
		t.Fatal("edited mask was not persisted byte for byte")
	}
	hist := parse[Detail](t, request(t, h, "GET", fmt.Sprintf("%s?revision=%d", firstURL, source.Latest), nil, 200))
	if hist.Selected.ID != source.Latest || hist.Selected.Targets["breech_face"].MaskURL != originalMask || hist.Latest != now.Latest {
		t.Fatal("source history changed")
	}
	if got := request(t, h, "GET", originalMask, nil, 200).Body.Bytes(); !bytes.Equal(got, originalBytes) {
		t.Fatal("source bytes changed")
	}
}

func TestReviewRejectsInvalidGeometry(t *testing.T) {
	a, _ := realApp(t, Options{})
	h := a.Handler()
	s := caseDetail(t, h, firstCase)
	b := request(t, h, "GET", s.Selected.Targets["breech_face"].MaskURL, nil, 200).Body.Bytes()
	for _, tc := range []struct {
		name, target string
		label        wireLabel
	}{
		{"non binary", "breech_face", wireLabel{Status: "present", Mask: editPixel(t, b, 127)}},
		{"new mask missing", "aperture_shear", wireLabel{Status: "present"}},
		{"non present with geometry", "breech_face", wireLabel{Status: "indeterminate", Mask: b}},
		{"direction out of bounds", drag, wireLabel{Status: "present", Start: &Point{s.Width, 0}, End: &Point{0, 0}}},
		{"direction zero length", drag, wireLabel{Status: "present", Start: &Point{0, 0}, End: &Point{0, 0}}},
	} {
		t.Run(tc.name, func(t *testing.T) {
			body, labels := bodyFor(s, true)
			labels[tc.target] = tc.label
			request(t, h, "POST", firstURL+"/review", body, 400)
		})
	}
	if d := caseDetail(t, h, firstCase); d.Latest != s.Latest || len(d.Revisions) != 1 {
		t.Fatal("bad review mutated history")
	}
}

func TestTrainingInclusionCannotMoveHoldouts(t *testing.T) {
	a, _ := realApp(t, Options{})
	h := a.Handler()
	for _, included := range []bool{false, true} {
		d := parse[Detail](t, request(t, h, "POST", firstURL+"/inclusion", map[string]bool{"included": included}, 200))
		if d.Included != included || d.Split != "train" || d.Latest != d.Approved {
			t.Fatalf("bad toggle: %+v", d.Case)
		}
	}
	for _, c := range parse[[]Case](t, request(t, h, "GET", "/api/cases", nil, 200)) {
		if c.Split == "train" {
			continue
		}
		url := "/api/cases/" + c.ID
		d := caseDetail(t, h, c.ID)
		if d.Approved != 0 || d.Included {
			t.Fatal("holdout became eligible")
		}
		request(t, h, "POST", url+"/inclusion", map[string]bool{"included": true}, 409)
	}
}
