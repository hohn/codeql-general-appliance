package artifactstore

import (
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"sync"

	"github.com/hohn/mrvacommander/pkg/common"
)

// FilesystemArtifactStore persists artifacts under a single root
// directory. Layout: <root>/<bucket>/<key>
//
// Used by the single-VM "standalone" deployment mode where multiple
// processes (server + agents spawned by LocalArgoClient) share the
// same root directory.
type FilesystemArtifactStore struct {
	root string
	mu   sync.Mutex
}

// NewFilesystemArtifactStore creates a filesystem-backed Store rooted
// at the given directory. The directory is created on demand.
func NewFilesystemArtifactStore(root string) (*FilesystemArtifactStore, error) {
	if root == "" {
		return nil, fmt.Errorf("filesystem artifact store: root must not be empty")
	}
	if err := os.MkdirAll(root, 0o755); err != nil {
		return nil, fmt.Errorf("filesystem artifact store: %w", err)
	}
	return &FilesystemArtifactStore{root: root}, nil
}

// safeJoin returns <root>/<bucket>/<key>, rejecting traversal attempts.
func (store *FilesystemArtifactStore) safeJoin(bucket, key string) (string, error) {
	if strings.Contains(key, "..") || filepath.IsAbs(key) {
		return "", fmt.Errorf("invalid artifact key: %q", key)
	}
	return filepath.Join(store.root, bucket, key), nil
}

// writeAtomic writes data to path via a .tmp + rename so readers never
// observe partial files.
func writeAtomic(path string, data []byte) error {
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		return err
	}
	tmp := path + ".tmp"
	if err := os.WriteFile(tmp, data, 0o644); err != nil {
		return err
	}
	return os.Rename(tmp, path)
}

// GetQueryPack retrieves the query pack bytes at the specified location.
func (store *FilesystemArtifactStore) GetQueryPack(location ArtifactLocation) ([]byte, error) {
	path, err := store.safeJoin(location.Bucket, location.Key)
	if err != nil {
		return nil, err
	}
	store.mu.Lock()
	defer store.mu.Unlock()
	data, err := os.ReadFile(path)
	if err != nil {
		return nil, fmt.Errorf("query pack not found: %s: %w", location.Key, err)
	}
	return data, nil
}

// SaveQueryPack saves the query pack using the session ID and returns
// the artifact location.
func (store *FilesystemArtifactStore) SaveQueryPack(sessionId int, data []byte) (ArtifactLocation, error) {
	key := fmt.Sprintf("%d-packs", sessionId)
	loc := ArtifactLocation{Bucket: AF_BUCKETNAME_PACKS, Key: key}

	path, err := store.safeJoin(loc.Bucket, loc.Key)
	if err != nil {
		return ArtifactLocation{}, err
	}
	store.mu.Lock()
	defer store.mu.Unlock()
	if err := writeAtomic(path, data); err != nil {
		return ArtifactLocation{}, fmt.Errorf("save query pack: %w", err)
	}
	return loc, nil
}

// GetResult retrieves the result bytes at the specified location.
func (store *FilesystemArtifactStore) GetResult(location ArtifactLocation) ([]byte, error) {
	path, err := store.safeJoin(location.Bucket, location.Key)
	if err != nil {
		return nil, err
	}
	store.mu.Lock()
	defer store.mu.Unlock()
	data, err := os.ReadFile(path)
	if err != nil {
		return nil, fmt.Errorf("result not found: %s: %w", location.Key, err)
	}
	return data, nil
}

// GetResultSize returns the size in bytes of the result at the
// specified location.
func (store *FilesystemArtifactStore) GetResultSize(location ArtifactLocation) (int, error) {
	path, err := store.safeJoin(location.Bucket, location.Key)
	if err != nil {
		return 0, err
	}
	store.mu.Lock()
	defer store.mu.Unlock()
	info, err := os.Stat(path)
	if err != nil {
		return 0, fmt.Errorf("result not found: %s: %w", location.Key, err)
	}
	return int(info.Size()), nil
}

// SaveResult saves the result bytes for the given JobSpec.
func (store *FilesystemArtifactStore) SaveResult(jobSpec common.JobSpec, language string, sha string, data []byte) (ArtifactLocation, error) {
	key := resultKey(jobSpec, language, sha)
	loc := ArtifactLocation{Bucket: AF_BUCKETNAME_RESULTS, Key: key}

	path, err := store.safeJoin(loc.Bucket, loc.Key)
	if err != nil {
		return ArtifactLocation{}, err
	}
	store.mu.Lock()
	defer store.mu.Unlock()
	if err := writeAtomic(path, data); err != nil {
		return ArtifactLocation{}, fmt.Errorf("save result: %w", err)
	}
	return loc, nil
}
