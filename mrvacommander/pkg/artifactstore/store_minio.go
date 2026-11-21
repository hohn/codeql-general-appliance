package artifactstore

import (
	"bytes"
	"context"
	"fmt"
	"io"
	"log/slog"
	"math"

	"github.com/hohn/mrvacommander/pkg/common"

	"github.com/minio/minio-go/v7"
	"github.com/minio/minio-go/v7/pkg/credentials"
)

type MinIOArtifactStore struct {
	client *minio.Client

	// createBucket, when true, makes saveArtifact create the target
	// bucket on demand if it does not yet exist. This is appropriate for a
	// locally-run MinIO server that starts empty (standalone mode); it is
	// left false for cloud/BCS where the bucket is provisioned out-of-band
	// and MakeBucket would be denied.
	createBucket bool
}

// NewMinIOArtifactStore creates a MinIO-backed Store.
//
//   - secure selects HTTPS (true, cloud/BCS) vs plain HTTP (false, local dev).
//   - lookup selects virtual-host vs path-style bucket addressing.
//   - createBucket makes the store create the bucket on first write (used for
//     a local MinIO server that starts with no buckets).
func NewMinIOArtifactStore(endpoint, id, secret string, secure bool, lookup minio.BucketLookupType, createBucket bool) (*MinIOArtifactStore, error) {
	minioClient, err := minio.New(endpoint, &minio.Options{
		Creds:        credentials.NewStaticV4(id, secret, ""),
		Secure:       secure,
		BucketLookup: lookup,
	})
	if err != nil {
		return nil, err
	}

	slog.Info("Connected to MinIO store server", "endpoint", endpoint, "secure", secure)

	return &MinIOArtifactStore{
		client:       minioClient,
		createBucket: createBucket,
	}, nil
}

func (store *MinIOArtifactStore) GetQueryPack(location ArtifactLocation) ([]byte, error) {
	return store.getArtifact(location)
}

func (store *MinIOArtifactStore) SaveQueryPack(jobId int, data []byte) (ArtifactLocation, error) {
	key := fmt.Sprintf("%d-packs", jobId)
	return store.saveArtifact(AF_BUCKETNAME_PACKS, key, data, "application/gzip")
}

func (store *MinIOArtifactStore) GetResult(location ArtifactLocation) ([]byte, error) {
	return store.getArtifact(location)
}

func (store *MinIOArtifactStore) GetResultSize(location ArtifactLocation) (int, error) {
	bucket := location.Bucket
	key := location.Key

	objectInfo, err := store.client.StatObject(context.Background(), bucket, key, minio.StatObjectOptions{})
	if err != nil {
		return 0, err
	}

	if objectInfo.Size > math.MaxInt32 {
		return 0, fmt.Errorf("object size %d exceeds max int size", objectInfo.Size)
	}

	return int(objectInfo.Size), nil
}
func (store *MinIOArtifactStore) SaveResult(jobSpec common.JobSpec, language string, sha string, data []byte) (ArtifactLocation, error) {
	key := resultKey(jobSpec, language, sha)
	return store.saveArtifact(AF_BUCKETNAME_RESULTS, key, data, "application/zip")
}

func (store *MinIOArtifactStore) getArtifact(location ArtifactLocation) ([]byte, error) {
	bucket := location.Bucket
	key := location.Key

	object, err := store.client.GetObject(context.Background(), bucket, key, minio.GetObjectOptions{})
	if err != nil {
		return nil, err
	}
	defer object.Close()

	data, err := io.ReadAll(object)
	if err != nil {
		return nil, err
	}

	return data, nil
}

func (store *MinIOArtifactStore) saveArtifact(bucket, key string, data []byte,
	contentType string) (ArtifactLocation, error) {
	ctx := context.Background()
	exists, err := store.client.BucketExists(ctx, bucket)
	if err != nil {
		return ArtifactLocation{}, fmt.Errorf("checking bucket %q: %w", bucket, err)
	}
	if !exists {
		if !store.createBucket {
			slog.Error("Bucket does not exist", "bucket", bucket)
			return ArtifactLocation{}, fmt.Errorf("bucket %q does not exist", bucket)
		}
		if err := store.client.MakeBucket(ctx, bucket, minio.MakeBucketOptions{}); err != nil {
			// Tolerate a concurrent creation by another process/agent.
			exists2, existErr := store.client.BucketExists(ctx, bucket)
			if existErr != nil || !exists2 {
				return ArtifactLocation{}, fmt.Errorf("creating bucket %q: %w", bucket, err)
			}
		} else {
			slog.Info("Created MinIO bucket", "bucket", bucket)
		}
	}

	_, err = store.client.PutObject(ctx, bucket, key,
		bytes.NewReader(data), int64(len(data)), minio.PutObjectOptions{
			ContentType: contentType,
		})
	if err != nil {
		return ArtifactLocation{}, err
	}

	location := ArtifactLocation{
		Bucket: bucket,
		Key:    key,
	}

	return location, nil
}
