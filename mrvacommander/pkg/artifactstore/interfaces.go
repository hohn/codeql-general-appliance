package artifactstore

import "github.com/hohn/mrvacommander/pkg/common"

type Store interface {
	// GetQueryPack retrieves the query pack from the specified location.
	GetQueryPack(location ArtifactLocation) ([]byte, error)

	// SaveQueryPack saves the query pack using the session ID and returns the artifact location.
	SaveQueryPack(sessionId int, data []byte) (ArtifactLocation, error)

	// GetResult retrieves the result from the specified location.
	GetResult(location ArtifactLocation) ([]byte, error)

	// GetResultSize retrieves the size of the result from the specified location.
	GetResultSize(location ArtifactLocation) (int, error)

	// SaveResult saves the result using the JobSpec and returns the artifact
	// location. The query language and the analyzed database's commit SHA are
	// woven into the object key: language guards against key collisions when the
	// SHA is absent (old/broken DBs yield a "no-sha-*" sentinel).
	SaveResult(jobSpec common.JobSpec, language string, sha string, data []byte) (ArtifactLocation, error)
}
