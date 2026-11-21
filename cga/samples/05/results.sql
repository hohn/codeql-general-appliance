WITH databases(repository, sarif_name) AS (
  VALUES
    ('dsvpn/dsvpn', 'job-01-dsvpn-dsvpn.sarif'),
    ('file/file', 'job-02-file-file.sarif'),
    ('flex/flex', 'job-03-flex-flex.sarif'),
    ('inotify-tools/inotify-tools', 'job-04-inotify-tools-inotify-tools.sarif'),
    ('nnn/nnn', 'job-05-nnn-nnn.sarif')
), ranked AS (
  SELECT databases.repository, sarif_results.*,
         count(*) OVER (PARTITION BY databases.repository) AS finding_count,
         row_number() OVER (
           PARTITION BY databases.repository
           ORDER BY uri, start_line, start_column, rule_id, result_json
         ) AS finding_number
  FROM sarif_results
  JOIN databases ON regexp_extract(file_name, '[^/]+$') = databases.sarif_name
  WHERE "user" = 'bob'
)
SELECT databases.repository,
       coalesce(ranked.finding_count, 0) AS finding_count,
       ranked.finding_number, ranked.rule_id, ranked.uri,
       ranked.start_line, ranked.start_column
FROM databases
LEFT JOIN ranked ON databases.repository = ranked.repository
                AND ranked.finding_number <= 4
ORDER BY databases.repository, ranked.finding_number;
