package reviewapp

import (
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestStaticWorkbenchAndAPIShareOneListener(t *testing.T) {
	root := t.TempDir()
	web := filepath.Join(root, "web")
	if err := os.Mkdir(web, 0700); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(web, "index.html"), []byte("review workbench"), 0600); err != nil {
		t.Fatal(err)
	}
	app, err := Open(filepath.Join(root, "test.sqlite"), Options{Web: web})
	if err != nil {
		t.Fatal(err)
	}
	defer app.Close()
	handler := app.Handler()
	for _, check := range []struct {
		method, path string
		code         int
		text         string
	}{
		{"GET", "/", http.StatusOK, "review workbench"},
		{"GET", "/api/cases", http.StatusOK, "[]"},
		{"POST", "/api/not-found", http.StatusNotFound, "not found"},
	} {
		w := httptest.NewRecorder()
		handler.ServeHTTP(w, httptest.NewRequest(check.method, check.path, nil))
		if w.Code != check.code || !strings.Contains(w.Body.String(), check.text) {
			t.Errorf("%s %s: %d %q", check.method, check.path, w.Code, w.Body.String())
		}
	}
	for _, method := range []string{http.MethodGet, http.MethodHead} {
		w := httptest.NewRecorder()
		handler.ServeHTTP(w, httptest.NewRequest(method, "/", nil))
		if got := w.Header().Get("Cache-Control"); got != "no-store" {
			t.Errorf("%s /: app shell Cache-Control = %q, want no-store", method, got)
		}
	}
}
