SELECT
  file_name,
  rule_id,
  uri,
  start_line,
  start_column
FROM sarif_results
WHERE rule_id = 'cpp/toy-sql-injection'
ORDER BY file_name, uri, start_line, start_column;
