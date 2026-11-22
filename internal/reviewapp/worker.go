package reviewapp

import (
	"bytes"
	"context"
	"database/sql"
	"encoding/json"
	"errors"
	"fmt"
	"image"
	"image/color"
	"image/png"
	"log"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"strconv"
	"strings"
	"time"
)

const runSchema = `
CREATE TABLE IF NOT EXISTS runs (
 id INTEGER PRIMARY KEY, status TEXT NOT NULL CHECK(status IN ('running','failed','succeeded')),
 fingerprint TEXT NOT NULL, snapshot TEXT NOT NULL, started TEXT NOT NULL, finished TEXT,
 manifest_sha TEXT NOT NULL DEFAULT '', checkpoint_sha TEXT NOT NULL DEFAULT '', error TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS import_run_cutoffs (
 import_name TEXT PRIMARY KEY REFERENCES imports(name), last_run INTEGER NOT NULL
);
`
const modelFile = "checkpoint.json"

type Run struct {
	ID     int64  `json:"id"`
	Status string `json:"status"`
	Model  string `json:"model,omitempty"`
	Error  string `json:"error,omitempty"`
}

func (a *App) runDir(id int64) string {
	return filepath.Join(a.dbPath+".runs", strconv.FormatInt(id, 10))
}
func modelName(id int64) string {
	return filepath.ToSlash(filepath.Join(strconv.FormatInt(id, 10), modelFile))
}

func (a *App) runs(w http.ResponseWriter, _ *http.Request) {
	rows, err := a.db.Query(`SELECT id,status,error FROM runs ORDER BY id DESC`)
	if err != nil {
		handleErrors(w, err)
		return
	}
	defer rows.Close()
	result := []Run{}
	for rows.Next() {
		var v Run
		if err := rows.Scan(&v.ID, &v.Status, &v.Error); err != nil {
			handleErrors(w, err)
			return
		}
		if v.Status == "succeeded" {
			v.Model = modelName(v.ID)
		}
		result = append(result, v)
	}
	if err := rows.Err(); err != nil {
		handleErrors(w, err)
		return
	}
	respond(w, 200, result)
}
func (a *App) startRun(w http.ResponseWriter, r *http.Request) {
	var in struct {
		Fingerprint string `json:"fingerprint"`
	}
	if err := payload(w, r, 4096, &in); err != nil {
		handleErrors(w, err)
		return
	}
	if !shaID.MatchString(in.Fingerprint) {
		handleErrors(w, bad("fingerprint must be a SHA-256 digest"))
		return
	}
	run, ms, err := a.freeze(in.Fingerprint)
	if err != nil {
		handleErrors(w, err)
		return
	}
	a.jobs.Add(1)
	go func() { defer a.jobs.Done(); a.train(run.ID, ms) }()
	respond(w, 202, run)
}
func (a *App) freeze(fp string) (Run, []member, error) {
	tx, err := a.db.Begin()
	if err != nil {
		return Run{}, nil, err
	}
	defer tx.Rollback()
	ms, raw, got, err := snapshot(tx)
	if err != nil {
		return Run{}, nil, err
	}
	if got != fp {
		return Run{}, nil, conflict("training snapshot changed; refresh the preview")
	}
	if len(ms) == 0 {
		return Run{}, nil, conflict("there are no eligible approved training cases")
	}
	var active bool
	if err := tx.QueryRow(`SELECT EXISTS(SELECT 1 FROM runs WHERE status='running')`).Scan(&active); err != nil {
		return Run{}, nil, err
	}
	if active {
		return Run{}, nil, conflict("a training run is already active")
	}
	result, err := tx.Exec(`INSERT INTO runs(status,fingerprint,snapshot,started) VALUES('running',?,?,?)`, fp, string(raw), time.Now().UTC().Format(time.RFC3339Nano))
	if err != nil {
		return Run{}, nil, err
	}
	id, err := result.LastInsertId()
	if err != nil {
		return Run{}, nil, err
	}
	return Run{ID: id, Status: "running"}, ms, tx.Commit()
}
func (a *App) train(id int64, ms []member) {
	dir := a.runDir(id)
	manifestSHA, checkpointSHA, err := a.buildModel(dir, ms)
	status, message := "succeeded", ""
	if err != nil {
		status, message = "failed", err.Error()
		if len(message) > 1200 {
			message = message[len(message)-1200:]
		}
	}
	if _, err := a.db.Exec(`UPDATE runs SET status=?,finished=?,manifest_sha=?,checkpoint_sha=?,error=? WHERE id=? AND status='running'`, status, time.Now().UTC().Format(time.RFC3339Nano), manifestSHA, checkpointSHA, message, id); err != nil {
		log.Printf("persist training run %d: %v", id, err)
	}
}
func (a *App) buildModel(dir string, ms []member) (manifestSHA, checkpointSHA string, err error) {
	if err = os.MkdirAll(filepath.Join(dir, "assets"), 0700); err != nil {
		return
	}
	manifest := filepath.Join(dir, "manifest.jsonl")
	manifestSHA, err = a.exportManifest(dir, ms)
	if err != nil {
		return
	}
	ctx, cancel := context.WithTimeout(a.ctx, 10*time.Minute)
	defer cancel()
	if err = a.worker(ctx, "", "train", "--manifest", manifest, "--out", filepath.Join(dir, modelFile)); err != nil {
		return
	}
	var b []byte
	b, err = bundleFile(dir, modelFile, 32<<20)
	if err != nil {
		return
	}
	if len(b) == 0 {
		return manifestSHA, "", errors.New("worker produced an empty checkpoint")
	}
	return manifestSHA, digest(b), nil
}

type trainRow struct {
	ID       string                   `json:"id"`
	Split    string                   `json:"split"`
	Image    string                   `json:"image"`
	Width    int                      `json:"width"`
	Height   int                      `json:"height"`
	Revision int64                    `json:"revision"`
	Labels   map[string]trainingLabel `json:"labels"`
}

func (a *App) exportManifest(dir string, ms []member) (string, error) {
	var out bytes.Buffer
	enc := json.NewEncoder(&out)
	done := map[string]bool{}
	materialize := func(key string, mask bool) (string, error) {
		prefix := "image-"
		if mask {
			prefix = "mask-"
		}
		rel := "assets/" + prefix + key + ".png"
		if done[rel] {
			return rel, nil
		}
		b, err := assetBytes(a.db, key)
		if err != nil {
			return "", err
		}
		if mask {
			b, err = grayscaleMask(b)
			if err != nil {
				return "", err
			}
		}
		if err := os.WriteFile(filepath.Join(dir, rel), b, 0600); err != nil {
			return "", err
		}
		done[rel] = true
		return rel, nil
	}
	for _, m := range ms {
		path, err := materialize(m.Image, false)
		if err != nil {
			return "", err
		}
		labels := map[string]trainingLabel{}
		for k, l := range m.Labels {
			if l.Mask != "" {
				l.Mask, err = materialize(l.Mask, true)
				if err != nil {
					return "", err
				}
			}
			labels[k] = l
		}
		if err := enc.Encode(trainRow{m.ID, "train", path, m.Width, m.Height, m.Revision, labels}); err != nil {
			return "", err
		}
	}
	if err := os.WriteFile(filepath.Join(dir, "manifest.jsonl"), out.Bytes(), 0600); err != nil {
		return "", err
	}
	return digest(out.Bytes()), nil
}

// Leave the database asset unchanged. The worker accepts grayscale PNGs only.
func grayscaleMask(data []byte) ([]byte, error) {
	cfg, err := png.DecodeConfig(bytes.NewReader(data))
	if err != nil {
		return nil, err
	}
	// Grayscale (including packed 1-bit) assets already usable by Pillow.
	if cfg.ColorModel == color.GrayModel && len(data) > 24 && data[24] <= 8 {
		return data, nil
	}
	im, err := png.Decode(bytes.NewReader(data))
	if err != nil {
		return nil, err
	}
	gray := image.NewGray(im.Bounds())
	for y := 0; y < im.Bounds().Dy(); y++ {
		for x := 0; x < im.Bounds().Dx(); x++ {
			gray.Set(x, y, im.At(x, y))
		}
	}
	var out bytes.Buffer
	if err := png.Encode(&out, gray); err != nil {
		return nil, err
	}
	return out.Bytes(), nil
}

type outputTail struct{ text string }

func (t *outputTail) Write(b []byte) (int, error) {
	const limit = 4096
	n := len(b)
	if n >= limit {
		t.text = string(b[n-limit:])
		return n, nil
	}
	if keep := limit - n; len(t.text) > keep {
		t.text = t.text[len(t.text)-keep:]
	}
	t.text += string(b)
	return n, nil
}
func (a *App) worker(ctx context.Context, modelSHA string, args ...string) error {
	cmd := exec.CommandContext(ctx, a.opts.Python, append([]string{"-E", a.opts.Worker}, args...)...)
	cmd.Env = append(os.Environ(), "REVIEWAPP_MODEL_SHA256="+modelSHA)
	tail := new(outputTail)
	cmd.Stdout = tail
	cmd.Stderr = tail
	cmd.WaitDelay = 2 * time.Second
	if err := cmd.Run(); err != nil {
		if ctx.Err() != nil {
			return fmt.Errorf("%s: %w", args[0], ctx.Err())
		}
		return fmt.Errorf("%s worker failed: %w: %s", args[0], err, strings.TrimSpace(tail.text))
	}
	return nil
}

func (a *App) latestModel() (int64, string, error) {
	var id int64
	var sha string
	var corrected bool
	var cutoff sql.NullInt64
	err := a.db.QueryRow(`SELECT r.id,r.checkpoint_sha,i.name IS NOT NULL,c.last_run FROM runs r
		LEFT JOIN imports i ON i.name=?
		LEFT JOIN import_run_cutoffs c ON c.import_name=i.name
		WHERE r.status='succeeded' ORDER BY r.id DESC LIMIT 1`, pinLabelMigration).Scan(&id, &sha, &corrected, &cutoff)
	if errors.Is(err, sql.ErrNoRows) {
		err = conflict("no trained model is available")
	}
	if err == nil && corrected && (!cutoff.Valid || id <= cutoff.Int64) {
		return 0, "", conflict("retrain on the corrected training pin labels before running an estimate")
	}
	return id, sha, err
}
