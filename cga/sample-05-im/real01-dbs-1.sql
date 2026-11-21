-- cgadl 1 (refined DB choice for case real01): narrow the baseline set to the
-- three repos the user decided to keep after inspecting chain A.
WITH ranked AS (
  SELECT *,
         row_number() OVER (
           PARTITION BY git_owner, git_repo ORDER BY db_file_size
         ) AS rn
  FROM metadata
  WHERE primary_language = 'cpp'
    AND (git_owner, git_repo) IN (
      ('flex', 'flex'),
      ('file', 'file'),
      ('nnn', 'nnn')
    )
)
SELECT content_hash, build_cid, git_branch, git_commit_id, git_owner, git_repo,
       ingestion_datetime_utc, primary_language, result_url, tool_name,
       tool_version, projname, db_file_size
FROM ranked
WHERE rn = 1
ORDER BY git_owner, git_repo;
