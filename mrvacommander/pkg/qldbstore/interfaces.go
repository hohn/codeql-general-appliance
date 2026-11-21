package qldbstore

import (
	"github.com/hohn/mrvacommander/pkg/common"
)

type Store interface {
	FindAvailableDBs(analysisReposRequested []common.NameWithOwner, language string) (
		notFoundRepos []common.NameWithOwner,
		foundRepos []common.NameWithOwner)

	// GetDatabase: return the database as a byte slice for the specified repository.
	// The slice is a CodeQL database -- a zip archive to be processed by the CodeQL CLI.
	GetDatabase(location common.NameWithOwner, language string) ([]byte, error)
}
