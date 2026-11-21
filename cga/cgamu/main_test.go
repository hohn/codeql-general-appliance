package main

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func writeSession(t *testing.T, value string) {
	t.Helper()
	path := filepath.Join(t.TempDir(), "session.json")
	if err := os.WriteFile(path, []byte(value), 0o600); err != nil {
		t.Fatal(err)
	}
	t.Setenv("CGA_SESSION", path)
}

func TestSessionsReflectOnlyRecordedSubmissions(t *testing.T) {
	writeSession(t, `{}`)
	if got := sessions(); len(got) != 0 {
		t.Fatalf("empty session returned %#v", got)
	}
	if detail := detailFragment(); !strings.Contains(detail, "No MRVA submissions yet") {
		t.Fatalf("empty detail is unclear: %s", detail)
	}

	writeSession(t, `{"cgamr-submissions":{"bob-1":{"user":"bob","session_id":1,"status":"succeeded","repositories":["flex/flex","maplibre/native"]}}}`)
	rows := sessions()
	if len(rows) != 1 || rows[0] != (sessionRow{"1", "bob", 2, "succeeded"}) {
		t.Fatalf("unexpected Bob rows: %#v", rows)
	}

	writeSession(t, `{"cgamr-submissions":{"eve-1":{"user":"eve","session_id":2,"status":"in_progress","repositories":["eve/repo"]},"bob-1":{"user":"bob","session_id":1,"status":"succeeded","repositories":["flex/flex","maplibre/native"]}}}`)
	rows = sessions()
	if len(rows) != 2 || rows[0].user != "bob" || rows[1].user != "eve" || rows[1].state != "in-progress" {
		t.Fatalf("unexpected accumulated rows: %#v", rows)
	}
}
