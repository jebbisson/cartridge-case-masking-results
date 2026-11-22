package main

import (
	"encoding/json"
	"errors"
	"flag"
	"net"
	"net/http/httptest"
	"os"
	"path/filepath"
	"testing"

	"cartridge-case-workbench/internal/reviewapp"
)

func TestStartupCorrectsTrainingPinLabelsBeforeProposalImport(t *testing.T) {
	manifest := os.Getenv("REVIEW_TEST_PILOT_MANIFEST")
	if manifest == "" {
		t.Skip("optional research corpus not configured; set REVIEW_TEST_PILOT_MANIFEST to run")
	}
	// Force run to return at the listen step without starting a server, after
	// exercising the real startup flags and imports against a temporary DB.
	listener, err := net.Listen("tcp4", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	defer listener.Close()
	oldFlags, oldArgs := flag.CommandLine, os.Args
	defer func() { flag.CommandLine, os.Args = oldFlags, oldArgs }()
	dir := t.TempDir()
	db := filepath.Join(dir, "review.sqlite")

	start := func(extra ...string) {
		t.Helper()
		flag.CommandLine = flag.NewFlagSet("reviewapp", flag.ContinueOnError)
		os.Args = append([]string{"reviewapp", "-db", db, "-addr", listener.Addr().String()}, extra...)
		var bind *net.OpError
		if err := run(); !errors.As(err, &bind) || bind.Op != "listen" {
			t.Fatalf("startup did not reach listen step: %v", err)
		}
	}
	const id = "3a23bc0c-4da6-4d8a-88fb-e3c359514673"
	lookup := func() reviewapp.Detail {
		t.Helper()
		a, err := reviewapp.Open(db, reviewapp.Options{})
		if err != nil {
			t.Fatal(err)
		}
		defer a.Close()
		w := httptest.NewRecorder()
		a.Handler().ServeHTTP(w, httptest.NewRequest("GET", "/api/cases/"+id, nil))
		if w.Code != 200 {
			t.Fatal(w.Body.String())
		}
		var d reviewapp.Detail
		if err := json.Unmarshal(w.Body.Bytes(), &d); err != nil {
			t.Fatal(err)
		}
		return d
	}
	start("-manifest", manifest)
	before := lookup()
	if len(before.Revisions) != 1 || before.Selected.Targets["firing_pin_impression"].Status != "present" {
		t.Fatal("unflagged startup changed the source schema")
	}
	write := func(name string, value any) {
		t.Helper()
		b, err := json.Marshal(value)
		if err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(filepath.Join(dir, name), b, 0600); err != nil {
			t.Fatal(err)
		}
	}
	labels := map[string]reviewapp.Target{}
	for k := range before.Selected.Targets {
		labels[k] = reviewapp.Target{Status: "not_annotated"}
	}
	write("proposal.json", map[string]any{"image_sha256": filepath.Base(before.ImageURL), "case_id": id, "source": "startup fixture", "targets": labels})
	write("proposals.jsonl", map[string]string{"case_id": id, "path": "proposal.json"})
	args := []string{"-correct-training-pin-labels", "-proposals", filepath.Join(dir, "proposals.jsonl")}
	start(args...)
	after := lookup()
	if len(after.Revisions) != 3 || after.Selected.Kind != "proposal" || after.Selected.Parent != after.Approved || after.Approved == before.Approved || after.Revisions[1].Targets["firing_pin_shear"].Status != "present" {
		t.Fatalf("expected correction to be approved before draft import: %+v", after.Case)
	}
	start(args...)
	if again := lookup(); len(again.Revisions) != 3 || again.Case != after.Case {
		t.Fatal("restart with both flags changed history or approvals")
	}
}
