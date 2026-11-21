package qldbstore

import (
	"archive/tar"
	"bytes"
	"compress/gzip"
	"encoding/json"
	"fmt"
	"io"
	"log/slog"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"strconv"
	"strings"
	"sync"
	"time"

	"github.com/hohn/mrvacommander/pkg/common"
)

const defaultCacheDurationMinutes = 60

type HepcStore struct {
	Endpoint         string
	metadataCache    []HepcResult
	cacheLastUpdated time.Time
	cacheMutex       sync.Mutex
	cacheDuration    time.Duration
}

type HepcResult struct {
	GitBranch         string `json:"git_branch"`
	GitCommitID       string `json:"git_commit_id"`
	GitRepo           string `json:"git_repo"`
	IngestionDatetime string `json:"ingestion_datetime_utc"`
	ResultURL         string `json:"result_url"`
	ToolID            string `json:"tool_id"`
	ToolName          string `json:"tool_name"`
	ToolVersion       string `json:"tool_version"`
	Projname          string `json:"projname"`
}

func NewHepcStore(endpoint string) *HepcStore {
	cacheDuration := getMetaCacheDuration()
	return &HepcStore{
		Endpoint:      endpoint,
		cacheDuration: cacheDuration,
	}
}

func getMetaCacheDuration() time.Duration {
	durationStr := os.Getenv("MRVA_HEPC_CACHE_DURATION")
	if durationStr == "" {
		return time.Minute * defaultCacheDurationMinutes
	}
	duration, err := strconv.Atoi(durationStr)
	if err != nil {
		slog.Warn("Invalid MRVA_HEPC_CACHE_DURATION value. Using default",
			"value", durationStr, "default_minutes", defaultCacheDurationMinutes,
		)
		return time.Minute * defaultCacheDurationMinutes
	}
	return time.Minute * time.Duration(duration)
}

func (h *HepcStore) fetchViaHTTP() ([]HepcResult, error) {
	url := fmt.Sprintf("%s/index", h.Endpoint)
	resp, err := http.Get(url)
	if err != nil {
		slog.Warn("Error fetching metadata", "err", err)
		return nil, fmt.Errorf("error fetching metadata: %w", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		slog.Warn("Non-OK HTTP status", "status", resp.Status)
		return nil, fmt.Errorf("non-OK HTTP status: %s", resp.Status)
	}

	var results []HepcResult
	decoder := json.NewDecoder(resp.Body)
	for {
		var result HepcResult
		if err := decoder.Decode(&result); err == io.EOF {
			break
		} else if err != nil {
			slog.Warn("Error decoding JSON", "err", err)
			return nil, fmt.Errorf("error decoding JSON: %w", err)
		}
		results = append(results, result)
	}

	return results, nil
}
func (h *HepcStore) fetchViaCli() ([]HepcResult, error) {
	outDir := os.Getenv("MRVA_HEPC_OUTDIR")
	toolName := os.Getenv("MRVA_HEPC_TOOL")

	var missing []string

	if outDir == "" {
		slog.Error("Missing required environment variable", "var", "MRVA_HEPC_OUTDIR")
		missing = append(missing, "MRVA_HEPC_OUTDIR")
	}
	if toolName == "" {
		slog.Error("Missing required environment variable", "var", "MRVA_HEPC_TOOL")
		missing = append(missing, "MRVA_HEPC_TOOL")
	}

	if len(missing) > 0 {
		return nil, fmt.Errorf("missing required environment variables: %s", strings.Join(missing, ", "))
	}

	// Expand ~ in outDir
	if strings.HasPrefix(outDir, "~/") {
		home, err := os.UserHomeDir()
		if err != nil {
			slog.Error("Unable to get home directory", "error", err)
			return nil, err
		}
		outDir = filepath.Join(home, outDir[2:])
	}

	if err := os.MkdirAll(outDir, 0755); err != nil {
		slog.Error("Failed to create output directory", "error", err)
		return nil, err
	}

	jsonPath := filepath.Join(outDir, "spigot-results.json")

	// ----------------------
	// Go version of
	// /opt/example/bin/spigot-cli bulk-download-results    \
	// --tool-name "$TOOL_NAME"                    \
	// --metadata-only all                         \
	// > "$OUT_DIR/spigot-results.json"
	//
	outFile, err := os.Create(jsonPath)
	if err != nil {
		slog.Error("Failed to create spigot output file", "error", err)
		return nil, err
	}
	defer outFile.Close()

	cmd := exec.Command(
		"/opt/example/bin/spigot-cli",
		"bulk-download-results",
		"--tool-name", toolName,
		"--metadata-only", "all",
	)
	cmd.Stdout = outFile

	cmd.Stderr = os.Stderr // for error logging

	if err := cmd.Run(); err != nil {
		slog.Error("spigot-cli failed", "error", err)
		return nil, err
	}
	// ----------------------

	// Decode the resulting JSON file
	f, err := os.Open(jsonPath)
	if err != nil {
		slog.Error("Failed to open JSON output", "path", jsonPath, "error", err)
		return nil, fmt.Errorf("failed to open result file: %w", err)
	}
	defer f.Close()

	var results []HepcResult
	decoder := json.NewDecoder(f)
	for {
		var result HepcResult
		if err := decoder.Decode(&result); err == io.EOF {
			break
		} else if err != nil {
			slog.Warn("Error decoding CLI JSON", "error", err)
			return nil, fmt.Errorf("error decoding CLI JSON: %w", err)
		}
		results = append(results, result)
	}

	return results, nil
}

func (h *HepcStore) fetchMetadata() ([]HepcResult, error) {
	// Get via request or cli?
	hepcDataViaCli := os.Getenv("MRVA_HEPC_DATAVIACLI")
	if hepcDataViaCli == "1" {
		return h.fetchViaCli()
	} else {
		return h.fetchViaHTTP()
	}
}

func (h *HepcStore) FindAvailableDBs(analysisReposRequested []common.NameWithOwner, language string) (
	notFoundRepos []common.NameWithOwner,
	foundRepos []common.NameWithOwner) {

	slog.Info("FindAvailableDBs: checking for DBs")

	// Step 1: make temp dir
	tempDir, err := os.MkdirTemp("", "finddb-*")
	if err != nil {
		slog.Error("FindAvailableDBs: failed to make temp dir", "err", err)
		return
	}
	defer os.RemoveAll(tempDir)

	// Step 2: convert input to []string format
	var inputStrings []string
	for _, nwo := range analysisReposRequested {
		inputStrings = append(inputStrings, fmt.Sprintf("%s/%s", nwo.Owner, nwo.Repo))
	}

	// Step 3: write input JSON file
	inputPath := filepath.Join(tempDir, "input.json")
	inputFile, err := os.Create(inputPath)
	if err != nil {
		slog.Error("FindAvailableDBs: failed to create input file", "err", err)
		return
	}
	if err := json.NewEncoder(inputFile).Encode(inputStrings); err != nil {
		slog.Error("FindAvailableDBs: failed to write input JSON", "err", err)
		return
	}
	inputFile.Close()

	// Step 4: call executable
	outputPath := filepath.Join(tempDir, "output.json")
	cmd := exec.Command("/opt/example/bin/mrva-project-resolver", "check-exists",
		"--input-json", inputPath,
		"--output-json", outputPath,
		"--language", language,
	)
	cmd.Stdout = os.Stdout
	cmd.Stderr = os.Stderr
	if err := cmd.Run(); err != nil {
		slog.Error("FindAvailableDBs: command failed", "err", err)
		return
	}

	// Step 5: read and parse output
	outData, err := os.ReadFile(outputPath)
	if err != nil {
		slog.Error("FindAvailableDBs: failed to read output file", "err", err)
		return
	}
	var results []struct {
		Project string `json:"project"`
		Exists  string `json:"exists"` // JSON uses string "true"/"false"
	}
	if err := json.Unmarshal(outData, &results); err != nil {
		slog.Error("FindAvailableDBs: failed to unmarshal output JSON", "err", err)
		return
	}

	// Step 6: split results into found / not found
	for _, r := range results {
		parts := strings.SplitN(r.Project, "/", 2)
		if len(parts) != 2 {
			slog.Warn("FindAvailableDBs: malformed project string", "project", r.Project)
			continue
		}
		nwo := common.NameWithOwner{
			Owner: parts[0],
			Repo:  parts[1],
		}
		if r.Exists == "true" {
			foundRepos = append(foundRepos, nwo)
		} else {
			notFoundRepos = append(notFoundRepos, nwo)
		}
	}

	return notFoundRepos, foundRepos
}

func extractDatabaseFromTar(tarStream io.Reader) ([]byte, bool, error) {
	gzReader, err := gzip.NewReader(tarStream)
	if err != nil {
		slog.Error("failed to open gzip stream", "error", err)
		return nil, false, fmt.Errorf("failed to open gzip stream: %w", err)
	}
	defer gzReader.Close()

	tarReader := tar.NewReader(gzReader)

	for {
		hdr, err := tarReader.Next()
		if err == io.EOF {
			break
		}
		if err != nil {
			slog.Error("failed to read tar entry", "error", err)
			return nil, false, fmt.Errorf("failed to read tar entry: %w", err)
		}

		if hdr.Name == "artifacts/codeql_database.zip" {
			var buf bytes.Buffer
			if _, err := io.Copy(&buf, tarReader); err != nil {
				slog.Error("failed to extract zip from tar", "error", err)
				return nil, false, fmt.Errorf("failed to extract zip from tar: %w", err)
			}
			return buf.Bytes(), true, nil
		}
	}

	return nil, false, nil // not found
}

func (h *HepcStore) GetDatabase(location common.NameWithOwner, language string) ([]byte, error) {
	slog.Debug("GetDatabase: pulling database", "owner", location.Owner, "repo", location.Repo)

	// Step 1: create temp directory
	tempDir, err := os.MkdirTemp("", "getdb-*")
	if err != nil {
		return nil, fmt.Errorf("failed to make temp dir: %w", err)
	}
	defer os.RemoveAll(tempDir)

	// Step 2: prepare output file path
	outputPath := filepath.Join(tempDir, "foo.zip")

	// Step 3: construct identifier string
	projectID := fmt.Sprintf("%s/%s", location.Owner, location.Repo)

	// Step 4: run the external resolver
	cmd := exec.Command("/opt/example/bin/mrva-project-resolver", "download-codeql-db",
		projectID,
		"--language", language,
		"--output-file", outputPath,
	)
	cmd.Stdout = os.Stdout
	cmd.Stderr = os.Stderr

	if err := cmd.Run(); err != nil {
		return nil, fmt.Errorf("/opt/example/bin/mrva-project-resolver failed: %w", err)
	}

	// Step 5: read the zip file into memory
	data, err := os.ReadFile(outputPath)
	if err != nil {
		return nil, fmt.Errorf("failed to read output file: %w", err)
	}

	return data, nil
}

// replaceHepcURL replaces the fixed "http://hepc" with the value from
// MRVA_HEPC_ENDPOINT
func replaceHepcURL(originalURL string) string {
	hepcEndpoint := os.Getenv("MRVA_HEPC_ENDPOINT")
	if hepcEndpoint == "" {
		hepcEndpoint = "http://hepc:8070" // Default fallback
	}

	// Replace "http://hepc" at the beginning of the URL
	newURL := strings.Replace(originalURL, "http://hepc", hepcEndpoint, 1)

	return newURL
}
