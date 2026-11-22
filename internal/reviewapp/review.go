package reviewapp

import (
	"encoding/json"
	"fmt"
	"net/http"
)

type reviewLabel struct {
	Status string `json:"status"`
	PNG    []byte `json:"mask_png"`
	Start  *Point `json:"start"`
	End    *Point `json:"end"`
}
type reviewRequest struct {
	Base    int64                  `json:"base_revision"`
	Approve *bool                  `json:"approve"`
	Targets map[string]reviewLabel `json:"targets"`
}

func (a *App) review(w http.ResponseWriter, r *http.Request) {
	var in reviewRequest
	if err := payload(w, r, 64<<20, &in); err != nil {
		handleErrors(w, err)
		return
	}
	d, err := a.saveReview(r.PathValue("id"), in)
	finishDetail(w, d, err)
}
func (a *App) saveReview(id string, in reviewRequest) (Detail, error) {
	if in.Base <= 0 || in.Approve == nil || len(in.Targets) != len(targets) {
		return Detail{}, bad("base_revision, approve and exactly five targets are required")
	}
	tx, err := a.db.Begin()
	if err != nil {
		return Detail{}, err
	}
	defer tx.Rollback()
	c, err := findCase(tx, id)
	if err != nil {
		return Detail{}, err
	}
	if c.Latest != in.Base {
		return Detail{}, conflict("stale base revision; reload the case")
	}
	base, err := readLabels(tx, in.Base)
	if err != nil {
		return Detail{}, err
	}
	labels := map[string]Target{}
	for _, name := range targets {
		v, ok := in.Targets[name]
		if !ok {
			return Detail{}, bad("missing target: " + name)
		}
		previous := base[name]
		l := Target{Status: v.Status, Start: v.Start, End: v.End}
		if v.PNG != nil {
			l.mask = digest(v.PNG)
		} else if v.Status == "present" && name != drag && previous.Status == "present" {
			l.mask = previous.mask
		}
		if err := verifyGeometry(name, l, c.Width, c.Height); err != nil {
			return Detail{}, bad(fmt.Sprintf("%s: %v", name, err))
		}
		if v.PNG != nil {
			if err := validPNG(v.PNG, c.Width, c.Height, true); err != nil {
				return Detail{}, bad(fmt.Sprintf("%s: %v", name, err))
			}
			if _, err := saveAsset(tx, v.PNG); err != nil {
				return Detail{}, err
			}
		}
		if sameGeometry(l, previous) {
			l.Origin, l.Rank = previous.Origin, previous.Rank
		} else {
			l.Origin = "review"
		}
		if *in.Approve && (l.Status == "present" || l.Status == "absent") && !seedLabel(l) {
			l.Origin, l.Rank = "review", ""
		}
		labels[name] = l
	}
	kind := "draft"
	if *in.Approve {
		kind = "approved"
	}
	if _, err = appendRevision(tx, c, kind, json.RawMessage(`{"type":"local_review"}`), labels, *in.Approve); err != nil {
		return Detail{}, err
	}
	d, err := detail(tx, id, 0)
	if err != nil {
		return Detail{}, err
	}
	return d, tx.Commit()
}
func samePoint(a, b *Point) bool { return a == nil && b == nil || a != nil && b != nil && *a == *b }
func sameGeometry(a, b Target) bool {
	return a.Status == b.Status && a.mask == b.mask && samePoint(a.Start, b.Start) && samePoint(a.End, b.End)
}

func finishDetail(w http.ResponseWriter, d Detail, err error) {
	if err != nil {
		handleErrors(w, err)
		return
	}
	respond(w, http.StatusOK, d)
}
func (a *App) inclusion(w http.ResponseWriter, r *http.Request) {
	var in struct {
		Included *bool `json:"included"`
	}
	if err := payload(w, r, 4096, &in); err != nil {
		handleErrors(w, err)
		return
	}
	if in.Included == nil {
		handleErrors(w, bad("included is required"))
		return
	}
	d, err := a.setInclusion(r.PathValue("id"), *in.Included)
	finishDetail(w, d, err)
}
func (a *App) setInclusion(id string, included bool) (Detail, error) {
	tx, err := a.db.Begin()
	if err != nil {
		return Detail{}, err
	}
	defer tx.Rollback()
	c, err := findCase(tx, id)
	if err != nil {
		return Detail{}, err
	}
	if c.Split != "train" && included {
		return Detail{}, conflict("validation and test cases cannot be included in training")
	}
	if _, err := tx.Exec(`UPDATE cases SET included=? WHERE id=?`, included, id); err != nil {
		return Detail{}, err
	}
	d, err := detail(tx, id, 0)
	if err != nil {
		return Detail{}, err
	}
	return d, tx.Commit()
}
