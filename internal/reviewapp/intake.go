package reviewapp

import (
	"bytes"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"image/color"
	"image/png"
	"io"
	"net/http"
	"strings"
	"unicode"
)

func textField(s string, limit int) bool {
	return len(s) > 0 && len(s) <= limit && strings.TrimSpace(s) == s && strings.IndexFunc(s, unicode.IsControl) == -1
}

func (a *App) upload(w http.ResponseWriter, r *http.Request) {
	r.Body = http.MaxBytesReader(w, r.Body, maxAsset+(16<<10))
	m, err := r.MultipartReader()
	if err != nil {
		handleErrors(w, problem{http.StatusUnsupportedMediaType, "expected multipart/form-data"})
		return
	}
	var b []byte
	fields := map[string]string{}
	for {
		part, err := m.NextPart()
		if errors.Is(err, io.EOF) {
			break
		}
		if err != nil {
			handleErrors(w, uploadError(err))
			return
		}
		key := part.FormName()
		switch key {
		case "file", "image": // image is an alias used by the React form.
			if b != nil || part.FileName() == "" {
				handleErrors(w, bad("send exactly one PNG file"))
				return
			}
			b, err = io.ReadAll(io.LimitReader(part, maxAsset+1))
			if err != nil {
				handleErrors(w, uploadError(err))
				return
			}
			if len(b) > maxAsset {
				handleErrors(w, problem{413, "PNG is too large"})
				return
			}
		case "name", "group_id":
			if _, exists := fields[key]; exists || part.FileName() != "" {
				handleErrors(w, bad("invalid duplicate multipart field: "+key))
				return
			}
			value, err := io.ReadAll(io.LimitReader(part, 257))
			if err != nil {
				handleErrors(w, uploadError(err))
				return
			}
			if !textField(string(value), 256) {
				handleErrors(w, bad("invalid "+key))
				return
			}
			fields[key] = string(value)
		default:
			handleErrors(w, bad("unexpected multipart field"))
			return
		}
	}
	if len(b) == 0 || fields["name"] == "" || fields["group_id"] == "" {
		handleErrors(w, bad("file, name and group_id are required"))
		return
	}
	d, err := a.addScan(b, fields["name"], fields["group_id"])
	if err != nil {
		handleErrors(w, err)
		return
	}
	w.Header().Set("Location", "/api/cases/"+d.ID)
	respond(w, 201, d)
}
func uploadError(err error) error {
	var max *http.MaxBytesError
	if errors.As(err, &max) {
		return problem{413, "multipart upload is too large"}
	}
	return bad("invalid multipart upload")
}
func (a *App) addScan(b []byte, name, group string) (Detail, error) {
	cfg, err := png.DecodeConfig(bytes.NewReader(b))
	if err != nil || cfg.Width <= 0 || cfg.Height <= 0 || cfg.Width > maxPixels/cfg.Height {
		return Detail{}, bad("expected valid PNG within native dimension limits")
	}
	im, err := png.Decode(bytes.NewReader(b))
	if err != nil {
		return Detail{}, bad("invalid PNG pixels")
	}
	pix := sha256.New()
	row := make([]byte, 3*cfg.Width)
	for y := 0; y < cfg.Height; y++ {
		for x := 0; x < cfg.Width; x++ {
			p := color.NRGBAModel.Convert(im.At(x, y)).(color.NRGBA)
			row[3*x], row[3*x+1], row[3*x+2] = p.R, p.G, p.B
		}
		_, _ = pix.Write(row)
	}
	pixels := hex.EncodeToString(pix.Sum(nil))
	sha := digest(b)
	tx, err := a.db.Begin()
	if err != nil {
		return Detail{}, err
	}
	defer tx.Rollback()
	var exists bool
	if err := tx.QueryRow(`SELECT EXISTS(SELECT 1 FROM cases WHERE group_id=? COLLATE NOCASE AND split<>'train')`, group).Scan(&exists); err != nil {
		return Detail{}, err
	}
	if exists {
		return Detail{}, conflict("this source group is held out")
	}
	if err := tx.QueryRow(`SELECT EXISTS(SELECT 1 FROM cases WHERE image=? OR (pixels=? AND width=? AND height=?))`, sha, pixels, cfg.Width, cfg.Height).Scan(&exists); err != nil {
		return Detail{}, err
	}
	if exists {
		return Detail{}, conflict("this scan already exists")
	}
	if _, err := saveAsset(tx, b); err != nil {
		return Detail{}, err
	}
	id := "scan-" + sha
	if _, err := tx.Exec(`INSERT INTO cases(id,name,split,group_id,width,height,image,pixels,included) VALUES(?,?,'train',?,?,?,?,?,1)`, id, name, group, cfg.Width, cfg.Height, sha, pixels); err != nil {
		return Detail{}, err
	}
	ls := map[string]Target{}
	for _, t := range targets {
		ls[t] = Target{Status: "not_annotated"}
	}
	if _, err := appendRevision(tx, Case{ID: id}, "imported", json.RawMessage(`{"method":"local_upload"}`), ls, false); err != nil {
		return Detail{}, err
	}
	d, err := detail(tx, id, 0)
	if err != nil {
		return Detail{}, err
	}
	return d, tx.Commit()
}
