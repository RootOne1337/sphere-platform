-- Фикс 1: scan_all — fail_if_not_found → true (ничего не найдено = FAIL → sleep_wait 5s)
UPDATE script_versions
SET dag = jsonb_set(dag, '{nodes,7,action,fail_if_not_found}', 'true'::jsonb)
WHERE id = '892c980b-fa38-4291-8c3c-b3eaa0a52172';

-- Фикс 2: route_play — on_true → sleep_wait (не set_phase_playing!)
-- Тапнули play → ждём 5 секунд (загрузка), НЕ ставим phase=playing
UPDATE script_versions
SET dag = jsonb_set(dag, '{nodes,27,action,on_true}', '"sleep_wait"'::jsonb)
WHERE id = '892c980b-fa38-4291-8c3c-b3eaa0a52172';

-- Фикс 3: check_watchdog — бесконечный цикл (останавливается по CANCEL или global timeout 30мин)
UPDATE script_versions
SET dag = jsonb_set(dag, '{nodes,4,action,code}', '"return true"'::jsonb)
WHERE id = '892c980b-fa38-4291-8c3c-b3eaa0a52172';

-- Верификация
SELECT n->>'id' as node_id,
       n->'action'->>'fail_if_not_found' as fail_if_not_found,
       n->'action'->>'on_true' as on_true,
       n->'action'->>'code' as code
FROM script_versions sv, jsonb_array_elements(sv.dag->'nodes') AS n
WHERE sv.id = '892c980b-fa38-4291-8c3c-b3eaa0a52172'
  AND n->>'id' IN ('scan_all','route_play','check_watchdog');
