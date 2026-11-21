package server

import (
	"os"
	"os/exec"
	"path/filepath"
	"testing"
)

func TestSysViewPauseInBrowser(t *testing.T) {
	for _, tool := range []string{"node", "chromium"} {
		if _, err := exec.LookPath(tool); err != nil {
			t.Skipf("browser check requires %s", tool)
		}
	}
	page := filepath.Join(t.TempDir(), "sysview.html")
	if err := os.WriteFile(page, []byte(sysViewHTML), 0600); err != nil {
		t.Fatal(err)
	}
	cmd := exec.Command("node", "testdata/sysview-pause.mjs", page)
	if output, err := cmd.CombinedOutput(); err != nil {
		t.Fatalf("sysview browser check: %v\n%s", err, output)
	}
}
