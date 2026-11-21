WITH ranked AS (
  SELECT *,
         row_number() OVER (
           PARTITION BY git_owner, git_repo ORDER BY db_file_size
         ) AS rn
  FROM metadata
  WHERE primary_language = 'cpp'
    AND git_owner = 'node-native-watchdog'
    AND git_repo = 'node-native-watchdog'
)
SELECT content_hash, build_cid, git_branch, git_commit_id, git_owner, git_repo,
       ingestion_datetime_utc, primary_language, result_url, tool_name,
       tool_version, projname, db_file_size
FROM ranked
WHERE rn = 1;
