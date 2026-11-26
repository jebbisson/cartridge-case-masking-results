package reviewapp

import (
	"bytes"
	"crypto/sha256"
	"database/sql"
	"encoding/hex"
	"errors"
	"fmt"
	"image"
	"image/png"
	"io"
	"os"
	"path/filepath"
)

const maxAsset = 24 << 20
const maxPixels = 16_000_000

func digest(b []byte) string { s := sha256.Sum256(b); return hex.EncodeToString(s[:]) }
func validPNG(b []byte, width, height int, mask bool) error {
	if len(b) == 0 || len(b) > maxAsset {
		return errors.New("PNG size out of range")
	}
	cfg, err := png.DecodeConfig(bytes.NewReader(b))
	if err != nil {
		return errors.New("expected a valid PNG")
	}
	if width <= 0 || height <= 0 || cfg.Width != width || cfg.Height != height || width > maxPixels/height {
		return errors.New("PNG must match valid native dimensions")
	}
	im, err := png.Decode(bytes.NewReader(b))
	if err != nil {
		return errors.New("invalid PNG pixels")
	}
	if !mask {
		return nil
	}
	// Source masks are grayscale; browser Canvas exports opaque RGBA PNGs.
	set := false
	if grey, ok := im.(*image.Gray); ok {
		for _, v := range grey.Pix {
			switch v {
			case 0:
			case 255:
				set = true
			default:
				return errors.New("mask must contain only opaque black or white")
			}
		}
	} else {
		for y := 0; y < height; y++ {
			for x := 0; x < width; x++ {
				r, g, b, a := im.At(x, y).RGBA()
				if a != 65535 || r != g || r != b || (r != 0 && r != 65535) {
					return errors.New("mask must contain only opaque black or white")
				}
				set = set || r == 65535
			}
		}
	}
	if !set {
		return errors.New("present mask must not be empty")
	}
	return nil
}

func saveAsset(tx *sql.Tx, b []byte) (string, error) {
	s := digest(b)
	_, err := tx.Exec(`INSERT OR IGNORE INTO assets(digest,png) VALUES(?,?)`, s, b)
	return s, err
}
func assetBytes(q queryer, key string) ([]byte, error) {
	var b []byte
	err := q.QueryRow(`SELECT png FROM assets WHERE digest=?`, key).Scan(&b)
	return b, err
}

// Bundle paths are relative and may not follow a symlink outside their root.
func bundleFile(root, name string, max int64) ([]byte, error) {
	if name == "." || !filepath.IsLocal(name) {
		return nil, fmt.Errorf("expected relative bundle file: %q", name)
	}
	f, err := os.OpenRoot(root)
	if err != nil {
		return nil, err
	}
	defer f.Close()
	r, err := f.Open(name)
	if err != nil {
		return nil, err
	}
	defer r.Close()
	st, err := r.Stat()
	if err != nil {
		return nil, err
	}
	if !st.Mode().IsRegular() || st.Size() > max {
		return nil, fmt.Errorf("invalid bundle file: %q", name)
	}
	b, err := io.ReadAll(io.LimitReader(r, max+1))
	if err != nil {
		return nil, err
	}
	if int64(len(b)) > max {
		return nil, fmt.Errorf("bundle file exceeds limit: %q", name)
	}
	return b, nil
}

func readPNG(root, name, want string, w, h int, mask bool) ([]byte, error) {
	b, err := bundleFile(root, name, maxAsset)
	if err != nil {
		return nil, err
	}
	if want != "" && digest(b) != want {
		return nil, fmt.Errorf("SHA-256 does not match %s", name)
	}
	if err := validPNG(b, w, h, mask); err != nil {
		return nil, fmt.Errorf("%s: %w", name, err)
	}
	return b, nil
}

func verifyGeometry(name string, t Target, w, h int) error {
	switch t.Status {
	case "absent", "indeterminate", "not_annotated":
		if t.Start != nil || t.End != nil || t.mask != "" {
			return errors.New("non-present target cannot have geometry")
		}
	case "present":
		if name == drag {
			inside := func(p *Point) bool { return p != nil && p[0] >= 0 && p[0] < w && p[1] >= 0 && p[1] < h }
			if t.mask != "" || !inside(t.Start) || !inside(t.End) || *t.Start == *t.End {
				return errors.New("expected two distinct, ordered in-bounds points and no mask")
			}
		} else if t.mask == "" || t.Start != nil || t.End != nil {
			return errors.New("expected one native mask and no points")
		}
	default:
		return errors.New("invalid status")
	}
	return nil
}
