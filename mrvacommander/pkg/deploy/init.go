package deploy

import (
	"fmt"
	"log/slog"
	"os"
	"strings"

	"github.com/hohn/mrvacommander/pkg/artifactstore"
	"github.com/hohn/mrvacommander/pkg/qldbstore"
	"github.com/hohn/mrvacommander/pkg/queue"
	"github.com/minio/minio-go/v7"
)

func validateEnvVars(requiredEnvVars []string) {
	missing := false

	for _, envVar := range requiredEnvVars {
		if _, ok := os.LookupEnv(envVar); !ok {
			slog.Error("Missing required environment variable", "key", envVar)
			missing = true
		}
	}

	if missing {
		os.Exit(1)
	}
}

func InitBCSMinIOArtifactStore() (artifactstore.Store, error) {
	//replace with BCS conn

	requiredEnvVars := []string{
		"MRVA_BCS_ENDPOINT",
		"MRVA_BCS_ACCESS_KEY",
		"MRVA_BCS_SECRET_KEY",
		"MRVA_MINIO_VIRTUAL_HOST",
	}
	validateEnvVars(requiredEnvVars)

	//	S3 endpoint in DEV network zone : https://{bucket}.s3.dev.bcs.example.com
	// MRVA_BCS_ENDPOINT  is psa-mrva-dev.s3.xx.com

	endpoint := os.Getenv("MRVA_BCS_ENDPOINT")
	id := os.Getenv("MRVA_BCS_ACCESS_KEY")
	secret := os.Getenv("MRVA_BCS_SECRET_KEY")
	useVirtual := os.Getenv("MRVA_MINIO_VIRTUAL_HOST") == "1"

	var lookup minio.BucketLookupType
	var bucketName string
	var hostName string

	if useVirtual {
		// full virtual hostname syntax, with https, is https://{bucket}.s3.xx.com
		// For minio init, the base domain is the endpoint; here s3.xx.com
		var split bool
		bucketName, hostName, split = strings.Cut(endpoint, ".")
		if !split {
			return nil, fmt.Errorf("minio endpoint missing parts: %s", endpoint)
		}
		lookup = minio.BucketLookupDNS
	} else {
		// For minio path name syntax,the base domain here is the full MRVA_BCS_ENDPOINT
		bucketName = "mrvabucket"
		hostName = endpoint
		lookup = minio.BucketLookupPath
	}
	// TODO: unify into one. clean up state handling.
	artifactstore.AF_BUCKETNAME_RESULTS = bucketName
	artifactstore.AF_BUCKETNAME_PACKS = bucketName

	// Cloud/BCS: HTTPS, bucket provisioned out-of-band (do not create).
	store, err := artifactstore.NewMinIOArtifactStore(hostName, id, secret, true, lookup, false)
	if err != nil {
		return nil, fmt.Errorf("failed to initialize artifact store: %v", err)
	}
	return store, nil

}

// InitLocalMinIOArtifactStore initialises a MinIO-backed Store pointed at a
// locally-run MinIO server (single-VM standalone mode). Unlike the BCS/cloud
// store it uses plain HTTP, path-style bucket addressing, and creates the
// bucket on demand (a fresh local MinIO starts with no buckets).
//
// Connection is configured from the environment; Go supplies sane local
// defaults only for values the operator has not set (config philosophy: the
// harness keeps full override control):
//
//	MRVA_MINIO_ENDPOINT    default "localhost:9000"
//	MRVA_MINIO_ACCESS_KEY  default "minioadmin"
//	MRVA_MINIO_SECRET_KEY  default "minioadmin"
func InitLocalMinIOArtifactStore() (artifactstore.Store, error) {
	endpoint := getEnvOrDefault("MRVA_MINIO_ENDPOINT", "localhost:9000")
	id := getEnvOrDefault("MRVA_MINIO_ACCESS_KEY", "minioadmin")
	secret := getEnvOrDefault("MRVA_MINIO_SECRET_KEY", "minioadmin")

	// Single shared bucket for packs and results, path-style addressing.
	artifactstore.AF_BUCKETNAME_RESULTS = "mrvabucket"
	artifactstore.AF_BUCKETNAME_PACKS = "mrvabucket"

	slog.Info("artifactstore: local minio", "endpoint", endpoint, "bucket", "mrvabucket")
	store, err := artifactstore.NewMinIOArtifactStore(
		endpoint, id, secret, false, minio.BucketLookupPath, true)
	if err != nil {
		return nil, fmt.Errorf("failed to initialize local minio artifact store: %w", err)
	}
	return store, nil
}

// getEnvOrDefault returns the value of an environment variable, or the given
// default when the variable is unset or empty.
func getEnvOrDefault(key, def string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return def
}

func InitHEPCDatabaseStore() (qldbstore.Store, error) {
	requiredEnvVars := []string{
		"MRVA_HEPC_ENDPOINT",
		"MRVA_HEPC_CACHE_DURATION",
		"MRVA_HEPC_DATAVIACLI",
		"MRVA_HEPC_OUTDIR",
		"MRVA_HEPC_TOOL",
	}
	validateEnvVars(requiredEnvVars)

	endpoint := os.Getenv("MRVA_HEPC_ENDPOINT")

	store := qldbstore.NewHepcStore(endpoint)

	return store, nil
}

// InitFilesystemArtifactStore initialises a filesystem-backed artifact
// store rooted at MRVA_ARTIFACT_DIR. Used by mode=standalone.
func InitFilesystemArtifactStore() (artifactstore.Store, error) {
	root := os.Getenv("MRVA_ARTIFACT_DIR")
	if root == "" {
		return nil, fmt.Errorf("MRVA_ARTIFACT_DIR must be set in standalone mode")
	}
	slog.Info("artifactstore: filesystem", "root", root)
	return artifactstore.NewFilesystemArtifactStore(root)
}

// InitStandaloneArtifactStore selects the artifact store used by the single-VM
// standalone deployment (both the server and the agent subprocesses it spawns).
//
// The backend is chosen by MRVA_STANDALONE_STORAGE:
//
//	"minio" (default) -- a locally-run MinIO server (see InitLocalMinIOArtifactStore)
//	"filesystem"      -- a directory tree under MRVA_ARTIFACT_DIR
//
// MinIO is the default so that standalone matches the production storage model
// (blobs in object storage, only references in Postgres). The filesystem
// backend remains available as an override for setups without MinIO.
func InitStandaloneArtifactStore() (artifactstore.Store, error) {
	backend := getEnvOrDefault("MRVA_STANDALONE_STORAGE", "minio")
	switch backend {
	case "minio":
		return InitLocalMinIOArtifactStore()
	case "filesystem", "fs", "file":
		return InitFilesystemArtifactStore()
	default:
		return nil, fmt.Errorf("MRVA_STANDALONE_STORAGE: unknown backend %q (want \"minio\" or \"filesystem\")", backend)
	}
}

// InitFilesystemDatabaseStore initialises a local-filesystem CodeQL DB
// store rooted at the given directory (typically the --dbpath flag).
// Used by mode=standalone.
func InitFilesystemDatabaseStore(root string) (qldbstore.Store, error) {
	if root == "" {
		return nil, fmt.Errorf("dbpath must not be empty in standalone mode")
	}
	slog.Info("qldbstore: filesystem", "root", root)
	return qldbstore.NewLocalFilesystemCodeQLDatabaseStore(root), nil
}

// InitHttpDatabaseStore initialises an HTTP-backed CodeQL DB store that fetches
// databases from the base URL in MRVA_DB_SERVER_URL (a simple HTTP server the
// harness runs over its DB-zip tree). Used by mode=standalone.
func InitHttpDatabaseStore(baseURL string) (qldbstore.Store, error) {
	if baseURL == "" {
		return nil, fmt.Errorf("MRVA_DB_SERVER_URL must not be empty")
	}
	slog.Info("qldbstore: http", "baseURL", baseURL)
	return qldbstore.NewHttpCodeQLDatabaseStore(baseURL), nil
}

// InitStandaloneDatabaseStore selects the CodeQL DB store used by the
// single-VM standalone deployment (both the server and the agent subprocesses
// it spawns).
//
// When MRVA_DB_SERVER_URL is set, databases are fetched over HTTP from that
// base URL — the server/agent never read harness-written files, so the harness
// owns and serves the databases (matching the production model where DBs live
// outside the server). Otherwise it falls back to a local-filesystem store
// rooted at dbPathRoot (the --dbpath flag).
func InitStandaloneDatabaseStore(dbPathRoot string) (qldbstore.Store, error) {
	if baseURL := os.Getenv("MRVA_DB_SERVER_URL"); baseURL != "" {
		return InitHttpDatabaseStore(baseURL)
	}
	return InitFilesystemDatabaseStore(dbPathRoot)
}

// InitNoopQueue returns a Queue that discards everything. This is the
// only queue implementation: agents talk to the server entirely through
// PostgreSQL state and the pool manager ticks on its own timer, so no
// message broker is used in any mode.
func InitNoopQueue() queue.QueueWithSync {
	slog.Info("queue: noop")
	return queue.NewNoopQueue()
}
