package main

import (
	"errors"
	"fmt"
	"io"
	"io/fs"
	"log"
	"net/http"
	"os"
	"path"
	"path/filepath"
	"strings"
)

type documentation struct {
	root string
}

func newDocumentation(root string) (http.Handler, error) {
	root, err := filepath.Abs(root)
	if err != nil {
		return nil, err
	}
	root, err = filepath.EvalSymlinks(root)
	if err != nil {
		return nil, err
	}
	d := &documentation{root: root}
	for _, name := range []string{"docs/cga-overview.html", "docs/cga-help.html"} {
		file, info, err := d.open(name)
		if err != nil {
			return nil, fmt.Errorf("documentation %s: %w", name, err)
		}
		file.Close()
		if !info.Mode().IsRegular() {
			return nil, fmt.Errorf("documentation %s is not a regular file", name)
		}
	}
	return http.StripPrefix("/documentation", d), nil
}

func documentPath(name string) bool {
	if !fs.ValidPath(name) {
		return false
	}
	for i, part := range strings.Split(name, "/") {
		if strings.HasPrefix(part, ".") && part != "." && !(i == 0 && part == ".agent-notes") {
			return false
		}
		if part == "cga-tmp" || part == "cga-prep-tmp" || part == "node_modules" {
			return false
		}
	}
	return true
}

func (d *documentation) open(name string) (*os.File, fs.FileInfo, error) {
	if !documentPath(name) {
		return nil, nil, fs.ErrNotExist
	}
	resolved, err := filepath.EvalSymlinks(filepath.Join(d.root, filepath.FromSlash(name)))
	if err != nil {
		return nil, nil, err
	}
	relative, err := filepath.Rel(d.root, resolved)
	if err != nil || !documentPath(filepath.ToSlash(relative)) {
		return nil, nil, fs.ErrNotExist
	}
	info, err := os.Stat(resolved)
	if err != nil {
		return nil, nil, err
	}
	if !info.IsDir() {
		if !info.Mode().IsRegular() {
			return nil, nil, fs.ErrNotExist
		}
		switch strings.ToLower(path.Ext(name)) {
		case "", ".html", ".css", ".js", ".json", ".map", ".md", ".org", ".txt",
			".svg", ".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico",
			".woff", ".woff2", ".ttf", ".eot", ".pdf",
			".go", ".py", ".sh", ".ql", ".sql", ".patch", ".tex",
			".tsv", ".csv", ".yaml", ".yml", ".toml", ".sha256":
		default:
			return nil, nil, fs.ErrNotExist
		}
	}
	file, err := os.Open(resolved)
	if err != nil {
		return nil, nil, err
	}
	info, err = file.Stat()
	if err != nil {
		file.Close()
		return nil, nil, err
	}
	if !info.IsDir() && path.Ext(name) == "" {
		var prefix [2]byte
		_, err := file.ReadAt(prefix[:], 0)
		if err != nil || string(prefix[:]) != "#!" {
			file.Close()
			if err != nil && !errors.Is(err, io.EOF) {
				return nil, nil, err
			}
			return nil, nil, fs.ErrNotExist
		}
	}
	return file, info, nil
}

func (d *documentation) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet && r.Method != http.MethodHead {
		w.Header().Set("Allow", "GET, HEAD")
		http.Error(w, "read-only documentation", http.StatusMethodNotAllowed)
		return
	}
	name := strings.TrimSuffix(strings.TrimPrefix(r.URL.Path, "/"), "/")
	if name == "" {
		name = "."
	}
	file, info, err := d.open(name)
	if err == nil && info.IsDir() {
		file.Close()
		if !strings.HasSuffix(r.URL.Path, "/") {
			http.Redirect(w, r, "/documentation"+r.URL.EscapedPath()+"/"+querySuffix(r.URL),
				http.StatusMovedPermanently)
			return
		}
		file, info, err = d.open(path.Join(name, "index.html"))
		if errors.Is(err, fs.ErrNotExist) {
			file, info, err = d.open(path.Join(name, "README.html"))
		}
		if err == nil && info.IsDir() {
			file.Close()
			err = fs.ErrNotExist
		}
	} else if err == nil && strings.HasSuffix(r.URL.Path, "/") {
		file.Close()
		err = fs.ErrNotExist
	}
	if err != nil {
		if errors.Is(err, fs.ErrNotExist) || errors.Is(err, fs.ErrPermission) {
			http.NotFound(w, r)
		} else {
			log.Printf("gateway documentation: %v", err)
			http.Error(w, "documentation unavailable", http.StatusInternalServerError)
		}
		return
	}
	defer file.Close()
	http.ServeContent(w, r, info.Name(), info.ModTime(), file)
}
