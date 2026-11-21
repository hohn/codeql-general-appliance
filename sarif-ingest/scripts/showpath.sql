-- srfi showpath: show all kind:path-problem results.
-- Runs under both sqlite3 and duckdb (plain SQL only).
select
  user,
  file_name,
  rule_id,
  rule_name,
  uri,
  start_line,
  start_column
from sarif_results
where kind = 'path-problem'
order by user, file_name, uri, start_line, start_column;
