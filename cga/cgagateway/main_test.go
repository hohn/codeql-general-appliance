package main

import (
	"bufio"
	"encoding/json"
	"fmt"
	"io"
	"net"
	"net/http"
	"net/http/httptest"
	"net/url"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"testing"
	"time"
)

func backend(t *testing.T, handler http.HandlerFunc) (*httptest.Server, int) {
	t.Helper()
	server := httptest.NewServer(handler)
	t.Cleanup(server.Close)
	u, _ := url.Parse(server.URL)
	port, _ := strconv.Atoi(u.Port())
	return server, port
}

func proxyServer(t *testing.T, ports map[string]int) *httptest.Server {
	t.Helper()
	g, err := newGateway(ports)
	if err != nil {
		t.Fatal(err)
	}
	server := httptest.NewServer(g)
	t.Cleanup(server.Close)
	t.Cleanup(g.client.Transport.(*http.Transport).CloseIdleConnections)
	return server
}

func response(t *testing.T, method, address, body string, headers map[string]string) (*http.Response, string) {
	t.Helper()
	req, err := http.NewRequest(method, address, strings.NewReader(body))
	if err != nil {
		t.Fatal(err)
	}
	for key, value := range headers {
		if key == "Host" {
			req.Host = value
		} else {
			req.Header.Set(key, value)
		}
	}
	client := &http.Client{Timeout: 5 * time.Second, CheckRedirect: func(*http.Request, []*http.Request) error {
		return http.ErrUseLastResponse
	}}
	res, err := client.Do(req)
	if err != nil {
		t.Fatal(err)
	}
	defer res.Body.Close()
	data, err := io.ReadAll(res.Body)
	if err != nil {
		t.Fatal(err)
	}
	return res, string(data)
}

func TestProxyPreservesCommandsAndRejectsForeignOrigins(t *testing.T) {
	hits := 0
	upstream, port := backend(t, func(w http.ResponseWriter, r *http.Request) {
		hits++
		data, _ := io.ReadAll(r.Body)
		if r.URL.RequestURI() != "/api/action%2Fsession?name=a%2Fb" || string(data) != `{"action":"session"}` ||
			r.Method != "POST" || r.Header.Get("X-CGA-Bench") != "1" ||
			r.Header.Get("Content-Type") != "application/json" || r.Header.Get("Origin") != "http://"+r.Host ||
			r.Header.Get("X-Forwarded-Host") != "" {
			t.Errorf("command changed: %s %s %s %v", r.Method, r.URL, data, r.Header)
		}
		w.WriteHeader(201)
		io.WriteString(w, "recorded")
	})
	gateway := proxyServer(t, map[string]int{"/bench/": port})
	headers := map[string]string{
		"Origin": gateway.URL, "Content-Type": "application/json",
		"X-CGA-Bench": "1", "X-Forwarded-Host": "untrusted.invalid",
	}
	res, body := response(t, "POST", gateway.URL+"/bench/api/action%2Fsession?name=a%2Fb", `{"action":"session"}`, headers)
	if res.StatusCode != 201 || body != "recorded" {
		t.Fatalf("%d: %s", res.StatusCode, body)
	}
	for _, invalid := range []map[string]string{
		{"Origin": "http://untrusted.invalid"}, {"Origin": "null"},
		{"Host": "untrusted.invalid"}, {"Host": "127.0.0.1.evil.invalid"},
	} {
		res, _ := response(t, "POST", gateway.URL+"/bench/api/action", "{}", invalid)
		if res.StatusCode != 403 {
			t.Fatalf("invalid headers accepted: %v", invalid)
		}
	}
	if hits != 1 {
		t.Fatalf("rejected request reached upstream: %d", hits)
	}
	upstream.Close()
	res, body = response(t, "GET", gateway.URL+"/bench/", "", nil)
	if res.StatusCode != 502 || !strings.Contains(body, "viewer unavailable") {
		t.Fatalf("missing backend: %d %s", res.StatusCode, body)
	}
}

func TestRoutingConfigAndPresentationLinks(t *testing.T) {
	system, systemPort := backend(t, func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/sysview/data" {
			t.Errorf("system path was stripped: %s", r.URL)
		}
		w.Header().Set("Content-Type", "application/json")
		io.WriteString(w, `{"jobs":[]}`)
	})
	_, port := backend(t, func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		switch r.URL.Path {
		case "/api/model":
			fmt.Fprintf(w, `{"links":{"workflow_state":"http://127.0.0.1:8600/","mrva_sysview":"%s/sysview","replay":"/existing/replay"},"command_text":"http://127.0.0.1:8081/not-a-link"}`, system.URL)
		case "/api/sysview":
			w.WriteHeader(503)
			fmt.Fprintf(w, `{"available":false,"url":"%s/sysview","error":"offline"}`, system.URL)
		default:
			w.WriteHeader(404)
		}
	})
	gateway := proxyServer(t, map[string]int{
		"/analysis/": 8600, "/preparation/": 8500, "/flow/": 8720, "/unified/": port,
		"/flow/unified/": port, "/sysview": systemPort,
	})
	for _, prefix := range []string{"/analysis/", "/flow/"} {
		res, body := response(t, "GET", gateway.URL+prefix+"cga-config.js", "", nil)
		if res.StatusCode != 200 || !strings.Contains(body, `"cgadl":"`+prefix+`cgadl"`) ||
			strings.Contains(body, "127.0.0.1") {
			t.Fatalf("config: %d %s", res.StatusCode, body)
		}
	}
	res, body := response(t, "GET", gateway.URL+"/preparation/cga-prep-config.js", "", nil)
	if res.StatusCode != 200 || !strings.Contains(body, "window.CGA_PREP_CONFIG") ||
		!strings.Contains(body, `"cgacv":"/preparation/cgacv"`) {
		t.Fatalf("preparation config: %d %s", res.StatusCode, body)
	}
	_, body = response(t, "GET", gateway.URL+"/api/routes", "", nil)
	if !strings.Contains(body, `"/preparation/":8500`) {
		t.Fatalf("live route introspection missing: %s", body)
	}
	for _, prefix := range []string{"/unified/", "/flow/unified/"} {
		_, body := response(t, "GET", gateway.URL+prefix+"api/model", "", nil)
		var model struct {
			Links       map[string]string `json:"links"`
			CommandText string            `json:"command_text"`
		}
		if err := json.Unmarshal([]byte(body), &model); err != nil {
			t.Fatal(err)
		}
		if model.Links["workflow_state"] != "/analysis/" ||
			model.Links["mrva_sysview"] != "/sysview" ||
			model.Links["replay"] != prefix+"existing/replay" ||
			model.CommandText != "http://127.0.0.1:8081/not-a-link" {
			t.Fatalf("presentation changed evidence or lost its mount: %s", body)
		}
		res, body := response(t, "GET", gateway.URL+prefix+"api/sysview", "", nil)
		if res.StatusCode != 503 || !strings.Contains(body, `"available":false`) ||
			!strings.Contains(body, `"url":"/sysview"`) {
			t.Fatalf("upstream failure lost: %d %s", res.StatusCode, body)
		}
	}
	res, body = response(t, "GET", gateway.URL+"/sysview/data", "", nil)
	if res.StatusCode != 200 || !strings.Contains(body, `"jobs":[]`) {
		t.Fatalf("system path was stripped: %d %s", res.StatusCode, body)
	}
	res, _ = response(t, "GET", gateway.URL+"/sysview-other", "", nil)
	if res.StatusCode != 404 {
		t.Fatal("system route matched a different path")
	}
	res, _ = response(t, "GET", gateway.URL+"/analysis?x=1", "", nil)
	if res.StatusCode != 307 || res.Header.Get("Location") != "/analysis/?x=1" {
		t.Fatal("missing mounted-directory redirect")
	}
}

func TestLiveEditorDiscoveryRedirectsCookiesAndWebSocket(t *testing.T) {
	_, editorPort := backend(t, func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path == "/socket" {
			conn, rw, err := w.(http.Hijacker).Hijack()
			if err != nil {
				t.Error(err)
				return
			}
			defer conn.Close()
			fmt.Fprint(rw, "HTTP/1.1 101 Switching Protocols\r\nConnection: Upgrade\r\nUpgrade: websocket\r\n\r\n")
			rw.Flush()
			data := make([]byte, 4)
			if _, err := io.ReadFull(rw, data); err != nil {
				t.Error(err)
				return
			}
			rw.Write(data)
			rw.Flush()
			return
		}
		if r.URL.Path != "/login" {
			t.Errorf("wrong editor path: %s", r.URL)
		}
		http.SetCookie(w, &http.Cookie{Name: "code-server-session", Value: "authenticated", Path: "/", HttpOnly: true})
		w.Header().Set("Location", "/?workspace=%2Ftmp%2Fproject")
		w.WriteHeader(302)
	})
	editorURL := fmt.Sprintf("http://127.0.0.1:%d", editorPort)
	_, benchPort := backend(t, func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		switch r.URL.Path {
		case "/api/editors":
			json.NewEncoder(w).Encode(map[string]string{"session-7": editorURL})
		case "/api/editor":
			json.NewEncoder(w).Encode(map[string]any{
				"session": 7, "url": editorURL + "/?workspace=%2Ftmp%2Fproject",
				"login": editorURL + "/login?to=%2F", "password": "retained-password",
			})
		default:
			w.WriteHeader(404)
		}
	})
	gateway := proxyServer(t, map[string]int{"/bench/": benchPort})
	res, body := response(t, "POST", gateway.URL+"/bench/api/editor", `{"session":7}`, nil)
	if res.StatusCode != 200 || !strings.Contains(body, `"login":"/editors/session-7/login?to=%2F"`) ||
		!strings.Contains(body, `"password":"retained-password"`) {
		t.Fatalf("editor descriptor: %d %s", res.StatusCode, body)
	}
	res, _ = response(t, "POST", gateway.URL+"/editors/session-7/login", "password=retained-password", nil)
	if res.StatusCode != 302 || res.Header.Get("Location") != "/editors/session-7/?workspace=%2Ftmp%2Fproject" ||
		len(res.Cookies()) != 1 || res.Cookies()[0].Path != "/editors/session-7/" || !res.Cookies()[0].HttpOnly {
		t.Fatalf("editor login: %d %v", res.StatusCode, res.Header)
	}
	res, _ = response(t, "GET", gateway.URL+"/editors/session-8/", "", nil)
	if res.StatusCode != 502 {
		t.Fatal("missing editor did not report failure")
	}
	u, _ := url.Parse(gateway.URL)
	conn, err := net.DialTimeout("tcp", u.Host, 5*time.Second)
	if err != nil {
		t.Fatal(err)
	}
	defer conn.Close()
	conn.SetDeadline(time.Now().Add(5 * time.Second))
	fmt.Fprintf(conn, "GET /editors/session-7/socket HTTP/1.1\r\nHost: %s\r\nConnection: Upgrade\r\nUpgrade: websocket\r\nOrigin: %s\r\n\r\n", u.Host, gateway.URL)
	reader := bufio.NewReader(conn)
	upgrade, err := http.ReadResponse(reader, nil)
	if err != nil || upgrade.StatusCode != 101 {
		t.Fatalf("upgrade: %v %v", upgrade, err)
	}
	io.WriteString(conn, "ping")
	data := make([]byte, 4)
	if _, err := io.ReadFull(reader, data); err != nil || string(data) != "ping" {
		t.Fatalf("bidirectional upgrade: %q %v", data, err)
	}
}

func TestConfigurationRejectsInvalidRoutesAndPreservesOverrides(t *testing.T) {
	t.Setenv("CGA_PAGE_PORT", "8700")
	t.Setenv("CGA_CGADL_PORT", "8702")
	ports, err := defaults()
	if err != nil || ports["/analysis/"] != 8700 || ports["/analysis/cgadl/"] != 8702 {
		t.Fatalf("overrides: %v %v", ports, err)
	}

	for _, ports := range []map[string]int{{"/arbitrary/": 8600}, {"/bench/": 0}, {"/bench/": 65536}} {
		if _, err := newGateway(ports); err == nil {
			t.Fatalf("invalid configuration accepted: %v", ports)
		}
	}
	t.Setenv("CGA_PAGE_PORT", "")
	if _, err := defaults(); err == nil {
		t.Fatal("explicit empty override silently replaced")
	}
}

func TestDocumentationUsesLiveCheckoutAndMountedLinks(t *testing.T) {
	root := t.TempDir()
	files := map[string]string{
		"index.html":             `<a href="docs/cga-overview.html">Overview</a>`,
		"docs/index.html":        `<a href="cga-overview.html">Overview</a>`,
		"docs/cga-overview.html": `<a href="../cga/README.html">Reference</a>`,
		"docs/cga-help.html":     `<h1>CGA help</h1>`,
		"docs/readme-layout.css": `body { color: black; }`,
		"docs/book/index.html":   `<script src="book.js"></script>`,
		"docs/book/book.js":      `window.book = true;`,
		"cga/README.html":        `<link rel="stylesheet" href="../docs/readme-layout.css">`,
		".agent-notes/views.md":  "# View contracts\n",
		".cga/session.json":      `{"private":true}`,
		".git/config":            "private",
		"cga-tmp/session.json":   `{"private":true}`,
		"docs/result.sqlite":     "not documentation",
		"docs/opaque":            "not a source script",
		"docs/unindexed/note.md": "# No directory listing\n",
		"cga/cga-run":            "#!/usr/bin/env python3\nprint('source only')\n",
	}
	for name, content := range files {
		target := filepath.Join(root, name)
		if err := os.MkdirAll(filepath.Dir(target), 0755); err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(target, []byte(content), 0644); err != nil {
			t.Fatal(err)
		}
	}
	outside := filepath.Join(t.TempDir(), "outside.html")
	if err := os.WriteFile(outside, []byte("outside checkout"), 0644); err != nil {
		t.Fatal(err)
	}
	for name, target := range map[string]string{
		"external.html": outside,
		"runtime.html":  filepath.Join(root, ".cga/session.json"),
		"local.html":    filepath.Join(root, "cga/README.html"),
	} {
		if err := os.Symlink(target, filepath.Join(root, "docs", name)); err != nil {
			t.Fatal(err)
		}
	}
	g, err := newGateway(nil)
	if err != nil {
		t.Fatal(err)
	}
	g.documents, err = newDocumentation(root)
	if err != nil {
		t.Fatal(err)
	}
	server := httptest.NewServer(g)
	t.Cleanup(server.Close)
	res, body := response(t, "GET", server.URL+"/", "", nil)
	if res.StatusCode != 200 || !strings.Contains(body, `href="/documentation/"`) ||
		!strings.Contains(body, `href="/documentation/docs/cga-help.html"`) ||
		!strings.Contains(body, `href="/documentation/docs/book/"`) {
		t.Fatalf("documentation is missing from landing page: %d %s", res.StatusCode, body)
	}
	for name, content := range files {
		if strings.HasPrefix(name, ".cga/") || strings.HasPrefix(name, ".git/") ||
			strings.HasPrefix(name, "cga-tmp/") || strings.HasSuffix(name, ".sqlite") || name == "docs/opaque" {
			continue
		}
		res, body := response(t, "GET", server.URL+"/documentation/"+name, "", nil)
		if res.StatusCode != 200 || body != content || res.Header.Get("Cache-Control") != "no-store" {
			t.Errorf("%s: %d %s", name, res.StatusCode, body)
		}
		if strings.HasSuffix(name, ".css") && !strings.HasPrefix(res.Header.Get("Content-Type"), "text/css") {
			t.Errorf("stylesheet has unusable content type: %s", res.Header.Get("Content-Type"))
		}
	}
	for _, directory := range []string{"", "docs/", "docs/book/"} {
		res, body := response(t, "GET", server.URL+"/documentation/"+directory, "", nil)
		if res.StatusCode != 200 || body != files[directory+"index.html"] {
			t.Errorf("directory index %s: %d %s", directory, res.StatusCode, body)
		}
		res, body = response(t, "GET", server.URL+"/documentation/cga/", "", nil)
		if res.StatusCode != 200 || body != files["cga/README.html"] {
			t.Fatal("component directory did not open its rendered README")
		}
	}
	for _, redirect := range []struct {
		path, location string
		code           int
	}{
		{"/documentation?from=gateway", "/documentation/?from=gateway", 307},
		{"/documentation/docs?from=gateway", "/documentation/docs/?from=gateway", 301},
	} {
		res, _ := response(t, "GET", server.URL+redirect.path, "", nil)
		if res.StatusCode != redirect.code || res.Header.Get("Location") != redirect.location {
			t.Errorf("mounted redirect %s: %d %s", redirect.path, res.StatusCode, res.Header.Get("Location"))
		}
	}
	res, body = response(t, "HEAD", server.URL+"/documentation/docs/cga-overview.html", "", nil)
	if res.StatusCode != 200 || body != "" || !strings.HasPrefix(res.Header.Get("Content-Type"), "text/html") {
		t.Fatalf("documentation HEAD: %d %s", res.StatusCode, body)
	}
	updated := "<h1>Updated overview</h1>"
	if err := os.WriteFile(filepath.Join(root, "docs/cga-overview.html"), []byte(updated), 0644); err != nil {
		t.Fatal(err)
	}
	_, body = response(t, "GET", server.URL+"/documentation/docs/cga-overview.html", "", nil)
	if body != updated {
		t.Fatal("documentation changes required a gateway rebuild")
	}
	res, body = response(t, "GET", server.URL+"/documentation/docs/local.html", "", nil)
	if res.StatusCode != 200 || body != files["cga/README.html"] {
		t.Fatal("canonical in-checkout symlink was not served")
	}
	for _, name := range []string{
		".cga/session.json", ".git/config", "cga-tmp/session.json",
		"docs/external.html", "docs/runtime.html", "docs/result.sqlite",
		"../outside.html", "%2e%2e/outside.html", "docs/unindexed/", "docs/opaque",
		"missing.html", "cga/README.html/",
	} {
		res, _ := response(t, "GET", server.URL+"/documentation/"+name, "", nil)
		if res.StatusCode != 404 {
			t.Errorf("non-document path %s: %d", name, res.StatusCode)
		}
	}
	res, _ = response(t, "POST", server.URL+"/documentation/docs/cga-overview.html", "update", nil)
	if res.StatusCode != 405 || res.Header.Get("Allow") != "GET, HEAD" {
		t.Fatal("documentation accepted a modifying request")
	}
	res, _ = response(t, "GET", server.URL+"/documentation/docs/cga-overview.html", "",
		map[string]string{"Origin": "http://untrusted.invalid"})
	if res.StatusCode != 403 {
		t.Fatal("documentation bypassed gateway origin guards")
	}
}

func TestDocumentationRequiresExistingEntryPages(t *testing.T) {
	if _, err := newDocumentation(t.TempDir()); err == nil {
		t.Fatal("missing documentation was silently accepted")
	}
}
