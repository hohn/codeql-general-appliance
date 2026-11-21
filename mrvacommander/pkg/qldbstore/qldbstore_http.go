package qldbstore

import (
	"fmt"
	"io"
	"log/slog"
	"net/http"
	"strings"
	"time"

	"github.com/hohn/mrvacommander/pkg/common"
)

// HttpCodeQLDatabaseStore serves CodeQL databases from a plain HTTP server
// (e.g. a `python3 -m http.server` the test harness runs over its DB-zip
// tree). It is the standalone counterpart to the cluster deployment's HepcStore:
// where HepcStore shells out to /opt/example/bin/mrva-project-resolver, this store
// simply forms a URL from owner/repo and a fixed prefix and fetches over HTTP.
//
// URL layout (identical to FilesystemCodeQLDatabaseStore's on-disk layout, so
// the same tree can be served without rearranging):
//
//	<baseURL>/<owner>/<repo>/<owner>_<repo>_db.zip
//
// The database content itself is owned and served by the harness; the server
// and agent only read it. This keeps server/agent-owned state (the artifact
// store, Postgres) free of harness-written database files.
//
// The ``language`` argument is accepted for interface compatibility but
// ignored: the layout is keyed by owner/repo only and the database records
// its own primary language.
type HttpCodeQLDatabaseStore struct {
	baseURL string
	client  *http.Client
}

// NewHttpCodeQLDatabaseStore builds a store rooted at the given base URL
// (e.g. "http://127.0.0.1:9080"). A trailing slash is tolerated.
func NewHttpCodeQLDatabaseStore(baseURL string) *HttpCodeQLDatabaseStore {
	return &HttpCodeQLDatabaseStore{
		baseURL: strings.TrimRight(baseURL, "/"),
		client:  &http.Client{Timeout: 5 * time.Minute},
	}
}

func (store *HttpCodeQLDatabaseStore) dbURL(owner, repo string) string {
	return fmt.Sprintf("%s/%s/%s/%s_%s_db.zip",
		store.baseURL, owner, repo, owner, repo)
}

func (store *HttpCodeQLDatabaseStore) FindAvailableDBs(
	analysisReposRequested []common.NameWithOwner, _ string) (
	notFoundRepos []common.NameWithOwner,
	foundRepos []common.NameWithOwner) {

	for _, repo := range analysisReposRequested {
		url := store.dbURL(repo.Owner, repo.Repo)
		if store.exists(url) {
			foundRepos = append(foundRepos, repo)
		} else {
			notFoundRepos = append(notFoundRepos, repo)
		}
	}

	return notFoundRepos, foundRepos
}

// exists reports whether the DB zip is retrievable. It prefers a HEAD request
// and falls back to a ranged GET for servers (like python http.server) whose
// HEAD support is adequate but whose behaviour we want to double-check.
func (store *HttpCodeQLDatabaseStore) exists(url string) bool {
	resp, err := store.client.Head(url)
	if err != nil {
		slog.Warn("qldbstore http: HEAD failed", "url", url, "err", err)
		return false
	}
	defer resp.Body.Close()
	return resp.StatusCode == http.StatusOK
}

func (store *HttpCodeQLDatabaseStore) GetDatabase(
	location common.NameWithOwner, _ string) ([]byte, error) {

	url := store.dbURL(location.Owner, location.Repo)
	resp, err := store.client.Get(url)
	if err != nil {
		return nil, fmt.Errorf("http database fetch for %s/%s failed: %w",
			location.Owner, location.Repo, err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("database not found for %s/%s: %s returned %s",
			location.Owner, location.Repo, url, resp.Status)
	}

	data, err := io.ReadAll(resp.Body)
	if err != nil {
		return nil, fmt.Errorf("reading database body for %s/%s: %w",
			location.Owner, location.Repo, err)
	}
	return data, nil
}
