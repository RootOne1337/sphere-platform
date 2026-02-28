UPDATE script_versions
SET dag = jsonb_set(
  dag,
  '{nodes}',
  (dag->'nodes') || '{"id":"validate_game_pid","retry":0,"action":{"type":"condition","code":"local pid = tostring(ctx.game_pid or '''')\nreturn #pid > 0 and pid ~= ''nil''","on_true":"reset_dead_alive","on_false":"increment_dead_count"},"on_success":"reset_dead_alive","on_failure":"increment_dead_count","timeout_ms":2000}'::jsonb
)
WHERE id = '892c980b-fa38-4291-8c3c-b3eaa0a52172'
RETURNING jsonb_array_length(dag->'nodes') as total_nodes;
