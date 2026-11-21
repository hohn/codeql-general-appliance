// Command cgasv is the CodeQL generic appliance workflow-state header provider.
//
// For now it only serves the page header fragment (cgasv/header). Like every
// cga* program it exposes a uniform `serve` command; the composite page in
// cga/web/ fetches the fragment by URL and places it in the layout grid.
//
// Usage:
//
//	cgasv serve     # serve the /header fragment
package main

import (
	"encoding/json"
	"fmt"
	"log"
	"net/http"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"time"
)

const component = "cgasv"
const defaultPort = "8601"

// loadSession reads the serve session CGAST (cga-tmp/session.json by default),
// so the header reflects the live pipeline state. A missing/unreadable session
// is treated as empty. This is the Go counterpart of cgalib/cgast.load_session.
func loadSession() map[string]any {
	path := os.Getenv("CGA_SESSION")
	if path == "" {
		root := os.Getenv("CGA_ROOT")
		if root == "" {
			root = "."
		}
		path = filepath.Join(root, "cga-tmp", "session.json")
	}
	data, err := os.ReadFile(path)
	if err != nil {
		return map[string]any{}
	}
	var m map[string]any
	if json.Unmarshal(data, &m) != nil {
		return map[string]any{}
	}
	return m
}

// activeComponents returns prefixes in workflow order, followed by any
// extension components in lexical order.
func activeComponents(session map[string]any) []string {
	seen := map[string]bool{}
	for k := range session {
		if i := strings.IndexByte(k, '-'); i > 0 {
			seen[k[:i]] = true
		}
	}
	order := []string{
		"cgadl", "cgaql", "cgamr", "cgamu", "cgasi", "cgaex",
	}
	out := make([]string, 0, len(seen))
	for _, c := range order {
		if seen[c] {
			out = append(out, c)
			delete(seen, c)
		}
	}
	extra := make([]string, 0, len(seen))
	for c := range seen {
		extra = append(extra, c)
	}
	sort.Strings(extra)
	out = append(out, extra...)
	return out
}

func esc(s string) string {
	r := ""
	for _, c := range s {
		switch c {
		case '&':
			r += "&amp;"
		case '<':
			r += "&lt;"
		case '>':
			r += "&gt;"
		case '"':
			r += "&quot;"
		default:
			r += string(c)
		}
	}
	return r
}

// fragment wraps body in the standard cga fragment envelope so all fragments,
// Go or Python, render uniformly under the composite page CSS.
func fragment(title, body, tip string) string {
	titleHTML := esc(title)
	if tip != "" {
		titleHTML = fmt.Sprintf(`<span class="cga-hover" title="%s">%s</span>`, esc(tip), esc(title))
	}
	return fmt.Sprintf(
		`<div class="cga-frag" data-component="%s"><div class="cga-frag-title">%s</div><div class="cga-frag-body">%s</div></div>`,
		component, titleHTML, body,
	)
}

func headerFragment() string {
	session := loadSession()
	active := activeComponents(session)
	pipeline := "idle"
	if len(active) > 0 {
		pipeline = strings.Join(active, " \u2192 ")
	}
	body := fmt.Sprintf(
		`<div class="cga-header-line">`+
			`<span class="cga-title">cga &mdash; codeql generic appliance</span>`+
			`<span class="cga-sub" title="cgasv/header -- workflow state">workflow state</span>`+
			`<span class="cga-sub" title="active CGAST pipeline">%s</span>`+
			`<span class="cga-clock" title="server time">%s</span>`+
			`</div>`,
		esc(pipeline),
		esc(time.Now().Format("2006-01-02 15:04:05")),
	)
	return fragment("CGA Workflow State", body, "cgasv/header -- workflow state provider")
}

func writeFrag(w http.ResponseWriter, html string) {
	w.Header().Set("Content-Type", "text/html; charset=utf-8")
	w.Header().Set("Access-Control-Allow-Origin", "*")
	w.Header().Set("Cache-Control", "no-store")
	fmt.Fprint(w, html)
}

func serve() {
	port := os.Getenv("CGA_CGASV_PORT")
	if port == "" {
		port = defaultPort
	}
	mux := http.NewServeMux()
	mux.HandleFunc("/header", func(w http.ResponseWriter, _ *http.Request) { writeFrag(w, headerFragment()) })
	mux.HandleFunc("/healthz", func(w http.ResponseWriter, _ *http.Request) {
		w.Header().Set("Access-Control-Allow-Origin", "*")
		fmt.Fprint(w, "ok")
	})
	mux.HandleFunc("/", func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/" {
			http.NotFound(w, r)
			return
		}
		w.Header().Set("Content-Type", "application/json")
		w.Header().Set("Access-Control-Allow-Origin", "*")
		json.NewEncoder(w).Encode(map[string]any{"component": component, "routes": []string{"/header"}})
	})
	addr := "127.0.0.1:" + port
	fmt.Printf("%s: serving fragments on http://%s (routes: /header)\n", component, addr)
	log.Fatal(http.ListenAndServe(addr, mux))
}

func main() {
	if len(os.Args) < 2 || os.Args[1] == "-h" || os.Args[1] == "--help" || os.Args[1] == "help" {
		fmt.Println("cgasv serve   # serve the /header fragment")
		return
	}
	switch os.Args[1] {
	case "serve":
		serve()
	default:
		fmt.Fprintf(os.Stderr, "%s: unknown command %q\n", component, os.Args[1])
		os.Exit(2)
	}
}
