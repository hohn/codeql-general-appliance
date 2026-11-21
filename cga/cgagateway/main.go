// cgagateway joins the loopback viewers without changing their service ports.
package main

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"html/template"
	"io"
	"log"
	"net"
	"net/http"
	"net/http/httputil"
	"net/url"
	"os"
	"os/signal"
	"sort"
	"strconv"
	"strings"
	"syscall"
	"time"
)

type route struct {
	Prefix string
	Port   int
}

func (r route) target() string { return fmt.Sprintf("http://127.0.0.1:%d", r.Port) }

func (r route) path(path string) string {
	if r.Prefix == "/sysview" {
		return path
	}
	return strings.TrimSuffix(r.Prefix, "/") + "/" + strings.TrimPrefix(path, "/")
}

type gateway struct {
	routes    []route
	client    *http.Client
	documents http.Handler
}

func newGateway(ports map[string]int) (*gateway, error) {
	g := &gateway{client: &http.Client{
		Timeout: 5 * time.Second,
		Transport: &http.Transport{
			DialContext:           (&net.Dialer{Timeout: 5 * time.Second, KeepAlive: 30 * time.Second}).DialContext,
			ResponseHeaderTimeout: 60 * time.Second,
			IdleConnTimeout:       60 * time.Second,
			DisableCompression:    true,
		},
		CheckRedirect: func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse },
	}}
	for prefix, port := range ports {
		if !validPrefix(prefix) || port < 1 || port > 65535 {
			return nil, fmt.Errorf("invalid gateway route %q: %d", prefix, port)
		}
		g.routes = append(g.routes, route{prefix, port})
	}
	sort.Slice(g.routes, func(i, j int) bool {
		if len(g.routes[i].Prefix) == len(g.routes[j].Prefix) {
			return g.routes[i].Prefix < g.routes[j].Prefix
		}
		return len(g.routes[i].Prefix) > len(g.routes[j].Prefix)
	})
	return g, nil
}

func validPrefix(s string) bool {
	switch s {
	case "/analysis/", "/preparation/", "/unified/", "/bench/", "/flow/", "/flow/unified/", "/sysview", "/archives/":
		return true
	}
	for _, dashboard := range []string{"/analysis/", "/flow/", "/preparation/"} {
		for _, component := range dashboardComponents(dashboard) {
			if s == dashboard+component+"/" {
				return true
			}
		}
	}
	return false
}

var components = []string{"cgasv", "cgadl", "cgaql", "cgamr", "cgamu", "cgasi", "cgamx", "cgaex"}
var preparationComponents = []string{"cgacv", "cgasp", "cgadb", "cgaqg"}

func dashboardComponents(prefix string) []string {
	if prefix == "/preparation/" {
		return preparationComponents
	}
	return components
}

func defaults() (map[string]int, error) {
	ports := map[string]int{
		"/analysis/": 8600, "/preparation/": 8500, "/unified/": 8609, "/bench/": 8610,
		"/flow/": 8720, "/flow/unified/": 8729, "/sysview": 8081, "/archives/": 9080,
	}
	for i, component := range components {
		ports["/analysis/"+component+"/"] = 8601 + i
		ports["/flow/"+component+"/"] = 8721 + i
	}
	for i, component := range preparationComponents {
		ports["/preparation/"+component+"/"] = 8501 + i
	}
	env := map[string]string{
		"/analysis/": "CGA_PAGE_PORT", "/unified/": "CGA_CGAUV_PORT",
		"/sysview": "PORT", "/archives/": "DB_SERVER_PORT", "/preparation/": "CGA_PREP_PAGE_PORT",
	}
	for _, component := range components {
		env["/analysis/"+component+"/"] = "CGA_" + strings.ToUpper(component) + "_PORT"
	}
	for _, component := range preparationComponents {
		env["/preparation/"+component+"/"] = "CGA_PREP_" + strings.ToUpper(component) + "_PORT"
	}
	for prefix, name := range env {
		if text, ok := os.LookupEnv(name); ok {
			port, err := strconv.Atoi(text)
			if err != nil || port < 1 || port > 65535 {
				return nil, fmt.Errorf("%s must be a port in 1..65535", name)
			}
			ports[prefix] = port
		}
	}
	return ports, nil
}

func loopbackHost(host string) bool {
	parsed, err := url.Parse("http://" + host)
	if err != nil || parsed.User != nil || parsed.Path != "" || parsed.RawQuery != "" || parsed.Fragment != "" {
		return false
	}
	return parsed.Hostname() == "127.0.0.1" || parsed.Hostname() == "localhost"
}

func (g *gateway) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Cache-Control", "no-store")
	w.Header().Set("X-Content-Type-Options", "nosniff")
	if !loopbackHost(r.Host) {
		http.Error(w, "loopback Host required", http.StatusForbidden)
		return
	}
	if origin := r.Header.Get("Origin"); origin != "" && origin != "http://"+r.Host {
		http.Error(w, "same-origin gateway request required", http.StatusForbidden)
		return
	}
	if r.URL.Path == "/healthz" {
		w.Header().Set("Content-Type", "application/json")
		io.WriteString(w, "{\"service\":\"cga-gateway\"}\n")
		return
	}
	if r.URL.Path == "/" {
		w.Header().Set("Content-Type", "text/html; charset=utf-8")
		if err := landing.Execute(w, g.documents != nil); err != nil {
			log.Printf("gateway landing page: %v", err)
		}
		return
	}
	if r.URL.Path == "/api/routes" {
		w.Header().Set("Content-Type", "application/json")
		ports := map[string]int{}
		for _, rt := range g.routes {
			ports[rt.Prefix] = rt.Port
		}
		if err := json.NewEncoder(w).Encode(ports); err != nil {
			log.Printf("gateway routes: %v", err)
		}
		return
	}
	if g.documents != nil && r.URL.Path == "/documentation" {
		http.Redirect(w, r, "/documentation/"+querySuffix(r.URL), http.StatusTemporaryRedirect)
		return
	}
	if g.documents != nil && strings.HasPrefix(r.URL.Path, "/documentation/") {
		g.documents.ServeHTTP(w, r)
		return
	}
	if strings.HasPrefix(r.URL.Path, "/editors/") {
		g.editor(w, r)
		return
	}
	for _, rt := range g.routes {
		if r.URL.Path == strings.TrimSuffix(rt.Prefix, "/") && rt.Prefix != "/sysview" {
			http.Redirect(w, r, rt.Prefix+querySuffix(r.URL), http.StatusTemporaryRedirect)
			return
		}
		if strings.HasPrefix(r.URL.Path, rt.Prefix) &&
			(rt.Prefix != "/sysview" || r.URL.Path == "/sysview" || strings.HasPrefix(r.URL.Path, "/sysview/")) {
			configName := "cga-config.js"
			if rt.Prefix == "/preparation/" {
				configName = "cga-prep-config.js"
			}
			if (rt.Prefix == "/analysis/" || rt.Prefix == "/flow/" || rt.Prefix == "/preparation/") &&
				r.URL.Path == rt.Prefix+configName {
				g.dashboardConfig(w, rt.Prefix)
				return
			}
			g.proxy(w, r, rt)
			return
		}
	}
	http.NotFound(w, r)
}

func querySuffix(u *url.URL) string {
	if u.RawQuery != "" {
		return "?" + u.RawQuery
	}
	return ""
}

func (g *gateway) dashboardConfig(w http.ResponseWriter, prefix string) {
	config := map[string]string{}
	for _, component := range dashboardComponents(prefix) {
		config[component] = prefix + component
	}
	w.Header().Set("Content-Type", "text/javascript; charset=utf-8")
	data, _ := json.Marshal(config)
	name := "CGA_CONFIG"
	if prefix == "/preparation/" {
		name = "CGA_PREP_CONFIG"
	}
	fmt.Fprintf(w, "window.%s = %s;\n", name, data)
}

func (g *gateway) editor(w http.ResponseWriter, r *http.Request) {
	parts := strings.SplitN(strings.TrimPrefix(r.URL.Path, "/editors/"), "/", 2)
	index, err := strconv.Atoi(strings.TrimPrefix(parts[0], "session-"))
	if err != nil || index < 1 || parts[0] != fmt.Sprintf("session-%d", index) {
		http.NotFound(w, r)
		return
	}
	if len(parts) != 2 {
		http.Redirect(w, r, r.URL.Path+"/"+querySuffix(r.URL), http.StatusTemporaryRedirect)
		return
	}
	var bench *route
	for i := range g.routes {
		if g.routes[i].Prefix == "/bench/" {
			bench = &g.routes[i]
		}
	}
	if bench == nil {
		http.Error(w, "Bench route not configured", http.StatusBadGateway)
		return
	}
	req, _ := http.NewRequestWithContext(r.Context(), http.MethodGet, bench.target()+"/api/editors", nil)
	response, err := g.client.Do(req)
	if err != nil {
		log.Printf("gateway editor discovery: %v", err)
		http.Error(w, "Bench editor discovery unavailable", http.StatusBadGateway)
		return
	}
	defer response.Body.Close()
	if response.StatusCode != http.StatusOK {
		http.Error(w, "Bench editor discovery failed; restart Bench after upgrading", http.StatusBadGateway)
		return
	}
	var editors map[string]string
	if err := json.NewDecoder(io.LimitReader(response.Body, 1<<20)).Decode(&editors); err != nil {
		log.Printf("gateway editor discovery: %v", err)
		http.Error(w, "invalid Bench editor discovery", http.StatusBadGateway)
		return
	}
	target, err := url.Parse(editors[parts[0]])
	if err != nil || target == nil || target.Scheme != "http" || target.Hostname() != "127.0.0.1" ||
		target.User != nil || target.Path != "" || target.RawQuery != "" || target.Fragment != "" {
		http.Error(w, "editor is not running; open it from Bench first", http.StatusBadGateway)
		return
	}
	port, err := strconv.Atoi(target.Port())
	if err != nil || port < 1 || port > 65535 {
		http.Error(w, "invalid Bench editor port", http.StatusBadGateway)
		return
	}
	g.proxy(w, r, route{"/editors/" + parts[0] + "/", port})
}

func (g *gateway) proxy(w http.ResponseWriter, r *http.Request, rt route) {
	target, _ := url.Parse(rt.target())
	upstreamPath := r.URL.Path
	upstreamRawPath := r.URL.RawPath
	if rt.Prefix != "/sysview" {
		upstreamPath = "/" + strings.TrimPrefix(r.URL.Path, rt.Prefix)
		if upstreamRawPath != "" {
			upstreamRawPath = "/" + strings.TrimPrefix(upstreamRawPath, rt.Prefix)
		}
	}
	proxy := &httputil.ReverseProxy{
		Transport: g.client.Transport,
		Rewrite: func(pr *httputil.ProxyRequest) {
			pr.SetURL(target)
			pr.Out.URL.Path = upstreamPath
			pr.Out.URL.RawPath = upstreamRawPath
			pr.Out.Host = target.Host
			pr.Out.Header.Del("Forwarded")
			pr.Out.Header.Del("X-Forwarded-Prefix")
			pr.Out.Header.Del("X-Forwarded-Host")
			pr.Out.Header.Del("X-Forwarded-Proto")
			pr.Out.Header.Del("X-Forwarded-For")
			pr.Out.Header.Set("Accept-Encoding", "identity")
			if pr.In.Header.Get("Origin") != "" {
				pr.Out.Header.Set("Origin", target.String())
			}
		},
		ModifyResponse: func(response *http.Response) error {
			if location := response.Header.Get("Location"); location != "" {
				response.Header.Set("Location", g.link(location, rt))
			}
			cookies := response.Cookies()
			response.Header.Del("Set-Cookie")
			for _, cookie := range cookies {
				if strings.HasPrefix(cookie.Path, "/") {
					cookie.Path = rt.path(cookie.Path)
				}
				response.Header.Add("Set-Cookie", cookie.String())
			}
			if (response.StatusCode < 400 || upstreamPath == "/api/sysview") &&
				strings.HasPrefix(response.Header.Get("Content-Type"), "application/json") {
				return g.presentation(response, rt, upstreamPath)
			}
			return nil
		},
		ErrorHandler: func(w http.ResponseWriter, _ *http.Request, err error) {
			log.Printf("gateway %s (%s): %v", rt.Prefix, rt.target(), err)
			http.Error(w, "viewer unavailable; run cga serve start with its existing workspace configured", http.StatusBadGateway)
		},
	}
	proxy.ServeHTTP(w, r)
}

func (g *gateway) link(raw string, current route) string {
	u, err := url.Parse(raw)
	if err != nil {
		return raw
	}
	if u.IsAbs() && (u.Hostname() == "127.0.0.1" || u.Hostname() == "localhost") {
		if u.Port() == strconv.Itoa(current.Port) {
			return current.path(u.EscapedPath()) + querySuffix(u) + fragmentSuffix(u)
		}
		for _, rt := range g.routes {
			if u.Port() == strconv.Itoa(rt.Port) {
				return rt.path(u.EscapedPath()) + querySuffix(u) + fragmentSuffix(u)
			}
		}
	}
	if strings.HasPrefix(raw, "/") && !strings.HasPrefix(raw, "//") {
		return current.path(raw)
	}
	return raw
}

func fragmentSuffix(u *url.URL) string {
	if u.Fragment != "" {
		return "#" + u.EscapedFragment()
	}
	return ""
}

func (g *gateway) presentation(response *http.Response, rt route, path string) error {
	viewer := rt.Prefix == "/bench/" || rt.Prefix == "/unified/" || rt.Prefix == "/flow/unified/"
	if !viewer || (path != "/api/model" && path != "/api/view" && path != "/api/sysview" && path != "/api/editor") {
		return nil
	}
	body, err := io.ReadAll(response.Body)
	response.Body.Close()
	if err != nil {
		return err
	}
	var document map[string]json.RawMessage
	if err := json.Unmarshal(body, &document); err != nil {
		return fmt.Errorf("invalid viewer presentation: %w", err)
	}
	if path == "/api/editor" {
		var session int
		if err := json.Unmarshal(document["session"], &session); err != nil || session < 1 {
			return errors.New("editor descriptor has no valid session; restart Bench after upgrading")
		}
		for _, key := range []string{"url", "login"} {
			var raw string
			if err := json.Unmarshal(document[key], &raw); err != nil {
				return err
			}
			u, err := url.Parse(raw)
			if err != nil || u.Hostname() != "127.0.0.1" || u.Scheme != "http" {
				return errors.New("editor descriptor must use IPv4 loopback HTTP")
			}
			document[key], _ = json.Marshal(fmt.Sprintf("/editors/session-%d%s", session, u.RequestURI()))
		}
	} else {
		for _, key := range []string{"links", "system"} {
			var values map[string]json.RawMessage
			if json.Unmarshal(document[key], &values) != nil || values == nil {
				continue
			}
			for name, value := range values {
				var raw string
				if json.Unmarshal(value, &raw) == nil && (key == "links" || name == "url") {
					values[name], _ = json.Marshal(g.link(raw, rt))
				}
			}
			document[key], _ = json.Marshal(values)
		}
		if path == "/api/sysview" {
			var raw string
			if json.Unmarshal(document["url"], &raw) == nil {
				document["url"], _ = json.Marshal(g.link(raw, rt))
			}
		}
	}
	body, err = json.Marshal(document)
	if err != nil {
		return err
	}
	response.Body = io.NopCloser(bytes.NewReader(body))
	response.ContentLength = int64(len(body))
	response.Header.Set("Content-Length", strconv.Itoa(len(body)))
	return nil
}

var landing = template.Must(template.New("landing").Parse(`<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>CGA gateway</title><style>
body{font:16px system-ui,sans-serif;max-width:42rem;margin:4rem auto;padding:0 1rem;color:#222;background:#fafafa}
a{color:#14539a}li{margin:1rem 0}code{font-size:.9em}
</style></head><body><h1>CGA gateway</h1>
{{if .}}<h2>Documentation</h2>
<ul><li><a href="/documentation/">CGA overview</a></li>
<li><a href="/documentation/docs/cga-help.html">CGA help: tasks and commands</a></li>
<li><a href="/documentation/docs/book/">Reference manual</a></li></ul>
<p>Documentation is served live from this checkout; no local files are needed on
your workstation. Rebuild rendered pages after editing Markdown with
<code>make -C docs html</code>; build the optional reference manual with
<code>make -C docs book</code>.</p>{{end}}
<h2>Viewers</h2>
<ul><li><a href="/analysis/">Analysis dashboard</a></li>
<li><a href="/preparation/">Preparation dashboard</a></li>
<li><a href="/unified/">Unified View</a></li><li><a href="/bench/">Bench</a></li>
<li><a href="/flow/">mrva-flow dashboard</a></li>
<li><a href="/flow/unified/">mrva-flow Unified View</a></li>
<li><a href="/sysview">MRVA System View</a></li>
<li><a href="/archives/">Database archives</a></li></ul>
<p>Start configured viewers together with <code>cga serve start</code>, or use
their independent CGA commands. Open each session editor from Bench.
The gateway does not start workflows, editors, or MRVA services.</p>
</body></html>`))

func main() {
	port := flag.Int("port", 8599, "loopback listening port")
	config := flag.String("config", "", "JSON object mapping known route prefixes to loopback ports")
	docsRoot := flag.String("docs-root", "", "repository root for live documentation; supplied by cga gateway")
	flag.Parse()
	ports, err := defaults()
	if err != nil {
		log.Fatal(err)
	}
	if *config != "" {
		data, err := os.ReadFile(*config)
		if err != nil {
			log.Fatal(err)
		}
		if err := json.Unmarshal(data, &ports); err != nil {
			log.Fatal(err)
		}
		if ports == nil {
			log.Fatal("gateway configuration must be a JSON object")
		}
	}
	if *port < 1 || *port > 65535 {
		log.Fatal("gateway port must be 1..65535")
	}
	for prefix, target := range ports {
		if target == *port {
			log.Fatalf("gateway route %s points back to its own port", prefix)
		}
	}
	g, err := newGateway(ports)
	if err != nil {
		log.Fatal(err)
	}
	if *docsRoot != "" {
		g.documents, err = newDocumentation(*docsRoot)
		if err != nil {
			log.Fatal(err)
		}
	}
	server := &http.Server{
		Addr: fmt.Sprintf("127.0.0.1:%d", *port), Handler: g,
		ReadHeaderTimeout: 10 * time.Second, IdleTimeout: 60 * time.Second,
	}
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()
	go func() {
		<-ctx.Done()
		// Closing also drops gateway-owned upgraded connections when the process exits.
		server.Close()
	}()
	log.Printf("cga gateway: http://127.0.0.1:%d/", *port)
	if err := server.ListenAndServe(); err != nil && !errors.Is(err, http.ErrServerClosed) {
		log.Fatal(err)
	}
}
