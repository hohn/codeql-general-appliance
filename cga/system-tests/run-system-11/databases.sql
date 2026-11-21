WITH snapshots AS (
    SELECT *,
           row_number() OVER (
               PARTITION BY git_owner, git_repo
               ORDER BY ingestion_datetime_utc DESC, content_hash DESC
           ) AS snapshot_rank
    FROM metadata
    WHERE primary_language = 'cpp'
      AND tool_name IN ('codeql', 'codeql-cpp')
)
SELECT content_hash, build_cid, git_branch, git_commit_id, git_owner,
       git_repo, ingestion_datetime_utc, primary_language, result_url,
       tool_name, tool_version, projname, db_file_size
FROM snapshots
WHERE snapshot_rank = 1
ORDER BY git_owner, git_repo;
