package reviewapp

import (
	"database/sql"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"log"
	"mime"
	"net/http"
	"strconv"
)

type problem struct {
	status  int
	message string
}

func (p problem) Error() string     { return p.message }
func bad(message string) error      { return problem{http.StatusBadRequest, message} }
func conflict(message string) error { return problem{http.StatusConflict, message} }

func handleErrors(w http.ResponseWriter, err error) {
	var p problem
	switch {
	case errors.As(err, &p):
	case errors.Is(err, sql.ErrNoRows):
		p = problem{http.StatusNotFound, "not found"}
	default:
		log.Printf("review app: %v", err)
		p = problem{http.StatusInternalServerError, "internal error"}
	}
	respond(w, p.status, map[string]string{"error": p.message})
}
func respond(w http.ResponseWriter, status int, value any) {
	w.Header().Set("Content-Type", "application/json")
	w.Header().Set("Cache-Control", "no-store")
	w.WriteHeader(status)
	if err := json.NewEncoder(w).Encode(value); err != nil {
		log.Printf("write response: %v", err)
	}
}
func payload(w http.ResponseWriter, r *http.Request, max int64, dst any) error {
	media, _, _ := mime.ParseMediaType(r.Header.Get("Content-Type"))
	if media != "application/json" {
		return problem{http.StatusUnsupportedMediaType, "expected application/json"}
	}
	d := json.NewDecoder(http.MaxBytesReader(w, r.Body, max))
	d.DisallowUnknownFields()
	if err := d.Decode(dst); err != nil {
		var tooLarge *http.MaxBytesError
		if errors.As(err, &tooLarge) {
			return problem{http.StatusRequestEntityTooLarge, "request body too large"}
		}
		return bad(fmt.Sprintf("invalid JSON: %v", err))
	}
	if err := d.Decode(new(any)); !errors.Is(err, io.EOF) {
		return bad("expected exactly one JSON value")
	}
	return nil
}

func (a *App) Handler() http.Handler {
	m := http.NewServeMux()
	m.HandleFunc("GET /api/cases", func(w http.ResponseWriter, r *http.Request) {
		value, err := listCases(a.db)
		if err != nil {
			handleErrors(w, err)
			return
		}
		respond(w, 200, value)
	})
	m.HandleFunc("GET /api/cases/{id}", func(w http.ResponseWriter, r *http.Request) {
		var rev int64
		if raw, ok := r.URL.Query()["revision"]; ok {
			var err error
			rev, err = strconv.ParseInt(raw[0], 10, 64)
			if err != nil || rev <= 0 || len(raw) != 1 {
				handleErrors(w, bad("revision must be a positive integer"))
				return
			}
		}
		// Pin the case pointers and revision history to the same DB view.
		tx, err := a.db.Begin()
		if err != nil {
			handleErrors(w, err)
			return
		}
		defer tx.Rollback()
		d, err := detail(tx, r.PathValue("id"), rev)
		if err != nil {
			handleErrors(w, err)
			return
		}
		if err := tx.Commit(); err != nil {
			handleErrors(w, err)
			return
		}
		respond(w, 200, d)
	})
	m.HandleFunc("GET /api/assets/{digest}", func(w http.ResponseWriter, r *http.Request) {
		key := r.PathValue("digest")
		if !shaID.MatchString(key) {
			handleErrors(w, sql.ErrNoRows)
			return
		}
		v, err := assetBytes(a.db, key)
		if err != nil {
			handleErrors(w, err)
			return
		}
		w.Header().Set("Content-Type", "image/png")
		w.Header().Set("Cache-Control", "private, max-age=31536000, immutable")
		w.Header().Set("Content-Length", strconv.Itoa(len(v)))
		_, _ = w.Write(v)
	})
	m.HandleFunc("POST /api/cases", a.upload)
	m.HandleFunc("POST /api/cases/{id}/review", a.review)
	m.HandleFunc("POST /api/cases/{id}/inclusion", a.inclusion)
	m.HandleFunc("POST /api/cases/{id}/estimate", a.estimate)
	m.HandleFunc("GET /api/training/preview", a.preview)
	m.HandleFunc("GET /api/training/runs", a.runs)
	m.HandleFunc("POST /api/training/runs", a.startRun)
	m.HandleFunc("/api/", func(w http.ResponseWriter, r *http.Request) { handleErrors(w, sql.ErrNoRows) })
	if a.opts.Web != "" {
		files := http.FileServer(http.Dir(a.opts.Web))
		m.HandleFunc("/", func(w http.ResponseWriter, r *http.Request) {
			if r.Method != http.MethodGet && r.Method != http.MethodHead {
				w.Header().Set("Allow", "GET, HEAD")
				handleErrors(w, problem{http.StatusMethodNotAllowed, "method not allowed"})
				return
			}
			// Always fetch the app shell so navigation picks up a newly built bundle.
			// Digest-keyed scan and mask PNGs are immutable and remain cacheable.
			if r.URL.Path == "/" || r.URL.Path == "/index.html" {
				w.Header().Set("Cache-Control", "no-store")
			}
			files.ServeHTTP(w, r)
		})
	}
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("X-Content-Type-Options", "nosniff")
		m.ServeHTTP(w, r)
	})
}
