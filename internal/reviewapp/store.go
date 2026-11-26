package reviewapp

import (
	"context"
	"database/sql"
	"encoding/json"
	"errors"
	"fmt"
	"net/url"
	"os"
	"path/filepath"
	"sync"
	"syscall"
	"time"

	_ "github.com/mattn/go-sqlite3"
)

var targets = [...]string{"breech_face", "aperture_shear", "firing_pin_shear", "firing_pin_impression", "firing_pin_drag_direction"}

const drag = "firing_pin_drag_direction"
const coarse = "coarse_baseline_only"

const schema = `
CREATE TABLE IF NOT EXISTS assets (
 digest TEXT PRIMARY KEY, png BLOB NOT NULL
);
CREATE TABLE IF NOT EXISTS cases (
 id TEXT PRIMARY KEY, name TEXT NOT NULL, split TEXT NOT NULL CHECK(split IN ('train','validation','test')),
 group_id TEXT NOT NULL, width INTEGER NOT NULL, height INTEGER NOT NULL,
 image TEXT NOT NULL REFERENCES assets(digest), pixels TEXT NOT NULL, included INTEGER NOT NULL,
 latest INTEGER REFERENCES revisions(id), approved INTEGER REFERENCES revisions(id),
 CHECK (split='train' OR included=0)
);
CREATE TABLE IF NOT EXISTS revisions (
 id INTEGER PRIMARY KEY, case_id TEXT NOT NULL REFERENCES cases(id),
 parent INTEGER REFERENCES revisions(id), kind TEXT NOT NULL, created TEXT NOT NULL,
 source TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS by_case ON revisions(case_id,id);
CREATE TABLE IF NOT EXISTS retired_revision_ids (id INTEGER PRIMARY KEY);
CREATE TABLE IF NOT EXISTS labels (
 revision INTEGER NOT NULL REFERENCES revisions(id), target TEXT NOT NULL, status TEXT NOT NULL,
 mask TEXT REFERENCES assets(digest), start_x INTEGER, start_y INTEGER, end_x INTEGER, end_y INTEGER,
 origin TEXT NOT NULL, rank TEXT NOT NULL,
 PRIMARY KEY(revision,target)
);
CREATE TABLE IF NOT EXISTS imports (name TEXT PRIMARY KEY, digest TEXT NOT NULL);
`

type Options struct{ Web, Python, Worker string }

type App struct {
	db         *sql.DB
	lock       *os.File
	dbPath     string
	opts       Options
	ctx        context.Context
	cancel     context.CancelFunc
	jobs       sync.WaitGroup
	estimating chan struct{}
}

func Open(path string, options Options) (*App, error) {
	abs, err := filepath.Abs(path)
	if err != nil {
		return nil, err
	}
	if options.Python == "" {
		options.Python = "python3"
	}
	if options.Worker == "" {
		options.Worker = "python/multiscale_worker.py"
	}
	options.Worker, err = filepath.Abs(options.Worker)
	if err != nil {
		return nil, err
	}
	// A single app owns the worker artifacts and can recover unfinished runs.
	lock, err := os.OpenFile(abs+".lock", os.O_CREATE|os.O_RDWR, 0600)
	if err != nil {
		return nil, err
	}
	ready := false
	defer func() {
		if !ready {
			lock.Close()
		}
	}()
	if err := syscall.Flock(int(lock.Fd()), syscall.LOCK_EX|syscall.LOCK_NB); err != nil {
		return nil, fmt.Errorf("lock review database: %w", err)
	}
	file, err := os.OpenFile(abs, os.O_CREATE|os.O_RDWR, 0600)
	if err != nil {
		return nil, err
	}
	if err := file.Close(); err != nil {
		return nil, err
	}
	u := url.URL{Scheme: "file", Path: abs, RawQuery: "_foreign_keys=on&_busy_timeout=5000&_journal_mode=WAL&_txlock=immediate"}
	db, err := sql.Open("sqlite3", u.String())
	if err != nil {
		return nil, err
	}
	db.SetMaxOpenConns(1)
	if _, err = db.Exec(schema + runSchema + proposalSchema); err != nil {
		db.Close()
		return nil, err
	}
	if _, err = db.Exec(`UPDATE runs SET status='failed',finished=?,error='training interrupted by app shutdown' WHERE status='running'`, time.Now().UTC().Format(time.RFC3339Nano)); err != nil {
		db.Close()
		return nil, err
	}
	ctx, cancel := context.WithCancel(context.Background())
	ready = true
	return &App{db: db, lock: lock, dbPath: abs, opts: options, ctx: ctx, cancel: cancel, estimating: make(chan struct{}, 1)}, nil
}
func (a *App) Close() error {
	a.cancel()
	a.jobs.Wait()
	return errors.Join(a.db.Close(), a.lock.Close())
}

type Case struct {
	ID       string `json:"id"`
	Name     string `json:"name"`
	GroupID  string `json:"group_id"`
	Split    string `json:"split"`
	Included bool   `json:"included"`
	Width    int    `json:"width"`
	Height   int    `json:"height"`
	Latest   int64  `json:"latest"`
	Approved int64  `json:"approved"`
	image    string
}

type Point [2]int

func (p *Point) UnmarshalJSON(data []byte) error {
	var v []*int
	if err := json.Unmarshal(data, &v); err != nil || len(v) != 2 || v[0] == nil || v[1] == nil {
		return errors.New("point must be [x,y] with integer coordinates")
	}
	*p = Point{*v[0], *v[1]}
	return nil
}

type Target struct {
	Status  string `json:"status"`
	MaskURL string `json:"mask_url,omitempty"`
	Start   *Point `json:"start,omitempty"`
	End     *Point `json:"end,omitempty"`
	Origin  string `json:"origin,omitempty"`
	Rank    string `json:"rank,omitempty"`
	mask    string
}

type Revision struct {
	ID      int64             `json:"id"`
	Kind    string            `json:"kind"`
	Created string            `json:"created"`
	Targets map[string]Target `json:"targets"`
	Source  json.RawMessage   `json:"source"`
	Parent  int64             `json:"parent,omitempty"`
}

type Detail struct {
	Case
	ImageURL  string     `json:"image_url"`
	Revisions []Revision `json:"revisions"`
	Selected  Revision   `json:"selected"`
}

type queryer interface {
	Query(string, ...any) (*sql.Rows, error)
	QueryRow(string, ...any) *sql.Row
}
type scanner interface{ Scan(...any) error }

const caseFields = `id,name,group_id,split,included,width,height,coalesce(latest,0),coalesce(approved,0),image`

func scanCase(s scanner) (c Case, err error) {
	err = s.Scan(&c.ID, &c.Name, &c.GroupID, &c.Split, &c.Included, &c.Width, &c.Height, &c.Latest, &c.Approved, &c.image)
	return
}
func listCases(q queryer) ([]Case, error) {
	rows, err := q.Query(`SELECT ` + caseFields + ` FROM cases ORDER BY id`)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	cs := []Case{}
	for rows.Next() {
		c, err := scanCase(rows)
		if err != nil {
			return nil, err
		}
		cs = append(cs, c)
	}
	return cs, rows.Err()
}
func findCase(q queryer, id string) (Case, error) {
	return scanCase(q.QueryRow(`SELECT `+caseFields+` FROM cases WHERE id=?`, id))
}
func assetURL(digest string) string { return "/api/assets/" + digest }
func readLabels(q queryer, id int64) (map[string]Target, error) {
	rows, err := q.Query(`SELECT target,status,coalesce(mask,''),start_x,start_y,end_x,end_y,origin,rank FROM labels WHERE revision=?`, id)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	result := map[string]Target{}
	for rows.Next() {
		var name string
		var l Target
		var x1, y1, x2, y2 sql.NullInt64
		if err := rows.Scan(&name, &l.Status, &l.mask, &x1, &y1, &x2, &y2, &l.Origin, &l.Rank); err != nil {
			return nil, err
		}
		if l.mask != "" {
			l.MaskURL = assetURL(l.mask)
		}
		if x1.Valid {
			l.Start = &Point{int(x1.Int64), int(y1.Int64)}
		}
		if x2.Valid {
			l.End = &Point{int(x2.Int64), int(y2.Int64)}
		}
		result[name] = l
	}
	return result, rows.Err()
}
func detail(q queryer, id string, selected int64) (Detail, error) {
	c, err := findCase(q, id)
	if err != nil {
		return Detail{}, err
	}
	d := Detail{Case: c, ImageURL: assetURL(c.image), Revisions: []Revision{}}
	if selected == 0 {
		selected = c.Latest
	}
	rows, err := q.Query(`SELECT id,kind,created,source,coalesce(parent,0) FROM revisions WHERE case_id=? ORDER BY id DESC`, id)
	if err != nil {
		return Detail{}, err
	}
	defer rows.Close()
	for rows.Next() {
		var v Revision
		var raw string
		if err := rows.Scan(&v.ID, &v.Kind, &v.Created, &raw, &v.Parent); err != nil {
			return Detail{}, err
		}
		v.Source = json.RawMessage(raw)
		d.Revisions = append(d.Revisions, v)
	}
	if err := rows.Err(); err != nil {
		return Detail{}, err
	}
	for i, v := range d.Revisions {
		v.Targets, err = readLabels(q, v.ID)
		if err != nil {
			return Detail{}, err
		}
		d.Revisions[i] = v
		if v.ID == selected {
			d.Selected = v
		}
	}
	if d.Selected.ID == 0 {
		return Detail{}, sql.ErrNoRows
	}
	return d, nil
}

func appendRevision(tx *sql.Tx, c Case, kind string, source json.RawMessage, labeled map[string]Target, approve bool) (int64, error) {
	// Retired IDs must never resolve to a different revision in stale clients.
	result, err := tx.Exec(`INSERT INTO revisions(id,case_id,parent,kind,created,source)
		VALUES(max(coalesce((SELECT max(id) FROM revisions),0),
		           coalesce((SELECT max(id) FROM retired_revision_ids),0))+1,?,nullif(?,0),?,?,?)`,
		c.ID, c.Latest, kind, time.Now().UTC().Format(time.RFC3339Nano), string(source))
	if err != nil {
		return 0, err
	}
	revision, err := result.LastInsertId()
	if err != nil {
		return 0, err
	}
	for _, name := range targets {
		l, ok := labeled[name]
		if !ok {
			return 0, fmt.Errorf("missing target: %s", name)
		}
		var x1, y1, x2, y2 any
		if l.Start != nil {
			x1, y1 = l.Start[0], l.Start[1]
		}
		if l.End != nil {
			x2, y2 = l.End[0], l.End[1]
		}
		if _, err := tx.Exec(`INSERT INTO labels VALUES(?,?,?,nullif(?,''),?,?,?,?,?,?)`, revision, name, l.Status, l.mask, x1, y1, x2, y2, l.Origin, l.Rank); err != nil {
			return 0, err
		}
	}
	if _, err := tx.Exec(`UPDATE cases SET latest=?,approved=CASE WHEN ? THEN ? ELSE approved END WHERE id=?`, revision, approve, revision, c.ID); err != nil {
		return 0, err
	}
	return revision, nil
}
