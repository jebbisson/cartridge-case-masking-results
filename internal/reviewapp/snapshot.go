package reviewapp

import (
	"database/sql"
	"encoding/json"
	"errors"
	"net/http"
	"sort"
)

type trainingLabel struct {
	Status string `json:"status"`
	Mask   string `json:"mask,omitempty"`
	Start  *Point `json:"start,omitempty"`
	End    *Point `json:"end,omitempty"`
	Origin string `json:"origin,omitempty"`
	Rank   string `json:"rank,omitempty"`
}
type member struct {
	ID       string                   `json:"id"`
	Name     string                   `json:"name"`
	Revision int64                    `json:"revision"`
	Image    string                   `json:"image_digest"`
	Width    int                      `json:"width"`
	Height   int                      `json:"height"`
	Labels   map[string]trainingLabel `json:"labels"`
}
type Preview struct {
	Fingerprint string   `json:"fingerprint"`
	Added       []Change `json:"added"`
	Corrected   []Change `json:"corrected"`
	Excluded    []Change `json:"excluded"`
	Unchanged   int      `json:"unchanged"`
	Total       int      `json:"total"`
}
type Change struct {
	ID               string   `json:"id"`
	Name             string   `json:"name"`
	Targets          []string `json:"targets,omitempty"`
	PreviousRevision int64    `json:"previous_revision,omitempty"`
	Revision         int64    `json:"revision,omitempty"`
}

func membership(tx *sql.Tx) ([]member, error) {
	rows, err := tx.Query(`SELECT cases.id,name,approved,image,width,height,kind FROM cases JOIN revisions ON revisions.id=approved WHERE split='train' AND included=1 ORDER BY cases.id`)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	type candidate struct {
		m    member
		kind string
	}
	var candidates []candidate
	for rows.Next() {
		var c candidate
		if err := rows.Scan(&c.m.ID, &c.m.Name, &c.m.Revision, &c.m.Image, &c.m.Width, &c.m.Height, &c.kind); err != nil {
			return nil, err
		}
		candidates = append(candidates, c)
	}
	if err := rows.Err(); err != nil {
		return nil, err
	}
	result := []member{}
	for _, c := range candidates {
		labels, err := readLabels(tx, c.m.Revision)
		if err != nil {
			return nil, err
		}
		haveKnown := false
		c.m.Labels = map[string]trainingLabel{}
		for _, name := range targets {
			t := labels[name]
			l := trainingLabel{Status: "not_annotated"}
			known := t.Status == "present" || t.Status == "absent"
			if known && (seedLabel(t) || c.kind == "approved" && t.Origin == "review") {
				l = trainingLabel{Status: t.Status, Mask: t.mask, Start: t.Start, End: t.End, Origin: t.Origin, Rank: t.Rank}
				haveKnown = true
			}
			c.m.Labels[name] = l
		}
		if haveKnown {
			result = append(result, c.m)
		}
	}
	return result, nil
}
func snapshot(tx *sql.Tx) ([]member, []byte, string, error) {
	ms, err := membership(tx)
	if err != nil {
		return nil, nil, "", err
	}
	raw, err := json.Marshal(ms)
	if err != nil {
		return nil, nil, "", err
	}
	return ms, raw, digest(raw), nil
}
func getPreview(tx *sql.Tx) (Preview, error) {
	now, _, fp, err := snapshot(tx)
	if err != nil {
		return Preview{}, err
	}
	var baseRaw string
	err = tx.QueryRow(`SELECT snapshot FROM runs WHERE status='succeeded' ORDER BY id DESC LIMIT 1`).Scan(&baseRaw)
	if err != nil && !errors.Is(err, sql.ErrNoRows) {
		return Preview{}, err
	}
	var base []member
	if err == nil {
		if err := json.Unmarshal([]byte(baseRaw), &base); err != nil {
			return Preview{}, err
		}
	}
	return compareSnapshots(now, base, fp), nil
}
func compareSnapshots(now, base []member, fp string) Preview {
	p := Preview{Fingerprint: fp, Total: len(now), Added: []Change{}, Corrected: []Change{}, Excluded: []Change{}}
	prev := map[string]member{}
	for _, m := range base {
		prev[m.ID] = m
	}
	for _, m := range now {
		prior, exists := prev[m.ID]
		delete(prev, m.ID)
		change := Change{ID: m.ID, Name: m.Name, Revision: m.Revision, PreviousRevision: prior.Revision}
		for _, name := range targets {
			b, a := prior.Labels[name], m.Labels[name]
			if !exists && a.Status != "not_annotated" || exists && (b.Status != a.Status || b.Mask != a.Mask || b.Rank != a.Rank || !samePoint(b.Start, a.Start) || !samePoint(b.End, a.End)) {
				change.Targets = append(change.Targets, name)
			}
		}
		if !exists {
			p.Added = append(p.Added, change)
		} else if len(change.Targets) > 0 {
			p.Corrected = append(p.Corrected, change)
		} else {
			p.Unchanged++
		}
	}
	for _, m := range prev {
		p.Excluded = append(p.Excluded, Change{ID: m.ID, Name: m.Name, PreviousRevision: m.Revision})
	}
	sort.Slice(p.Excluded, func(i, j int) bool { return p.Excluded[i].ID < p.Excluded[j].ID })
	return p
}
func (a *App) preview(w http.ResponseWriter, _ *http.Request) {
	tx, err := a.db.Begin()
	if err != nil {
		handleErrors(w, err)
		return
	}
	defer tx.Rollback()
	p, err := getPreview(tx)
	if err != nil {
		handleErrors(w, err)
		return
	}
	if err := tx.Commit(); err != nil {
		handleErrors(w, err)
		return
	}
	respond(w, 200, p)
}
