// Command cgamu is the CodeQL generic appliance MRVA user-view provider.
//
// It is a subset of the MRVA sysview and serves the /overview and /detail
// fragments for the composite page. It derives its rows from the named cgamr
// submissions in the shared CGAST.
//
// Usage:
//
//	cgamu serve     # serve the /overview and /detail fragments
package main

import (
	"encoding/json"
	"fmt"
	"log"
	"net/http"
	"os"
	"path/filepath"
	"sort"
	"strconv"
	"strings"
)

const component = "cgamu"
const defaultPort = "8605"

// loadSession reads the serve session CGAST (cga-tmp/session.json by default) so
// the user view reflects the live pipeline state. The Go counterpart of
// cgalib/cgast.load_session; a missing/unreadable session is treated as empty.
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

type sessionRow struct {
	session string
	user    string
	jobs    int
	state   string
}

func stringValue(v any) string {
	switch value := v.(type) {
	case string:
		return value
	case float64:
		return strconv.FormatFloat(value, 'f', -1, 64)
	case json.Number:
		return value.String()
	default:
		return ""
	}
}

// sessions returns one row for each cgamr submission currently recorded in
// the shared CGAST. No submission means no row: this view never invents work.
func sessions() []sessionRow {
	m := loadSession()
	items, ok := m["cgamr-submissions"].(map[string]any)
	if !ok {
		return []sessionRow{}
	}
	rows := make([]sessionRow, 0, len(items))
	for _, raw := range items {
		item, ok := raw.(map[string]any)
		if !ok {
			continue
		}
		jobs := 0
		if repos, ok := item["repositories"].([]any); ok {
			jobs = len(repos)
		}
		rows = append(rows, sessionRow{
			session: stringValue(item["session_id"]),
			user:    stringValue(item["user"]),
			jobs:    jobs,
			state:   strings.ReplaceAll(stringValue(item["status"]), "_", "-"),
		})
	}
	sort.SliceStable(rows, func(i, j int) bool {
		a, aerr := strconv.ParseInt(rows[i].session, 10, 64)
		b, berr := strconv.ParseInt(rows[j].session, 10, 64)
		if aerr == nil && berr == nil {
			return a < b
		}
		return rows[i].session < rows[j].session
	})
	return rows
}

func kv(rows [][2]string) string {
	s := `<table class="cga-kv">`
	for _, r := range rows {
		s += fmt.Sprintf(`<tr><th>%s</th><td>%s</td></tr>`, esc(r[0]), esc(r[1]))
	}
	return s + `</table>`
}

func overviewFragment() string {
	rows := sessions()
	users := map[string]bool{}
	names := ""
	for _, s := range rows {
		if !users[s.user] {
			users[s.user] = true
			if names != "" {
				names += ", "
			}
			names += s.user
		}
	}
	if names == "" {
		names = "(none)"
	}
	body := kv([][2]string{
		{"sessions", fmt.Sprintf("%d", len(rows))},
		{"users", names},
	})
	return fragment("cga mrva usrview", body, "cgamu/overview -- subset of sysview (live from session CGAST)")
}

func detailFragment() string {
	sessions := sessions()
	if len(sessions) == 0 {
		return fragment("cga mrva usrview -- detail",
			"<p>No MRVA submissions yet.</p>",
			"cgamu/detail -- per-session detail (live from session CGAST)")
	}
	rows := ""
	for _, s := range sessions {
		rows += fmt.Sprintf(
			`<tr><td>%s</td><td>%s</td><td>%d</td><td>%s</td></tr>`,
			esc(s.session), esc(s.user), s.jobs, esc(s.state),
		)
	}
	table := `<table class="cga-list"><thead><tr><th>session</th><th>user</th><th>jobs</th><th>state</th></tr></thead><tbody>` + rows + `</tbody></table>`
	return fragment("cga mrva usrview -- detail", table, "cgamu/detail -- per-session detail (live from session CGAST)")
}

func writeFrag(w http.ResponseWriter, html string) {
	w.Header().Set("Content-Type", "text/html; charset=utf-8")
	w.Header().Set("Access-Control-Allow-Origin", "*")
	w.Header().Set("Cache-Control", "no-store")
	fmt.Fprint(w, html)
}

func serve() {
	port := os.Getenv("CGA_CGAMU_PORT")
	if port == "" {
		port = defaultPort
	}
	mux := http.NewServeMux()
	mux.HandleFunc("/overview", func(w http.ResponseWriter, _ *http.Request) { writeFrag(w, overviewFragment()) })
	mux.HandleFunc("/detail", func(w http.ResponseWriter, _ *http.Request) { writeFrag(w, detailFragment()) })
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
		json.NewEncoder(w).Encode(map[string]any{"component": component, "routes": []string{"/overview", "/detail"}})
	})
	addr := "127.0.0.1:" + port
	fmt.Printf("%s: serving fragments on http://%s (routes: /overview, /detail)\n", component, addr)
	log.Fatal(http.ListenAndServe(addr, mux))
}

func main() {
	if len(os.Args) < 2 || os.Args[1] == "-h" || os.Args[1] == "--help" || os.Args[1] == "help" {
		fmt.Println("cgamu serve   # serve the /overview and /detail fragments")
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
