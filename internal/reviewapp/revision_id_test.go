package reviewapp

import (

	"encoding/json"
	"path/filepath"
	"testing"
)

func TestAppendRevisionDoesNotReuseRetiredID(t *testing.T) {
	a, err := Open(filepath.Join(t.TempDir(), "review.sqlite"), Options{})
	if err != nil {
		t.Fatal(err)
	}
	defer a.Close()
	_, err = a.db.Exec(`INSERT INTO assets VALUES('image',X'01');
		INSERT INTO cases(id,name,split,group_id,width,height,image,pixels,included)
		VALUES('case','scan','train','group',1,1,'image','pixels',1);`)
	if err != nil {
		t.Fatal(err)
	}
	// Model the state left by an administrative removal of the highest ID.
	_, err = a.db.Exec(`CREATE TABLE IF NOT EXISTS retired_revision_ids (id INTEGER PRIMARY KEY); INSERT INTO retired_revision_ids VALUES (7)`)
	if err != nil {
		t.Fatal(err)
	}
	labels := make(map[string]Target)
	for _, name := range targets {
		labels[name] = Target{Status: "indeterminate", Origin: "review"}
	}
	tx, err := a.db.BeginTx(t.Context(), nil)
	if err != nil {
		t.Fatal(err)
	}
	defer tx.Rollback()
	id, err := appendRevision(tx, Case{ID: "case"}, "draft", json.RawMessage(`{}`), labels, false)
	if err != nil || id != 8 {
		t.Fatalf("appendRevision = %d, %v; want 8, nil", id, err)
	}
}
