package qldbstore

import (
	"fmt"
	"github.com/hohn/mrvacommander/pkg/common"
	"os"
	"path/filepath"
)

// FilesystemCodeQLDatabaseStore serves CodeQL databases laid out on the
// local filesystem under a single root directory.
//
// Layout (compatible with the HEPC-produced layout for ergonomic
// crossover):
//
//	<basePath>/<owner>/<repo>/<owner>_<repo>_db.zip
//
// The ``language`` argument is accepted for interface compatibility
// with HepcStore but ignored: the on-disk layout is keyed by owner/repo
// only and the database itself records its primary language.
type FilesystemCodeQLDatabaseStore struct {
	basePath string
}

func NewLocalFilesystemCodeQLDatabaseStore(basePath string) *FilesystemCodeQLDatabaseStore {
	return &FilesystemCodeQLDatabaseStore{
		basePath: basePath,
	}
}

func (store *FilesystemCodeQLDatabaseStore) dbFile(owner, repo string) string {
	return filepath.Join(store.basePath,
		fmt.Sprintf("%s/%s/%s_%s_db.zip", owner, repo, owner, repo))
}

func (store *FilesystemCodeQLDatabaseStore) FindAvailableDBs(
	analysisReposRequested []common.NameWithOwner, _ string) (
	notFoundRepos []common.NameWithOwner,
	foundRepos []common.NameWithOwner) {

	for _, repo := range analysisReposRequested {
		filePath := store.dbFile(repo.Owner, repo.Repo)
		if _, err := os.Stat(filePath); os.IsNotExist(err) {
			notFoundRepos = append(notFoundRepos, repo)
		} else {
			foundRepos = append(foundRepos, repo)
		}
	}

	return notFoundRepos, foundRepos
}

func (store *FilesystemCodeQLDatabaseStore) GetDatabase(
	location common.NameWithOwner, _ string) ([]byte, error) {

	filePath := store.dbFile(location.Owner, location.Repo)
	if _, err := os.Stat(filePath); os.IsNotExist(err) {
		return nil, fmt.Errorf("database not found for %s/%s", location.Owner, location.Repo)
	}
	return os.ReadFile(filePath)
}

