package reviewapp

import (
	"bufio"
	"bytes"
	"context"
	"database/sql"
	"encoding/json"
	"fmt"
	"net/http"
	"os"
	"path/filepath"
	"time"
)

const proposalSchema = `
CREATE TABLE IF NOT EXISTS imported_proposals (
 case_id TEXT NOT NULL REFERENCES cases(id), fingerprint TEXT NOT NULL,
 revision INTEGER NOT NULL REFERENCES revisions(id), PRIMARY KEY(case_id,fingerprint)
);
`

type proposal struct {
	ImageSHA string                 `json:"image_sha256"`
	CaseID   string                 `json:"case_id"`
	Source   json.RawMessage        `json:"source"`
	ModelSHA string                 `json:"model_sha256"`
	Version  string                 `json:"model_version"`
	Targets  map[string]bundleLabel `json:"targets"`
}

func loadProposal(root, name string) (proposal, []byte, error) {
	b, err := bundleFile(root, name, 1<<20)
	if err != nil {
		return proposal{}, nil, err
	}
	var p proposal
	if err := json.Unmarshal(b, &p); err != nil {
		return proposal{}, nil, err
	}
	var source any
	if err := json.Unmarshal(p.Source, &source); err != nil {
		return proposal{}, nil, fmt.Errorf("proposal source is required")
	}
	switch v := source.(type) {
	case string:
		if v == "" {
			return proposal{}, nil, fmt.Errorf("empty proposal source")
		}
	case map[string]any:
		if len(v) == 0 {
			return proposal{}, nil, fmt.Errorf("empty proposal source")
		}
	default:
		return proposal{}, nil, fmt.Errorf("expected proposal source string or object")
	}
	return p, b, nil
}
func proposalTargets(tx *sql.Tx, root, subdir string, c Case, p proposal, origin string) (map[string]Target, error) {
	if c.image != p.ImageSHA || p.CaseID != "" && p.CaseID != c.ID {
		return nil, fmt.Errorf("proposal image hash or case ID does not match the stored scan")
	}
	if len(p.Targets) != len(targets) {
		return nil, fmt.Errorf("proposal must contain all five targets")
	}
	labels := map[string]Target{}
	for _, name := range targets {
		b, ok := p.Targets[name]
		if !ok {
			return nil, fmt.Errorf("proposal target %s is missing", name)
		}
		if b.Mask != "" {
			if b.Mask == "." || !filepath.IsLocal(b.Mask) {
				return nil, fmt.Errorf("%s: mask must be relative to proposal", name)
			}
			b.Mask = filepath.Join(subdir, b.Mask)
		}
		b.Origin, b.Rank = origin, ""
		l, err := labelFromBundle(tx, root, name, b, c.Width, c.Height)
		if err != nil {
			return nil, fmt.Errorf("%s: %w", name, err)
		}
		labels[name] = l
	}
	return labels, nil
}
func proposalSource(p proposal, raw []byte, run int64, sha string) (json.RawMessage, error) {
	var name string
	_ = json.Unmarshal(p.Source, &name)
	method := "external_proposal"
	if run != 0 {
		method = "local_prediction"
	}
	return json.Marshal(struct {
		Method   string          `json:"method"`
		Model    string          `json:"model,omitempty"`
		Version  string          `json:"version,omitempty"`
		Run      int64           `json:"run_id,omitempty"`
		SHA      string          `json:"model_sha256,omitempty"`
		Proposal json.RawMessage `json:"proposal"`
	}{method, name, p.Version, run, sha, raw})
}

// ImportProposals is atomic: an invalid bundle adds no assets or revisions.
func (a *App) ImportProposals(index string) error {
	root := filepath.Dir(index)
	b, err := bundleFile(root, filepath.Base(index), 4<<20)
	if err != nil {
		return err
	}
	tx, err := a.db.Begin()
	if err != nil {
		return err
	}
	defer tx.Rollback()
	lines := bufio.NewScanner(bytes.NewReader(b))
	lines.Buffer(make([]byte, 2048), 128<<10)
	for n := 1; lines.Scan(); n++ {
		raw := bytes.TrimSpace(lines.Bytes())
		if len(raw) == 0 {
			continue
		}
		var entry struct {
			CaseID string `json:"case_id"`
			Path   string `json:"path"`
		}
		if err := json.Unmarshal(raw, &entry); err != nil {
			return fmt.Errorf("proposal index line %d: %w", n, err)
		}
		c, err := findCase(tx, entry.CaseID)
		if err != nil {
			return fmt.Errorf("proposal index line %d, case %q: %w", n, entry.CaseID, err)
		}
		p, doc, err := loadProposal(root, entry.Path)
		if err != nil {
			return fmt.Errorf("%s: %w", entry.Path, err)
		}
		labels, err := proposalTargets(tx, root, filepath.Dir(entry.Path), c, p, "proposal")
		if err != nil {
			return fmt.Errorf("%s: %w", entry.Path, err)
		}
		var identity bytes.Buffer
		if err := json.Compact(&identity, doc); err != nil {
			return err
		}
		for _, name := range targets {
			identity.WriteString(labels[name].mask)
		}
		fp := digest(identity.Bytes())
		var exists bool
		if err := tx.QueryRow(`SELECT EXISTS(SELECT 1 FROM imported_proposals WHERE case_id=? AND fingerprint=?)`, c.ID, fp).Scan(&exists); err != nil {
			return err
		}
		if exists {
			continue
		}
		s, err := proposalSource(p, doc, 0, "")
		if err != nil {
			return err
		}
		rev, err := appendRevision(tx, c, "proposal", s, labels, false)
		if err != nil {
			return err
		}
		if _, err := tx.Exec(`INSERT INTO imported_proposals VALUES(?,?,?)`, c.ID, fp, rev); err != nil {
			return err
		}
	}
	if err := lines.Err(); err != nil {
		return err
	}
	return tx.Commit()
}

type estimatePreview struct {
	Base    int64                  `json:"base_revision"`
	Run     int64                  `json:"run_id"`
	Targets map[string]reviewLabel `json:"targets"`
}

func (a *App) estimate(w http.ResponseWriter, r *http.Request) {
	var body struct {
		Base int64 `json:"base_revision"`
	}
	if err := payload(w, r, 4096, &body); err != nil {
		handleErrors(w, err)
		return
	}
	if body.Base <= 0 {
		handleErrors(w, bad("base_revision is required"))
		return
	}
	preview, err := a.predict(r.Context(), r.PathValue("id"), body.Base)
	if err != nil {
		handleErrors(w, err)
		return
	}
	respond(w, http.StatusOK, preview)
}
func (a *App) predict(requestCtx context.Context, id string, base int64) (estimatePreview, error) {
	c, err := findCase(a.db, id)
	if err != nil {
		return estimatePreview{}, err
	}
	if c.Latest != base {
		return estimatePreview{}, conflict("stale base revision; reload the case")
	}
	run, sha, err := a.latestModel()
	if err != nil {
		return estimatePreview{}, err
	}
	select {
	case a.estimating <- struct{}{}:
		defer func() { <-a.estimating }()
	default:
		return estimatePreview{}, conflict("an estimate is already running")
	}
	model, err := bundleFile(a.runDir(run), modelFile, 32<<20)
	if err != nil || digest(model) != sha {
		return estimatePreview{}, conflict("the latest model checkpoint is missing or has changed")
	}
	dir, err := os.MkdirTemp(a.dbPath+".runs", "estimate-")
	if err != nil {
		return estimatePreview{}, err
	}
	defer os.RemoveAll(dir)
	img, err := assetBytes(a.db, c.image)
	if err != nil {
		return estimatePreview{}, err
	}
	imagePath := filepath.Join(dir, "scan.png")
	if err := os.WriteFile(imagePath, img, 0600); err != nil {
		return estimatePreview{}, err
	}
	out := filepath.Join(dir, "output")
	ctx, cancel := context.WithTimeout(requestCtx, 2*time.Minute)
	defer cancel()
	stop := context.AfterFunc(a.ctx, cancel)
	defer stop()
	if err := a.worker(ctx, sha, "predict", "--model", filepath.Join(a.runDir(run), modelFile), "--image", imagePath, "--out", out); err != nil {
		return estimatePreview{}, problem{http.StatusBadGateway, err.Error()}
	}
	p, _, err := loadProposal(out, "proposal.json")
	if err != nil {
		return estimatePreview{}, problem{http.StatusBadGateway, fmt.Sprintf("invalid worker proposal: %v", err)}
	}
	if p.ModelSHA != "" && p.ModelSHA != sha {
		return estimatePreview{}, problem{http.StatusBadGateway, "worker checkpoint hash mismatch"}
	}
	labels, err := previewTargets(out, c, p)
	if err != nil {
		return estimatePreview{}, problem{http.StatusBadGateway, fmt.Sprintf("invalid worker proposal: %v", err)}
	}
	current, err := findCase(a.db, id)
	if err != nil {
		return estimatePreview{}, err
	}
	if current.Latest != base {
		return estimatePreview{}, conflict("stale base revision; reload the case")
	}
	return estimatePreview{Base: base, Run: run, Targets: labels}, nil
}

func previewTargets(root string, c Case, p proposal) (map[string]reviewLabel, error) {
	if c.image != p.ImageSHA || p.CaseID != "" && p.CaseID != c.ID || len(p.Targets) != len(targets) {
		return nil, fmt.Errorf("preview does not match the scan or target schema")
	}
	labels := make(map[string]reviewLabel, len(targets))
	for _, name := range targets {
		b, ok := p.Targets[name]
		if !ok {
			return nil, fmt.Errorf("preview target %s is missing", name)
		}
		t, png, err := readBundleLabel(root, name, b, c.Width, c.Height)
		if err != nil {
			return nil, fmt.Errorf("%s: %w", name, err)
		}
		labels[name] = reviewLabel{Status: t.Status, PNG: png, Start: t.Start, End: t.End}
	}
	return labels, nil
}
