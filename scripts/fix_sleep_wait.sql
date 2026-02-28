UPDATE script_versions
SET dag = (
    SELECT jsonb_set(
        sv.dag,
        '{nodes}',
        (
            SELECT jsonb_agg(
                CASE
                    WHEN n->>'id' = 'sleep_wait'
                    THEN jsonb_set(n, '{on_failure}', '"check_game_alive"')
                    ELSE n
                END
            )
            FROM jsonb_array_elements(sv.dag->'nodes') AS n
        )
    )
    FROM script_versions sv
    WHERE sv.id = '892c980b-fa38-4291-8c3c-b3eaa0a52172'
)
WHERE id = '892c980b-fa38-4291-8c3c-b3eaa0a52172';
