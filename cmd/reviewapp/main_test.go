package main

import (
	"net/http"
	"net/http/httptest"
	"testing"
)

func TestContainerBindOptIn(t *testing.T) {
	t.Setenv("REVIEWAPP_CONTAINER_BIND", "")
	if checkAddr("0.0.0.0:8787") == nil {
		t.Fatal("wildcard bind accepted without container opt-in")
	}
	t.Setenv("REVIEWAPP_CONTAINER_BIND", "1")
	if err := checkAddr("0.0.0.0:8787"); err != nil {
		t.Fatalf("container opt-in rejected: %v", err)
	}
	for _, addr := range []string{":8787", "192.0.2.1:8787", "[::]:8787", "0.0.0.0:70000"} {
		if checkAddr(addr) == nil {
			t.Errorf("unexpected container bind accepted: %s", addr)
		}
	}
}

func TestLocalOnly(t *testing.T) {
	t.Setenv("REVIEWAPP_CONTAINER_BIND", "")
	for _, addr := range []string{":8787", "0.0.0.0:8787", "[::]:8787", "localhost:8787"} {
		if err := checkAddr(addr); err == nil {
			t.Errorf("accepted non-literal-loopback bind %s", addr)
		}
	}
	if err := checkAddr("127.0.0.1:8787"); err != nil {
		t.Fatal(err)
	}
	h := localOnly(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { w.WriteHeader(204) }))
	for _, tc := range []struct {
		host, origin string
		want         int
	}{
		{"127.0.0.1:8787", "http://127.0.0.1:8787", 204},
		{"localhost:5173", "http://localhost:5173", 204},
		{"127.0.0.1:8787", "https://other.example", 403},
		{"evil.example:8787", "", 403},
	} {
		r := httptest.NewRequest("POST", "/api/cases", nil)
		r.Host = tc.host
		if tc.origin != "" {
			r.Header.Set("Origin", tc.origin)
		}
		w := httptest.NewRecorder()
		h.ServeHTTP(w, r)
		if w.Code != tc.want {
			t.Errorf("host=%s origin=%s: got %d, wanted %d", tc.host, tc.origin, w.Code, tc.want)
		}
	}
}
