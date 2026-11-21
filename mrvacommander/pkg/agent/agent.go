package agent

import (
	"fmt"
	"log/slog"
	"os"
	"path/filepath"

	"github.com/hohn/mrvacommander/pkg/artifactstore"
	"github.com/hohn/mrvacommander/pkg/codeql"
	"github.com/hohn/mrvacommander/pkg/common"
	"github.com/hohn/mrvacommander/pkg/qldbstore"
	"github.com/hohn/mrvacommander/pkg/queue"
	"github.com/hohn/mrvacommander/utils"

	"github.com/google/uuid"
)

/*
type RunnerSingle struct {
	queue queue.Queue
}

func NewAgentSingle(numWorkers int, v *Visibles) *RunnerSingle {
	r := RunnerSingle{queue: v.Queue}

	for id := 1; id <= numWorkers; id++ {
		go r.worker(id)
	}
	return &r
}

func (r *RunnerSingle) worker(wid int) {
	var job common.AnalyzeJob

	for {
		job = <-r.queue.Jobs()
		result, err := RunAnalysisJob(job)
		if err != nil {
			slog.Error("Failed to run analysis job", slog.Any("error", err))
			continue
		}
		r.queue.Results() <- result
	}
}
*/

// RunAnalysisJob runs a CodeQL analysis job (AnalyzeJob) returning an AnalyzeResult
func RunAnalysisJob(
	job queue.AnalyzeJob, artifacts artifactstore.Store, dbs qldbstore.Store) (queue.AnalyzeResult, error) {
	var result = queue.AnalyzeResult{
		Spec:           job.Spec,
		ResultCount:    0,
		ResultLocation: artifactstore.ArtifactLocation{},
		Status:         common.StatusFailed,
	}

	// Create a temporary directory
	tempDir := filepath.Join(os.TempDir(), uuid.New().String())
	if err := os.MkdirAll(tempDir, 0700); err != nil {
		return result, fmt.Errorf("failed to create temporary directory: %v", err)
	}
	defer os.RemoveAll(tempDir)

	// Download the query pack as a byte slice
	queryPackData, err := artifacts.GetQueryPack(job.QueryPackLocation)
	if err != nil {
		return result, fmt.Errorf("failed to download query pack: %w", err)
	}

	// Write the query pack data to the filesystem
	queryPackArchivePath := filepath.Join(tempDir, "query-pack.tar.gz")
	if err := os.WriteFile(queryPackArchivePath, queryPackData, 0700); err != nil {
		return result, fmt.Errorf("failed to write query pack archive to disk: %w", err)
	}

	// Make a directory and extract the query pack
	queryPackPath := filepath.Join(tempDir, "pack")
	if err := os.Mkdir(queryPackPath, 0700); err != nil {
		return result, fmt.Errorf("failed to create query pack directory: %w", err)
	}
	if err := utils.UntarGz(queryPackArchivePath, queryPackPath); err != nil {
		return result, fmt.Errorf("failed to extract query pack: %w", err)
	}

	databaseData, err := dbs.GetDatabase(job.Spec.NameWithOwner, string(job.QueryLanguage))
	if err != nil {
		slog.Error("Failed to get database",
			slog.String("owner", job.Spec.Owner),
			slog.String("repo", job.Spec.Repo),
			slog.Int("session_id", job.Spec.SessionID),
			slog.String("operation", "GetDatabase"),
			slog.Any("error", err),
		)
		return result, fmt.Errorf("failed to get database for %s/%s: %w",
			job.Spec.Owner, job.Spec.Repo, err)
	}

	// Write the CodeQL database data to the filesystem
	databasePath := filepath.Join(tempDir, "database.zip")
	if err := os.WriteFile(databasePath, databaseData, 0700); err != nil {
		return result, fmt.Errorf("failed to write CodeQL database to disk: %w", err)
	}

	// Perform the CodeQL analysis
	runResult, err := codeql.RunQuery(databasePath, job.QueryLanguage,
		queryPackPath, tempDir, job.Spec.NameWithOwner)
	if err != nil {
		return result, fmt.Errorf("failed to run analysis: %w", err)
	}

	// Generate a ZIP archive containing SARIF and BQRS files
	resultsArchive, err := codeql.GenerateResultsZipArchive(runResult)
	if err != nil {
		return result, fmt.Errorf("failed to generate results archive: %w", err)
	}

	// Upload the archive to storage
	slog.Debug("Results archive size", slog.Int("size", len(resultsArchive)))
	resultsLocation, err := artifacts.SaveResult(job.Spec, string(job.QueryLanguage), runResult.DatabaseSHA, resultsArchive)
	if err != nil {
		return result, fmt.Errorf("failed to save results archive: %w", err)
	}

	// flow: form result
	result = queue.AnalyzeResult{
		Spec:                 job.Spec,
		ResultCount:          runResult.ResultCount,
		ResultLocation:       resultsLocation,
		Status:               common.StatusSucceeded,
		SourceLocationPrefix: runResult.SourceLocationPrefix,
		DatabaseSHA:          runResult.DatabaseSHA,
	}

	return result, nil
}
