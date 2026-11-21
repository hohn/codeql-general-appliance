package artifactstore

import (
	"fmt"

	"github.com/hohn/mrvacommander/pkg/common"
)

// resultKey builds the artifact object key for a job's result.
//
// Format: "<sessionID>-results-<language>-<owner>-<repo>-<sha>".
//
// The commit SHA versions the artifact so that re-analysis of the same
// owner/repo at a different revision does not collide. Because the SHA can be
// missing (old/broken DBs surface a "no-sha-in-db"/"no-sha-from-resolver"
// sentinel from the CodeQL runner), the query language is also embedded to keep
// keys discriminating in that degraded case.
func resultKey(jobSpec common.JobSpec, language, sha string) string {
	return fmt.Sprintf("%d-results-%s-%s-%s-%s",
		jobSpec.SessionID, language,
		jobSpec.NameWithOwner.Owner, jobSpec.NameWithOwner.Repo, sha)
}
