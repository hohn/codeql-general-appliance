WITH
  expected(variant, mode) AS (
    VALUES ('vulnerable', 'none'), ('vulnerable', 'trace'),
           ('patched', 'none'), ('patched', 'trace')
  ),
  builds AS (
    SELECT unnest(databases) AS build
    FROM read_json_auto('../collection/manifest.json')
  ),
  ingestion AS (
    SELECT "cgasi-ingestions"."sqlite-injection" AS submission
    FROM read_json_auto('analysis-state.json')
  ),
  runs AS (
    SELECT unnest(submission.jobs) AS run,
           submission.status AS submission_status,
           submission."user" AS mrva_user,
           submission.session_id AS session_id,
           submission.query_pack AS query_pack
    FROM ingestion
  ),
  findings AS (
    SELECT "user", file_name, count(*) AS finding_count
    FROM sarif_results
    WHERE rule_id = 'cpp/toy-sql-injection'
    GROUP BY "user", file_name
  )
SELECT
  expected.variant,
  expected.mode,
  CASE
    WHEN build.repository IS NULL THEN 'missing build'
    WHEN submission_status IS DISTINCT FROM 'succeeded'
      OR run.status IS DISTINCT FROM 'succeeded' THEN 'missing/failed job'
    WHEN run.finding_count IS DISTINCT FROM coalesce(findings.finding_count, 0)
      OR run.mrva_result_count IS DISTINCT FROM run.finding_count
      THEN 'count mismatch'
    ELSE 'complete'
  END AS status,
  CASE WHEN submission_status = 'succeeded' AND run.status = 'succeeded'
    THEN coalesce(findings.finding_count, 0) END AS findings,
  run.finding_count AS ingested_findings,
  run.mrva_result_count,
  build.repository,
  mrva_user,
  session_id,
  query_pack
FROM expected
LEFT JOIN builds
  ON build.variant = expected.variant AND build.mode = expected.mode
LEFT JOIN runs ON run.repository = build.repository
LEFT JOIN findings
  ON findings."user" = mrva_user
 AND regexp_extract(findings.file_name, '[^/]+$')
     = regexp_extract(run.artifacts.sarif, '[^/]+$')
ORDER BY expected.variant DESC, expected.mode;
