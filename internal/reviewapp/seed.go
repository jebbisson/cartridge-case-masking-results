package reviewapp

import (
	"bufio"
	"bytes"
	"database/sql"
	"encoding/json"
	"errors"
	"fmt"
	"path/filepath"
	"regexp"
	"strings"
)

var safeID = regexp.MustCompile(`^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$`)
var shaID = regexp.MustCompile(`^[a-f0-9]{64}$`)

type bundleLabel struct {
	Status  string `json:"status"`
	Origin  string `json:"origin"`
	Rank    string `json:"rank"`
	Mask    string `json:"mask"`
	MaskSHA string `json:"mask_sha256"`
	Start   *Point `json:"start"`
	End     *Point `json:"end"`
}

type manifestCase struct {
	ID       string                 `json:"id"`
	Group    string                 `json:"group_id"`
	Specimen string                 `json:"specimen_id"`
	Split    string                 `json:"split"`
	Width    int                    `json:"width_px"`
	Height   int                    `json:"height_px"`
	Name     string                 `json:"original_filename"`
	Image    string                 `json:"image"`
	SHA      string                 `json:"sha256"`
	Pixels   string                 `json:"decoded_pixel_sha256"`
	Labels   map[string]bundleLabel `json:"labels"`
}

func labelFromBundle(tx *sql.Tx, root, name string, b bundleLabel, w, h int) (Target, error) {
	t, data, err := readBundleLabel(root, name, b, w, h)
	if err != nil {
		return Target{}, err
	}
	if data != nil {
		t.mask, err = saveAsset(tx, data)
	}
	return t, err
}

func readBundleLabel(root, name string, b bundleLabel, w, h int) (Target, []byte, error) {
	t := Target{Status: b.Status, Start: b.Start, End: b.End, Origin: b.Origin, Rank: b.Rank, mask: b.Mask}
	if err := verifyGeometry(name, t, w, h); err != nil {
		return Target{}, nil, err
	}
	if b.Mask == "" {
		return t, nil, nil
	}
	data, err := readPNG(root, b.Mask, b.MaskSHA, w, h, true)
	return t, data, err
}

func (a *App) Seed(path string) error {
	root := filepath.Dir(path)
	b, err := bundleFile(root, filepath.Base(path), 16<<20)
	if err != nil {
		return err
	}
	hash := digest(b)
	tx, err := a.db.Begin()
	if err != nil {
		return err
	}
	defer tx.Rollback()
	var old string
	err = tx.QueryRow(`SELECT digest FROM imports WHERE name='manifest'`).Scan(&old)
	if err == nil {
		if old == hash {
			return nil
		}
		return errors.New("database already seeded from a different manifest")
	}
	if !errors.Is(err, sql.ErrNoRows) {
		return err
	}
	ids := map[string]bool{}
	groups := map[string]string{}
	lines := bufio.NewScanner(bytes.NewReader(b))
	lines.Buffer(make([]byte, 4096), 1<<20)
	for n := 1; lines.Scan(); n++ {
		raw := bytes.TrimSpace(lines.Bytes())
		if len(raw) == 0 {
			continue
		}
		var m manifestCase
		if err := json.Unmarshal(raw, &m); err != nil {
			return fmt.Errorf("manifest line %d: %w", n, err)
		}
		if !safeID.MatchString(m.ID) || ids[m.ID] || strings.TrimSpace(m.Name) == "" || !shaID.MatchString(m.SHA) || !shaID.MatchString(m.Pixels) || (m.Split != "train" && m.Split != "validation" && m.Split != "test") {
			return fmt.Errorf("manifest line %d: invalid identity, digest, name, or split", n)
		}
		ids[m.ID] = true
		for _, k := range []struct{ p, v string }{{"group:", m.Group}, {"specimen:", m.Specimen}, {"sha:", m.SHA}, {"pixels:", fmt.Sprintf("%dx%d:%s", m.Width, m.Height, m.Pixels)}} {
			if k.v == "" || strings.TrimSpace(k.v) != k.v {
				return fmt.Errorf("%s: invalid %s", m.ID, k.p)
			}
			key := k.p + k.v
			if old := groups[key]; old != "" && old != m.Split {
				return fmt.Errorf("%s: %s crosses splits", m.ID, k.p)
			}
			groups[key] = m.Split
		}
		im, err := readPNG(root, m.Image, m.SHA, m.Width, m.Height, false)
		if err != nil {
			return fmt.Errorf("%s: %w", m.ID, err)
		}
		if _, err = saveAsset(tx, im); err != nil {
			return err
		}
		if _, err = tx.Exec(`INSERT INTO cases(id,name,split,group_id,width,height,image,pixels,included) VALUES(?,?,?,?,?,?,?,?,?)`, m.ID, m.Name, m.Split, m.Group, m.Width, m.Height, m.SHA, m.Pixels, m.Split == "train"); err != nil {
			return err
		}
		labels := map[string]Target{}
		eligible := false
		if len(m.Labels) != len(targets) {
			return fmt.Errorf("%s: expected all five targets", m.ID)
		}
		for _, name := range targets {
			in := m.Labels[name]
			if in.Origin != "" && in.Origin != "reference" && in.Origin != "proposal" && in.Origin != "prediction" || in.Status == "present" && in.Origin == "" || in.Mask != "" && !shaID.MatchString(in.MaskSHA) {
				return fmt.Errorf("%s %s: invalid provenance or mask digest", m.ID, name)
			}
			t, err := labelFromBundle(tx, root, name, in, m.Width, m.Height)
			if err != nil {
				return fmt.Errorf("%s %s: %w", m.ID, name, err)
			}
			labels[name] = t
			eligible = eligible || seedLabel(t)
		}
		// Retain the full source record so individual mask provenance is auditable.
		source, err := json.Marshal(struct {
			Type        string          `json:"type"`
			ManifestSHA string          `json:"manifest_sha256"`
			Row         json.RawMessage `json:"manifest_row"`
		}{"manifest", hash, raw})
		if err != nil {
			return err
		}
		if _, err := appendRevision(tx, Case{ID: m.ID}, "source", source, labels, m.Split == "train" && eligible); err != nil {
			return err
		}
	}
	if err := lines.Err(); err != nil {
		return err
	}
	if len(ids) == 0 {
		return errors.New("manifest contains no cases")
	}
	if _, err := tx.Exec(`INSERT INTO imports VALUES('manifest',?)`, hash); err != nil {
		return err
	}
	return tx.Commit()
}

func seedLabel(t Target) bool {
	return t.Origin == "reference" && t.Rank == coarse && (t.Status == "present" || t.Status == "absent")
}
